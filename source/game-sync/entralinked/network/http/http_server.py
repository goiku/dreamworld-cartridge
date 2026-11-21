"""The web server for everything the DS reaches over HTTP."""
import os
import io
import logging
import socket
import socketserver
import threading
from time import perf_counter, thread_time
from collections.abc import Callable, Iterable
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer

from flask import Flask
from tlslite import TLSSocketServerMixIn, X509CertChain
from tlslite.handshakesettings import HandshakeSettings
from tlslite.sessioncache import SessionCache
from tlslite.utils.keyfactory import parsePEMKey
from werkzeug.serving import BaseWSGIServer, WSGIRequestHandler as WerkzeugRequestHandler, make_server
from werkzeug.wrappers import Request, Response

from ...context import Context
from ...paths import SERVER_PEM_PATH
from .dls_handler import DlsHandler
from .gts_handler import GtsHandler
from .nas_handler import NasHandler
from .pgl_handler import PglHandler

logger = logging.getLogger(__name__)

HTTPS_PORT = 443  # the DS is only given an address, so the port can't change
HTTP_PORT = 8081


class _GameRequestLog:
    def setup(self):
        super().setup()
        # Some handhelds wait for an ACK before sending the next short segment.
        # Older Python versions don't name Windows' SIO_TCP_SET_ACK_FREQUENCY.
        quick_ack = getattr(socket, "TCP_QUICKACK", -1744830441 if os.name == "nt" else None)
        if quick_ack is not None:
            try:
                self.connection.setsockopt(socket.IPPROTO_TCP, quick_ack, 1)
            except OSError:
                pass  # Older network stacks can still exchange saves normally.

    def log_request(self, code="-", size="-"):
        # DS query strings may contain session tokens and encoded Pokémon records.
        path = getattr(self, "path", "").partition("?")[0]
        logger.info("%s %s -> %s", getattr(self, "command", ""), path[:128], code)


class NintendoHttpRequestHandler(_GameRequestLog, WerkzeugRequestHandler):
    """Use HTTP/1.0 for the DS's plain HTTP requests."""

    protocol_version = "HTTP/1.0"
    # Werkzeug writes HTTP headers and the short result separately.
    disable_nagle_algorithm = True


class NintendoTLSRequestHandler(_GameRequestLog, WSGIRequestHandler):
    # wsgiref flushes after writing the response body. Send a short Game Sync reply
    # in one TLS record instead of separate records for status, headers and payload.
    wbufsize = 16 * 1024

    def setup(self):
        super().setup()
        # tlslite returns a raw SocketIO even when makefile is asked for buffering.
        # Buffer headers and keep short TLS records from causing large temporary reads.
        if isinstance(self.rfile, io.RawIOBase):
            self.rfile = io.BufferedReader(self.rfile, 16 * 1024)


class RequestBodyMiddleware:
    def __init__(self, wsgi_app: Callable[..., Iterable[bytes]]) -> None:
        self.wsgi_app = wsgi_app

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Iterable[bytes]:
        try:
            remaining = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            return Response(status=400)(environ, start_response)
        if remaining < 0:
            return Response(status=400)(environ, start_response)

        wsgi_input = environ.get("wsgi.input")
        upload = (environ.get("REQUEST_METHOD") == "POST"
                  and environ.get("PATH_INFO", "").rstrip("/") == "/dsio/gw"
                  and Request(environ).args.get("p") == "savedata.upload")
        if upload:
            started = perf_counter()
            cpu_started = thread_time()
            total = remaining
            quarter = 1
            last_read = started
            longest_read = 0.0
            logger.info("Tuck-in upload started: expecting %d bytes", remaining)

        if remaining > 0 and wsgi_input is not None:
            chunks = []

            while remaining > 0:
                chunk = wsgi_input.read(min(remaining, 16 * 1024))
                if not chunk:
                    # A partial upload or acknowledgement must not reach Game Sync.
                    logger.warning("Incomplete %s body for %s (%d bytes missing)",
                                   environ.get("REQUEST_METHOD"), environ.get("PATH_INFO"), remaining)
                    return Response(status=400)(environ, start_response)
                chunks.append(chunk)
                remaining -= len(chunk)
                if upload:
                    now = perf_counter()
                    longest_read = max(longest_read, now - last_read)
                    last_read = now
                    while quarter <= 4 and (total - remaining) * 4 >= total * quarter:
                        logger.info("Tuck-in upload %d%% after %.3fs (%d bytes received)",
                                    quarter * 25, now - started, total - remaining)
                        quarter += 1

            body = b"".join(chunks)
            environ["wsgi.input"] = io.BytesIO(body)
            environ["CONTENT_LENGTH"] = str(len(body))

        if upload:
            received = perf_counter()
            receive_cpu = thread_time() - cpu_started
            response = self.wsgi_app(environ, start_response)
            logger.info("Tuck-in upload timing: receive %.3fs, handle %.3fs, "
                        "receive thread CPU %.3fs, longest read interval %.3fs",
                        received - started, perf_counter() - received, receive_cpu, longest_read)
            return response
        return self.wsgi_app(environ, start_response)


