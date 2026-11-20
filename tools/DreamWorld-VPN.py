# /// script
# requires-python = ">=3.11"
# dependencies = ["dnslib==0.9.26"]
# ///
"""Forward Dream World traffic between two computers on a private Tailscale network."""

import argparse
import asyncio
from contextlib import AsyncExitStack
from ipaddress import IPv4Address, IPv4Network
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import struct
import sys
import tempfile
import time

from dnslib import A, DNSError, DNSRecord, QTYPE, RCODE, RR, TXT


LOG = logging.getLogger("dreamworld-vpn")
TAILNET = IPv4Network("100.64.0.0/10")
LAN = tuple(IPv4Network(prefix) for prefix in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
WEB_PORTS = (8080, 8081, 8083, 8084, 8085, 8086, 8087, 8088)
GAME_PORTS = (80, 443, 29900, 29901, 28910)
DISCOVERY_PORTS = (27900, 27901)
TUNNEL_PORT = 29910
PLAYER_PORTS = range(31000, 31128)
PACKET = struct.Struct("!4sHH")
MAGIC = b"DWU1"
DEFAULT_RELAY_IP = "192.168.242.1"
DNS_NAMES = {
    "conntest.nintendowifi.net.",
    "nas.nintendowifi.net.",
    "gpcm.gs.nintendowifi.net.",
    "gpsp.gs.nintendowifi.net.",
    "gamestats2.gs.nintendowifi.net.",
    "natneg1.gs.nintendowifi.net.",
    "natneg2.gs.nintendowifi.net.",
    "natneg3.gs.nintendowifi.net.",
    "dls1.nintendowifi.net.",
    "ds.pokemon-gl.com.",
}
AVAILABILITY_SUFFIX = ".available.gs.nintendowifi.net."
GAME_SUFFIXES = (AVAILABILITY_SUFFIX, ".ms0.gs.nintendowifi.net.", ".master.gs.nintendowifi.net.",
                 ".gamestats.gs.nintendowifi.net.", ".gamestats2.gs.nintendowifi.net.",
                 ".natneg1.gs.nintendowifi.net.", ".natneg2.gs.nintendowifi.net.", ".natneg3.gs.nintendowifi.net.")
MATCH_SERVER = re.compile(r"[a-z0-9-]+\.ms[0-9]+\.gs\.nintendowifi\.net\.")
GUIDE_DNS_NAME = "guide-status.dreamworld.invalid."
GUIDE_DNS_PATH = b"/player-guide/dns.json"


class GameDNS(asyncio.DatagramProtocol):
    def __init__(self, address: str, peers: frozenset[str]) -> None:
        self.address = address
        self.peers = peers

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, peer: tuple[str, int]) -> None:
        if (peer[0] not in self.peers and peer[0] != self.address) or len(data) > 512:
            return
        try:
            query = DNSRecord.parse(data)
        except (DNSError, ValueError, TypeError, BufferError):
            return
        if query.header.qr or query.header.q != 1:
            return
        name = str(query.q.qname).lower()
        result = query.reply(ra=0)
        if name == GUIDE_DNS_NAME and query.q.qtype == QTYPE.TXT and peer[0] == self.address:
            result.add_answer(RR(query.q.qname, QTYPE.TXT, ttl=0, rdata=TXT(f"dreamworld-dns-v1 {self.address}")))
        elif peer[0] not in self.peers:
            return
        elif name not in DNS_NAMES and not name.endswith(GAME_SUFFIXES) and not MATCH_SERVER.fullmatch(name):
            result.header.rcode = RCODE.NXDOMAIN
        elif query.q.qtype == QTYPE.A:
            result.add_answer(RR(query.q.qname, QTYPE.A, ttl=0, rdata=A(self.address)))
        self.transport.sendto(result.pack(), peer)


