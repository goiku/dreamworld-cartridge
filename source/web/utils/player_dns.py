"""Find the DS-facing DNS listener on the computer showing the local guide."""
import ipaddress
import os
import socket
from contextlib import suppress

from dnslib import DNSError, DNSRecord

from game_sync_server.entralinked.network.dns.server import MELONDS_HOST
from utils.web_network import LOCAL_HOSTS, same_web_lan

PRIVATE_LAN = tuple(ipaddress.IPv4Network(prefix) for prefix in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
STATUS_NAME = "guide-status.dreamworld.invalid."


def _candidates() -> list[str]:
    addresses = {os.environ.get("DW_GAME_BIND", "")}
    with suppress(OSError):
        addresses.update(str(entry[4][0]) for entry in socket.getaddrinfo(
            socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM))
    return sorted(ip for ip in addresses if ip and _is_lan(ip))


def _is_lan(value: str) -> bool:
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return any(address in network for network in PRIVATE_LAN)


def _answers(ip: str, name: str, kind: str):
    query = DNSRecord.question(name, kind)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            # A candidate must actually belong to this computer. Never probe other LAN devices.
            probe.bind((ip, 0))
            probe.settimeout(0.18)
            probe.connect((ip, 53))
            probe.send(query.pack())
            reply = DNSRecord.parse(probe.recv(512))
        if reply.header.id != query.header.id or not reply.header.qr or reply.header.rcode or reply.q != query.q:
            return []
        return [rr.rdata for rr in reply.rr if rr.rname == query.q.qname and rr.rtype == query.q.qtype]
    except (OSError, DNSError):
        return []


def _is_serving(ip: str) -> bool:
    marker = [f"dreamworld-dns-v1 {ip}".encode("ascii")]
    return any(answer.data == marker for answer in _answers(ip, STATUS_NAME, "TXT"))


def emulator_dns(peer: str | None, host: str | None) -> dict:
    if peer not in ("127.0.0.1", "::1") or host not in LOCAL_HOSTS:
        return {"status": "ambiguous", "address": None}
    if _is_serving("127.0.0.1"):
        answers = _answers("127.0.0.1", "nas.nintendowifi.net", "A")
        if any(str(answer) == MELONDS_HOST for answer in answers):
            return {"status": "ready", "address": MELONDS_HOST}
    return get_player_dns(peer, host)


def get_player_dns(peer: str | None, web_host: str | None = "localhost") -> dict[str, str | None]:
    if web_host and same_web_lan(peer, web_host):
        if _is_serving(web_host):
            return {"status": "ready", "address": web_host}
        return {"status": "offline", "address": None}
    # A hub relays its guests' web traffic from distinct 127.64/10 aliases. Only a
    # direct local browser can use this computer's LAN address; gateways answer locally.
    if peer not in ("127.0.0.1", "::1") or web_host not in LOCAL_HOSTS:
        return {"status": "ambiguous", "address": None}
    active = [ip for ip in _candidates() if _is_serving(ip)]
    if len(active) == 1:
        return {"status": "ready", "address": active[0]}
    return {"status": "ambiguous" if active else "offline", "address": None}
