"""Select one attached private LAN for the website; keep the PC's loopback URL."""
import ipaddress
import logging
import os
import socket
import subprocess
import time
from pathlib import Path

from flask import Response, request

PRIVATE_LANS = tuple(ipaddress.IPv4Network(cidr) for cidr in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
log = logging.getLogger(__name__)

# Report numeric data only. Virtual adapters (including a VPN) are excluded.
_ADAPTERS = """
$ErrorActionPreference = 'Stop'
foreach ($nic in @(Get-NetAdapter -Physical | Where-Object Status -eq 'Up')) {
    $wifi = [int]$nic.NdisPhysicalMedium -in 1,9
    foreach ($ip in @(Get-NetIPAddress -InterfaceIndex $nic.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue)) {
        if ($ip.AddressState -eq 'Preferred' -and !$ip.SkipAsSource) {
            Write-Output "$($ip.IPAddress)/$($ip.PrefixLength) $([int]$wifi)"
        }
    }
}
"""


def _private_interface(value: str) -> ipaddress.IPv4Interface:
    interface = ipaddress.IPv4Interface(value)
    if not any(interface.network.subnet_of(network) for network in PRIVATE_LANS):
        raise ValueError("The web listener needs a private LAN address and subnet.")
    return interface


def choose_web_lan(requested: str | None, ds_address: str | None, watch_wifi: bool) -> str | None:
    """Resolve a launcher option against the actual physical adapter and subnet."""
    if not (requested or ds_address or watch_wifi):
        return None
    explicit = _private_interface(requested) if requested else None
    if os.name != "nt":
        if requested and "/" not in requested:
            raise ValueError("Include the adapter's prefix length with --web-lan (for example 192.168.1.5/24).")
        return str(explicit) if explicit else None
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _ADAPTERS],
            capture_output=True, check=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if explicit:
            raise ValueError("Could not verify the selected LAN adapter.") from exc
        log.warning("Could not identify the physical LAN. The website is available on this PC.")
        return None
    choices = []
    for line in result.stdout.decode("ascii", errors="replace").splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            candidate = _private_interface(parts[0])
        except ValueError:
            continue
        if explicit:
            if candidate.ip == explicit.ip and ("/" not in (requested or "") or candidate == explicit):
                return str(candidate)
        elif ds_address == str(candidate.ip) or (watch_wifi and parts[1] == "1"):
            choices.append(str(candidate))
    if explicit:
        raise ValueError("--web-lan must match an address on a connected physical LAN adapter.")
    if len(choices) == 1:
        return choices[0]
    log.warning("No single LAN selected. Use --web-lan to choose a physical adapter. The PC website stays available.")
    return None


def lan_web_address() -> str | None:
    value = os.environ.get("DW_WEB_LAN")
    return str(_private_interface(value).ip) if value else None


def is_web_host(host: str | None) -> bool:
    return host in LOCAL_HOSTS or (host is not None and host == lan_web_address())


def same_web_lan(peer: str | None, host: str | None) -> bool:
    value = os.environ.get("DW_WEB_LAN")
    if not peer or not value:
        return False
    interface = _private_interface(value)
    try:
        return host == str(interface.ip) and ipaddress.IPv4Address(peer) in interface.network
    except ValueError:
        return False


def restrict_web_clients() -> Response | None:
    """Preserve loopback and relay traffic. Accept LAN browsers on the configured subnet only."""
    peer = request.remote_addr or ""
    try:
        if ipaddress.ip_address(peer).is_loopback:
            return None
    except ValueError:
        pass
    if same_web_lan(peer, request.host.partition(":")[0]):
        return None
    return Response("Local network access only.", status=403, mimetype="text/plain")


def web_listeners(port: int) -> list[str]:
    """Drop a stale or occupied LAN binding without taking the loopback site down."""
    addresses = [f"127.0.0.1:{port}"]
    address = lan_web_address()
    if address:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as check:
                check.bind((address, port))
        except OSError:
            log.warning("LAN address %s:%s is unavailable. Restart the launcher after checking your network.", address, port)
            os.environ.pop("DW_WEB_LAN", None)
        else:
            addresses.append(f"{address}:{port}")
    return addresses


def publish_web_lan(path: Path, lan: str | None) -> None:
    """Share one physical-adapter detection among all language servers."""
    temporary = path.with_suffix(".new")
    temporary.write_text(lan or "", encoding="ascii")
    temporary.replace(path)


def serve_changing_lan(app, port: int, state: Path, **options) -> None:
    """Keep loopback and existing tasks running while switching the private LAN socket."""
    from waitress import create_server, wasyncore

    channels: dict = {}
    loopback = create_server(app, map=channels, host="127.0.0.1", port=port, **options)
    lan_server = None
    os.environ.pop("DW_WEB_LAN", None)
    next_check = 0.0
    try:
        while True:
            if time.monotonic() >= next_check:
                next_check = time.monotonic() + 1
                try:
                    value = state.read_text(encoding="ascii").strip()
                    target = _private_interface(value) if value else None
                except (OSError, ValueError):
                    target = None
                new_ip = str(target.ip) if target else None
                if lan_server is not None and new_ip != lan_server.effective_host:
                    os.environ.pop("DW_WEB_LAN", None)
                    for channel in list(lan_server.active_channels.values()):
                        channel.handle_close()
                    lan_server.close()
                    lan_server = None
                if target and lan_server is None:
                    # Bind first: failure must not leak a Waitress trigger or a dispatcher.
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    try:
                        sock.bind((str(target.ip), port))
                    except OSError:
                        sock.close()
                        next_check = time.monotonic() + 3
                    else:
                        lan_server = create_server(app, map=channels, sockets=[sock],
                                                   _dispatcher=loopback.task_dispatcher, **options)
                if lan_server is not None and target:
                    os.environ["DW_WEB_LAN"] = str(target)
            wasyncore.loop(timeout=0.5, map=channels, count=1)
    except KeyboardInterrupt:
        pass
    finally:
        os.environ.pop("DW_WEB_LAN", None)
        loopback.task_dispatcher.shutdown()
        wasyncore.close_all(channels)