async def copy_stream(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    while data := await reader.read(65536):
        writer.write(data)
        await writer.drain()
    if writer.can_write_eof():
        writer.write_eof()


async def close_stream(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass


def peer_alias(peer: str) -> str:
    return str(IPv4Address(int(IPv4Address("127.64.0.0")) + (int(IPv4Address(peer)) & 0x3fffff)))


async def gateway_web_request(reader, writer, address):
    # The DS and the browser are on this gateway. Its DNS answer must stay here
    # even though all ordinary web pages are served by the remote hub.
    header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=30)
    request, *fields = header[:-4].split(b"\r\n")
    parts = request.split()
    if len(parts) == 3 and parts[0] in (b"GET", b"HEAD") and parts[1].split(b"?", 1)[0] == GUIDE_DNS_PATH:
        hosts = [line.partition(b":")[2].strip().lower() for line in fields if line.partition(b":")[0].lower() == b"host"]
        status = "ambiguous"
        if len(hosts) == 1 and re.fullmatch(rb"(127\.0\.0\.1|localhost)(:\d+)?", hosts[0]):
            # UDP is already listening. Check that a detached hotspot hasn't removed
            # the configured address since that socket was opened.
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as check:
                    check.bind((address, 0))
                status = "ready"
            except OSError:
                status = "offline"
        body = json.dumps({"status": status, "address": address if status == "ready" else None}).encode("ascii")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n"
                     b"Connection: close\r\nContent-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n")
        if parts[0] == b"GET":
            writer.write(body)
        await writer.drain()
        return None
    # A persistent tunnel could send a later DNS request straight to the hub.
    # Ask the upstream HTTP server to close after this response.
    fields = [line for line in fields if line.partition(b":")[0].lower() not in (b"connection", b"proxy-connection")]
    return b"\r\n".join([request, *fields, b"Connection: close", b"", b""])


def tcp_bridge(destination: str, port: int, peers: frozenset[str], *, identity=False, source=None, guide_dns=None):
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        upstream = None
        try:
            if not peer or peer[0] not in peers:
                return
            header = None
            if guide_dns is not None:
                header = await gateway_web_request(reader, writer, guide_dns)
                if header is None:
                    return
            outbound = peer_alias(peer[0]) if identity else source
            options = {"local_addr": (outbound, 0)} if outbound else {}
            remote, upstream = await asyncio.wait_for(asyncio.open_connection(destination, port, **options), timeout=6)
            if header:
                upstream.write(header)
                await upstream.drain()
            async with asyncio.TaskGroup() as group:
                group.create_task(copy_stream(reader, upstream))
                group.create_task(copy_stream(remote, writer))
        except asyncio.IncompleteReadError:
            pass
        except (OSError, TimeoutError, asyncio.LimitOverrunError, ExceptionGroup) as exc:
            LOG.warning("TCP %s to %s:%d closed: %s", peer, destination, port, exc)
        finally:
            if upstream is not None:
                await close_stream(upstream)
            await close_stream(writer)

    return handle


class UDPListener(asyncio.DatagramProtocol):
    def __init__(self, receive):
        self.receive = receive

    def datagram_received(self, data, peer):
        self.receive(data, peer)


async def udp_listener(stack, host, port, receive):
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: UDPListener(receive), local_addr=(host, port))
    stack.callback(transport.close)
    return transport


def decode_packet(data):
    if len(data) < PACKET.size:
        return None
    magic, source, destination = PACKET.unpack_from(data)
    if magic != MAGIC:
        return None
    return source, destination, data[PACKET.size:]


def encode_packet(source, destination, data=b""):
    return PACKET.pack(MAGIC, source, destination) + data


