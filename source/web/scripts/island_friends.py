"""Serve and synchronize authorized island pairs while this Dream World server is running."""

import logging
import socket
import sqlite3
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor

from flask import Flask, Response, request
from waitress import create_server, wasyncore

from utils import island_peers as peers
from utils import offline_islands as islands

log = logging.getLogger(__name__)


def wire_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = peers.LIMIT

    @app.post("/v1/<action>")
    def exchange(action: str) -> Response:
        try:
            result = peers.dispatch(
                request.remote_addr or "",
                action,
                request.headers.get("X-Island-Key", ""),
                request.get_data(cache=False),
            )
        except (peers.PeerError, islands.IslandError, ValueError) as exc:
            log.debug("Island exchange rejected: %s", type(exc).__name__)
            return Response(status=403)
        return Response(result, mimetype="application/octet-stream", headers={"Cache-Control": "no-store"})

    return app


def supervise(stop: threading.Event) -> None:
    """Independent outbound polls keep a sleeping peer from blocking the inbound listener."""
    running: dict[str, Future] = {}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="island-exchange") as pool:
        while not stop.wait(1):
            for key, future in list(running.items()):
                if future.done():
                    try:
                        future.result()
                    except (peers.PeerError, islands.IslandError, sqlite3.Error, OSError) as exc:
                        log.debug("Will retry island sync: %s", type(exc).__name__)
                    del running[key]
            try:
                rows = peers.link_rows()
            except sqlite3.Error:
                continue
            for row in rows:
                if len(running) >= 4 or row["attempted"] > peers.now() - peers.INTERVAL:
                    break
                if row["id"] not in running:
                    running[row["id"]] = pool.submit(peers.sync, row)


def main(stop: threading.Event | None = None) -> None:
    app = wire_app()
    channels: dict = {}
    active: dict = {}
    stop = stop or threading.Event()
    thread = threading.Thread(target=supervise, args=(stop,), name="island-pair-sync", daemon=True)
    thread.start()
    next_scan = 0.0
    try:
        while not stop.is_set():
            if time.monotonic() >= next_scan:
                targets = peers.interfaces()
                for iface in set(active) - set(targets):
                    listener = active.pop(iface)
                    for ch in list(listener.active_channels.values()):
                        ch.handle_close()
                    listener.close()
                    listener.task_dispatcher.shutdown()
                for iface in targets:
                    if iface in active:
                        continue
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        sock.bind((iface.split("/")[0], peers.PORT))
                    except OSError:
                        sock.close()
                        log.warning("Island pairing listener unavailable on %s.", iface.split("/")[0])
                    else:
                        active[iface] = create_server(
                            app,
                            map=channels,
                            sockets=[sock],
                            threads=4,
                            max_request_body_size=peers.LIMIT,
                            channel_timeout=20,
                        )
                peers.advertise(list(active))
                next_scan = time.monotonic() + 12
            if channels:
                wasyncore.loop(timeout=0.5, count=1, map=channels)
            else:
                stop.wait(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        peers.advertise([])
        for listener in active.values():
            listener.task_dispatcher.shutdown()
        wasyncore.close_all(channels)


if __name__ == "__main__":
    main()
