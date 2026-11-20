"""A DNS server."""
import logging
import os

from dnslib import QTYPE, RR, TXT, A
from dnslib.server import BaseResolver, DNSHandler, DNSRecord, DNSServer

logger = logging.getLogger(__name__)

DNS_PORT = 53  # the DS is only given an address, so the port can't change


class FixedResolver(BaseResolver):
    """Resolves every A query to one address."""

    def __init__(self, host_address: str) -> None:
        self.host_address = host_address

    def resolve(self, request: DNSRecord, handler: DNSHandler) -> DNSRecord:
        """Answer one query."""
        reply = request.reply()

        if (request.q.qtype == QTYPE.TXT and str(request.q.qname).lower() == "guide-status.dreamworld.invalid."
                and handler.client_address[0] == self.host_address):
            reply.add_answer(RR(request.q.qname, QTYPE.TXT, rdata=TXT(f"dreamworld-dns-v1 {self.host_address}"), ttl=0))
        elif request.q.qtype == QTYPE.A:
            reply.add_answer(RR(request.q.qname, QTYPE.A, rdata=A(self.host_address), ttl=0))
        else:
            logger.warning("Unsupported record type in DNS question: %s", request.q.qtype)

        return reply


class DnsServer:
    """Runs the resolver on UDP port 53."""

    def __init__(self, host_address: str, bind: str | None = None) -> None:
        self.host_address = host_address
        self.bind = bind or os.environ.get("DW_GAME_BIND", "127.0.0.1")
        self.server: DNSServer | None = None

    def start(self) -> None:
        """Start answering queries."""
        self.server = DNSServer(FixedResolver(self.host_address), port=DNS_PORT, address=self.bind)
        self.server.start_thread()
        logger.info("DNS server listening @ port %d", DNS_PORT)

    def stop(self) -> None:
        """Stop the server. Do nothing if it isn't running."""
        if self.server is None:
            return

        self.server.stop()
        self.server = None
        logger.info("DNS server stopped")