class TLSServer(TLSSocketServerMixIn, socketserver.ThreadingMixIn, WSGIServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, private_key: Any, cert_chain: X509CertChain, app: Flask, bind: str) -> None:
        super().__init__((bind, HTTPS_PORT), NintendoTLSRequestHandler)
        self.private_key = private_key
        self.cert_chain = cert_chain
        self.session_cache = SessionCache()
        self.set_app(app)

    def handshake(self, connection: Any) -> bool:
        settings = HandshakeSettings()
        settings.minVersion = (3, 0)
        settings.maxVersion = (3, 1)
        settings.cipherNames = ["rc4"]
        settings.macNames = ["md5", "sha"]
        settings.keyExchangeNames = ["rsa"]

        connection.handshakeServer(
            privateKey=self.private_key,
            certChain=self.cert_chain,
            settings=settings,
            sessionCache=self.session_cache,
        )
        return True


def create_app(context: Context) -> Flask:
    """Create the Flask app with the handler's routes."""
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    app.wsgi_app = RequestBodyMiddleware(app.wsgi_app)

    for handler in (NasHandler(context), PglHandler(context), DlsHandler(context), GtsHandler(context)):
        app.register_blueprint(handler.blueprint())

    @app.route("/")
    def conntest() -> tuple[str, int, dict[str, str]]:
        """Answer the DS's connection test, which fails without this header."""
        return (
            "<html><head><title>HTML Page</title></head>"
            "<body>This is test.html page</body></html>",
            200,
            {"Content-Type": "text/html", "X-Organization": "Nintendo"},
        )

    return app


class HttpServer:
    """Serves the app over HTTP(S)."""

    def __init__(self, context: Context, http_port: int = HTTP_PORT, bind: str | None = None) -> None:
        self.app = create_app(context)
        self.bind = bind or os.environ.get("DW_GAME_BIND", "127.0.0.1")
        self.http_port = http_port
        self.http_server: BaseWSGIServer | None = None
        self.http_thread: threading.Thread | None = None
        self.server: TLSServer | None = None
        self.server_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the HTTP and HTTPS servers."""
        self.http_server = make_server(
            self.bind,
            self.http_port,
            self.app,
            threaded=True,
            request_handler=NintendoHttpRequestHandler,
        )
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()
        logger.info("HTTP server listening @ port %d", self.http_port)

        pem = SERVER_PEM_PATH.read_text(encoding="UTF-8") # update the cert in 2076
        chain = X509CertChain()
        chain.parsePemList(pem)
        self.server = TLSServer(parsePEMKey(pem, private=True), chain, self.app, self.bind)

        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        logger.info("HTTPS server listening @ port %d", HTTPS_PORT)

    def stop(self) -> None:
        """Stop listening. Do nothing for a server that isn't running."""
        for name, server, thread in (("HTTP", self.http_server, self.http_thread),
                                     ("HTTPS", self.server, self.server_thread)):
            if server is None:
                continue
            server.shutdown()
            server.server_close()
            if thread is not None:
                thread.join()
            logger.info("%s server stopped", name)

        self.http_server = self.http_thread = self.server = self.server_thread = None
