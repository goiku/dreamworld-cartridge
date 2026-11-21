"""Report the address to enter in a DS connection, even before it connects."""
import ipaddress
import os

from game_sync_server.entralinked.app import get_local_address
from game_sync_server.entralinked.network.dns.server import MELONDS_HOST
from utils.web_network import LOCAL_HOSTS, PRIVATE_LANS, choose_web_lan, lan_web_address, same_web_lan


def _private_ip(value: str) -> bool:
    try:
        address = ipaddress.IPv4Address(value)
    except ValueError:
        return False
    return any(address in subnet for subnet in PRIVATE_LANS)


def emulator_dns(peer: str | None, host: str | None) -> dict:
    if peer not in ("127.0.0.1", "::1") or host not in LOCAL_HOSTS:
        return {"status": "ambiguous", "address": None}
    bind = os.environ.get("DW_GAME_BIND", "127.0.0.1")
    return {"status": "ready", "address": bind if _private_ip(bind) else MELONDS_HOST}


def get_player_dns(peer: str | None, web_host: str | None = "localhost") -> dict:
    if web_host and same_web_lan(peer, web_host):
        return {"status": "ready", "address": web_host}
    if peer not in ("127.0.0.1", "::1") or web_host not in LOCAL_HOSTS:
        return {"status": "ambiguous", "address": None}
    bind = os.environ.get("DW_GAME_BIND", "")
    if _private_ip(bind):
        return {"status": "ready", "address": bind}
    address = lan_web_address()
    if not address:
        route = get_local_address()
        if _private_ip(route):
            if os.name == "nt":
                interface = choose_web_lan(None, route, False)
                address = interface.split("/")[0] if interface else None
            else:
                address = route
    return {"status": "ready" if address else "offline", "address": address}