class BattleHub:
    """Map one trusted gateway's DS sockets onto stable ports shared by the gateways."""
    def __init__(self, peers, backend, relay_ip, state_file):
        self.peers = peers
        self.backend = backend
        self.relay_ip = relay_ip
        self.state_file = state_file
        self.gateways = {}
        self.ports = {}
        self.upstream = {}
        self.last_seen = {}
        self.pending = asyncio.Queue(maxsize=1024)
        self.ready = asyncio.Event()

    async def save_state(self):
        entries = {peer_alias(peer): {"udp_ports": {}} for peer in self.peers}
        for (owner, original), port in self.ports.items():
            entries[peer_alias(owner)]["udp_ports"][str(port)] = original
        state = {"version": 1, "relay_ip": self.relay_ip, "peers": entries}
        temporary = self.state_file.with_name(self.state_file.name + ".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(temporary, self.state_file)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                await asyncio.sleep(0.015 * (attempt + 1))

    def close(self):
        for transport in self.upstream.values():
            transport.close()
        self.state_file.unlink(missing_ok=True)

    def receive(self, data, addr):
        decoded = decode_packet(data)
        if addr[0] not in self.peers or decoded is None:
            return
        source, destination, payload = decoded
        if source == 0 and destination == 0 and not payload:
            if self.gateways.get(addr[0]) != addr:
                LOG.info("Gateway connected: %s", addr[0])
            self.gateways[addr[0]] = addr
            self.tunnel.sendto(encode_packet(0, 0), addr)
        elif source and (destination in DISCOVERY_PORTS or destination in PLAYER_PORTS):
            self.gateways[addr[0]] = addr
            if not self.pending.full():
                self.pending.put_nowait((addr[0], source, destination, payload))

    def forward(self, owner, source, destination, payload):
        socket_address = self.gateways.get(owner)
        if socket_address:
            self.tunnel.sendto(encode_packet(source, destination, payload), socket_address)

    async def expire(self):
        limit = time.monotonic() - 3600
        expired = [pair for pair, last in self.last_seen.items() if last < limit]
        for pair in expired:
            port = self.ports.pop(pair)
            self.upstream.pop(port).close()
            del self.last_seen[pair]
        if expired:
            await self.save_state()

    async def allocate(self, owner, original):
        pair = owner, original
        if pair in self.ports:
            self.last_seen[pair] = time.monotonic()
            return self.ports[pair]
        await self.expire()
        loop = asyncio.get_running_loop()
        def reply(data, addr):
            if addr[0] == self.backend and addr[1] in DISCOVERY_PORTS:
                self.last_seen[pair] = time.monotonic()
                self.forward(owner, addr[1], original, data)
        for port in PLAYER_PORTS:
            if port in self.upstream:
                continue
            try:
                transport, _ = await loop.create_datagram_endpoint(lambda: UDPListener(reply),
                    local_addr=(peer_alias(owner), port))
            except OSError:
                continue
            self.ports[pair] = port
            self.upstream[port] = transport
            self.last_seen[pair] = time.monotonic()
            await self.save_state()
            return port
        LOG.warning("No free battle UDP port for %s", owner)
        return None

    async def run(self, bind, stack):
        self.tunnel = await udp_listener(stack, bind, TUNNEL_PORT, self.receive)
        stack.callback(self.close)
        await self.save_state()
        self.ready.set()
        while True:
            owner, original, target, data = await self.pending.get()
            if target in PLAYER_PORTS and target not in self.upstream:
                continue
            source = await self.allocate(owner, original)
            if source is None:
                continue
            if target in DISCOVERY_PORTS:
                self.upstream[source].sendto(data, (self.backend, target))
            else:
                for pair, port in self.ports.items():
                    if port == target:
                        if pair[0] != owner:
                            self.last_seen[pair] = time.monotonic()
                            self.forward(pair[0], source, pair[1], data)
                        break


class BattleGateway:
    """Give the local DS the same peer addresses reported by the matchmaking server."""
    def __init__(self, ds, hub):
        self.ds = ds
        self.hub = (hub, TUNNEL_PORT)
        self.local = {}
        self.observed = set()
        self.connected = asyncio.Event()

    def receive_local(self, port, data, addr):
        if addr[0] != self.ds or len(data) > 65507 - PACKET.size:
            return
        self.observed.add(addr[1])
        self.tunnel.sendto(encode_packet(addr[1], port, data), self.hub)

    def receive_hub(self, data, addr):
        decoded = decode_packet(data)
        if addr != self.hub or decoded is None:
            return
        source, target, payload = decoded
        if source == 0 and target == 0 and not payload:
            if not self.connected.is_set():
                LOG.info("Battle hub confirmed the connection: %s", addr[0])
            self.connected.set()
        elif source in self.local and target in self.observed:
            self.local[source].sendto(payload, (self.ds, target))

    async def run(self, bind, relay_ip, tail_ip, stack):
        self.tunnel = await udp_listener(stack, tail_ip or "0.0.0.0", 0, self.receive_hub)
        for port in (*DISCOVERY_PORTS, *PLAYER_PORTS):
            ip = bind if port in DISCOVERY_PORTS else relay_ip
            self.local[port] = await udp_listener(stack, ip, port,
                lambda data, addr, port=port: self.receive_local(port, data, addr))
        LOG.info("DS battle relay: %s, remote peers at %s", bind, relay_ip)
        while True:
            self.tunnel.sendto(encode_packet(0, 0), self.hub)
            await asyncio.sleep(15)


async def serve(bind: str, peers: frozenset[str], game: str, web: str, gateway: bool,
                *, tail_ip=None, relay_ip=None, state_file=None, no_web=False) -> None:
    async with AsyncExitStack() as stack:
        for port in GAME_PORTS:
            server = await asyncio.start_server(tcp_bridge(game, port, peers, identity=not gateway, source=tail_ip), bind, port)
            await stack.enter_async_context(server)

        if gateway:
            loop = asyncio.get_running_loop()
            dns, _ = await loop.create_datagram_endpoint(lambda: GameDNS(bind, peers), local_addr=(bind, 53))
            stack.callback(dns.close)
            LOG.info("DS primary DNS: %s", bind)
            if not no_web:
                LOG.info("Browser starts at http://127.0.0.1:8088/pdw/")
        else:
            LOG.info("Private VPN relay listening at %s", bind)

        web_bind = "127.0.0.1" if gateway else bind
        web_peers = frozenset({"127.0.0.1"}) if gateway else peers
        for port in (() if no_web else WEB_PORTS):
            handle_web = tcp_bridge(web, port, web_peers, identity=not gateway,
                                    source=tail_ip if gateway else None, guide_dns=bind if gateway else None)
            server = await asyncio.start_server(handle_web, web_bind, port)
            await stack.enter_async_context(server)

        if relay_ip and gateway:
            await BattleGateway(next(iter(peers)), game).run(bind, relay_ip, tail_ip, stack)
        elif relay_ip:
            await BattleHub(peers, game, relay_ip, state_file).run(bind, stack)
        else:
            await asyncio.Event().wait()


def is_lan(address: IPv4Address) -> bool:
    return any(address in network for network in LAN)


async def self_test():
    """Exercise this installation with two local test clients. No live game or VPN is needed."""
    subnet = f"127.251.{secrets.randbelow(254) + 1}"
    hub_ip, backend = f"{subnet}.1", f"{subnet}.2"
    lan = [f"{subnet}.11", f"{subnet}.12"]
    tail = [f"{subnet}.21", f"{subnet}.22"]
    consoles = [f"{subnet}.31", f"{subnet}.32"]
    queues = [asyncio.Queue(), asyncio.Queue()]
    received = asyncio.Queue()
    with tempfile.TemporaryDirectory(prefix="DreamWorld-VPN-check-") as folder:
        async with AsyncExitStack() as stack, asyncio.TaskGroup() as group:
            hub = BattleHub(frozenset(tail), backend, DEFAULT_RELAY_IP, Path(folder) / "state.json")
            jobs = [group.create_task(hub.run(hub_ip, stack))]
            try:
                await hub.ready.wait()
                service = await udp_listener(stack, backend, DISCOVERY_PORTS[0],
                    lambda data, addr: received.put_nowait((data, addr)))
                sockets, ports = [], []
                for index in range(2):
                    gateway = BattleGateway(consoles[index], hub_ip)
                    jobs.append(group.create_task(gateway.run(lan[index], lan[index], tail[index], stack)))
                    await gateway.connected.wait()
                    def reply(data, addr, queue=queues[index]):
                        queue.put_nowait((data, addr))
                    client = await udp_listener(stack, consoles[index], 49100, reply)
                    sockets.append(client)
                    client.sendto(b"find", (lan[index], DISCOVERY_PORTS[0]))
                    data, endpoint = await received.get()
                    if data != b"find" or endpoint[0] != peer_alias(tail[index]):
                        raise RuntimeError("The backend did not see the expected player identity")
                    service.sendto(b"found", endpoint)
                    if await queues[index].get() != (b"found", (lan[index], DISCOVERY_PORTS[0])):
                        raise RuntimeError("Discovery reply did not return to its original client")
                    ports.append(endpoint[1])
                if ports[0] == ports[1]:
                    raise RuntimeError("Two consoles received the same relay port")
                for sender, recipient in ((0, 1), (1, 0)):
                    payload = bytes([sender]) + bytes(range(256)) * 3
                    sockets[sender].sendto(payload, (lan[sender], ports[recipient]))
                    if await queues[recipient].get() != (payload, (lan[recipient], ports[sender])):
                        raise RuntimeError("Player data did not reach the other console intact")
            finally:
                for job in jobs:
                    job.cancel()
    print("PASS: Two simulated consoles, distinct game identities, discovery and bidirectional player UDP.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    commands.add_parser("self-test", help="check discovery and player traffic locally with two simulated consoles")
    host = commands.add_parser("host", help="Run on the computer hosting Dream World")
    host.add_argument("--bind", required=True, type=IPv4Address, help="this computer's Tailscale IP")
    host.add_argument("--peer", required=True, type=IPv4Address, action="append", help="friend's Tailscale IP")
    host.add_argument("--game", type=IPv4Address, default=IPv4Address("127.0.0.1"),
                      help="local address where Game Sync is listening")
    gateway = commands.add_parser("gateway", help="Run on the computer on the same LAN as the remote DS")
    gateway.add_argument("--bind", required=True, type=IPv4Address, help="this computer's DS-facing LAN IP")
    gateway.add_argument("--peer", required=True, type=IPv4Address, action="append", help="DS's LAN IP")
    gateway.add_argument("--host", required=True, type=IPv4Address, help="server computer's Tailscale IP")
    host.add_argument("--relay-ip", type=IPv4Address, default=IPv4Address(DEFAULT_RELAY_IP),
                      help="same private IPv4 address reachable by each DS on its local gateway")
    default_state = Path(sys.executable if getattr(sys, "frozen", False) else __file__).resolve().with_name("DreamWorld-VPN-state.json")
    host.add_argument("--state-file", type=Path, default=Path(os.environ.get("DW_RELAY_STATE", default_state)))
    gateway.add_argument("--relay-ip", type=IPv4Address, help="enable battles with this locally assigned relay IP")
    gateway.add_argument("--tailscale-ip", type=IPv4Address, help="this gateway's Tailscale IPv4 address")
    gateway.add_argument("--no-web", action="store_true", help="skip web listeners when running on the host PC")
    args = parser.parse_args()
    if args.mode == "self-test":
        try:
            asyncio.run(asyncio.wait_for(self_test(), timeout=15))
        except (OSError, TimeoutError, ExceptionGroup, RuntimeError) as exc:
            parser.exit(1, f"Relay self-test failed: {exc}\n")
        return
    if args.relay_ip and not is_lan(args.relay_ip):
        parser.error("--relay-ip must be a private LAN address")
    if args.mode == "host":
        if args.bind not in TAILNET or any(peer not in TAILNET for peer in args.peer):
            parser.error("host and peer addresses must be Tailscale IPv4 addresses")
        if not args.game.is_loopback and not is_lan(args.game):
            parser.error("Game Sync must run on this computer's loopback or private LAN address")
        game, web = str(args.game), "127.0.0.1"
    else:
        if args.host not in TAILNET or not is_lan(args.bind) or not all(map(is_lan, args.peer)):
            parser.error("use a Tailscale host address and private LAN addresses for the gateway and DS")
        if args.relay_ip and len(args.peer) != 1:
            parser.error("battle mode needs exactly one DS per gateway")
        if args.tailscale_ip and args.tailscale_ip not in TAILNET:
            parser.error("--tailscale-ip must belong to the private Tailscale network")
        game = web = str(args.host)
    if args.mode == "gateway" and (args.bind in args.peer or args.relay_ip in args.peer):
        parser.error("the DS needs an address different from this gateway's local addresses")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        asyncio.run(serve(str(args.bind), frozenset(map(str, args.peer)), game, web, args.mode == "gateway",
                          tail_ip=str(args.tailscale_ip) if getattr(args, "tailscale_ip", None) else None,
                          relay_ip=str(args.relay_ip) if args.relay_ip else None,
                          state_file=getattr(args, "state_file", None), no_web=getattr(args, "no_web", False)))
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        parser.exit(1, f"Could not start the listeners: {exc}\n")


if __name__ == "__main__":
    main()
