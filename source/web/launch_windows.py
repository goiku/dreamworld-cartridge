"""Run the two Windows services together from one console."""

import argparse
import ipaddress
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from config import WEB_PORTS, EmailNotConfiguredError, get_email_config, get_secret_key
from game_sync_server.entralinked.app import get_local_address
from utils.web_network import choose_web_lan, publish_web_lan


def _local_ipv4_addresses() -> frozenset[str]:
    try:
        return frozenset(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        return frozenset()


def main() -> int:
    parser = argparse.ArgumentParser()
    network = parser.add_mutually_exclusive_group()
    network.add_argument("--lan", action="store_true")
    network.add_argument("--watch-wifi", metavar="PROFILE", help="Enable DS access when the PC joins this Wi-Fi")
    parser.add_argument("--web-lan", metavar="ADDRESS", help="Serve the website on this physical private LAN address")
    args = parser.parse_args()
    if args.lan and os.environ.get("DW_WIFI_PROFILE"):
        args.watch_wifi = os.environ["DW_WIFI_PROFILE"]
        args.lan = False
    address = get_local_address() if args.lan else "127.0.0.1"
    private_networks = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    if args.lan and not any(
        ipaddress.IPv4Address(address) in ipaddress.IPv4Network(network)
        for network in private_networks
    ):
        parser.error("Game Sync LAN mode requires a private IPv4 address.")

    # Initialize shared first-run files once before the language servers start.
    get_secret_key()
    try:
        get_email_config(prompt=False)
    except EmailNotConfiguredError:
        pass  # The server operator can activate new accounts from the local console.

    env = dict(os.environ, DW_GAME_BIND=address, PYTHONUNBUFFERED="1")
    explicit_web = args.web_lan or env.get("DW_WEB_LAN")
    try:
        lan = choose_web_lan(explicit_web, address if args.lan else None, bool(args.watch_wifi))
    except ValueError as exc:
        parser.error(str(exc))
    if lan:
        env["DW_WEB_LAN"] = lan
    else:
        env.pop("DW_WEB_LAN", None)
    directory = Path(__file__).resolve().parent
    processes: dict[str | None, subprocess.Popen] = {}
    adaptive = os.name == "nt" and not explicit_web and (args.lan or args.watch_wifi)
    state_dir = tempfile.TemporaryDirectory(prefix="dreamworld-web-") if adaptive else None
    state_file = Path(state_dir.name) / "lan" if state_dir else None
    env.pop("DW_WEB_LAN_STATE", None)
    try:
        if state_file:
            publish_web_lan(state_file, lan)
            env["DW_WEB_LAN_STATE"] = str(state_file)
        if args.watch_wifi:
            print(f"DS primary DNS will be shown when the computer connects to {args.watch_wifi}.", flush=True)
        else:
            print(f"Game Sync address: {address}", flush=True)
        game_command = ["game_sync_server/server.py", "--http-port", "80", "--host", address]
        if args.watch_wifi:
            game_command.extend(("--watch-wifi", args.watch_wifi))
        commands: list[tuple[str | None, list[str]]] = [(None, game_command)]
        for language, port in WEB_PORTS.items():
            base = "ja" if language == "zh" else language
            page = directory / "dreamworld_assets" / f"{base}.pokemon-gl.com" / "pdw" / "index.html"
            if page.is_file():
                print(f"Dream World ({language}): http://127.0.0.1:{port}/", flush=True)
                if lan:
                    print(f"Same LAN ({language}): http://{lan.split('/')[0]}:{port}/", flush=True)
                commands.append((language, ["main.py", "--lang", language, "--port", str(port)]))
        for service, command in commands:
            processes[service] = subprocess.Popen(
                [sys.executable, *command], cwd=directory, env=env,
            )
        retry_after: dict[str | None, float] = {}
        next_web_check = time.monotonic() + 3
        next_adapter_scan = time.monotonic() + 45
        previous_ips = _local_ipv4_addresses() if state_file else frozenset()
        while processes[None].poll() is None:
            now = time.monotonic()
            if state_file and now >= next_web_check:
                local_ips = _local_ipv4_addresses()
                if local_ips != previous_ips or now >= next_adapter_scan:
                    current = choose_web_lan(None, get_local_address() if args.lan else None, bool(args.watch_wifi))
                    if current != lan:
                        try:
                            publish_web_lan(state_file, current)
                        except OSError as exc:
                            print(f"Unable to update the website LAN address yet: {exc}", flush=True)
                        else:
                            lan = current
                            print("Website LAN updated. Open Phone web address on this PC for the current address.", flush=True)
                    previous_ips = local_ips
                    next_adapter_scan = time.monotonic() + 45
                next_web_check = time.monotonic() + 3
            for service, command in commands[1:]:
                if processes[service].poll() is not None and now >= retry_after.get(service, 0):
                    retry_after[service] = now + 30
                    print(f"Restarting Dream World ({service}).", flush=True)
                    processes[service] = subprocess.Popen([sys.executable, *command], cwd=directory, env=env)
            time.sleep(0.5)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
        for process in processes.values():
            process.wait()
        if state_dir:
            state_dir.cleanup()


if __name__ == "__main__":
    sys.exit(main())
