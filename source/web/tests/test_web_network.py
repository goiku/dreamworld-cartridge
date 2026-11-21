"""Exercise a running website through address changes using only loopback sockets."""
import ipaddress
import socket
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

import pytest
from flask import Flask
from waitress import wasyncore

from utils import web_network as network


def test_switch_lan_keeps_loopback_server(tmp_path, monkeypatch):
    app = Flask(__name__)
    app.add_url_rule("/", view_func=lambda: network.lan_web_address() or "offline")
    state = tmp_path / "lan"
    first, second = "127.0.0.2", "127.0.0.3"
    network.publish_web_lan(state, first + "/8")
    monkeypatch.setattr(network, "_private_interface", ipaddress.IPv4Interface)
    monkeypatch.delenv("DW_WEB_LAN", raising=False)
    io_loop, stop = wasyncore.loop, threading.Event()

    def run_loop(**kwargs):
        if stop.is_set():
            raise KeyboardInterrupt
        io_loop(**kwargs)

    monkeypatch.setattr(wasyncore, "loop", run_loop)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = threading.Thread(target=network.serve_changing_lan, args=(app, port, state), kwargs={"threads": 2})
    http = build_opener(ProxyHandler({}))

    def get(address):
        with http.open(f"http://{address}:{port}/", timeout=0.5) as result:
            return result.read().decode()

    def wait_for(address, text):
        start = time.monotonic()
        while time.monotonic() - start < 10:
            try:
                if get(address) == text:
                    return
            except OSError:
                pass
            time.sleep(0.05)
        pytest.fail(f"Website at {address} did not advertise {text}.")

    server.start()
    try:
        wait_for(first, first)
        assert get("127.0.0.1") == first
        network.publish_web_lan(state, second + "/8")
        wait_for(second, second)
        assert get("127.0.0.1") == second
        with pytest.raises((URLError, OSError)):
            get(first)
        network.publish_web_lan(state, None)
        wait_for("127.0.0.1", "offline")
        network.publish_web_lan(state, first + "/8")
        wait_for(first, first)
    finally:
        stop.set()
        server.join(timeout=5)
    assert not server.is_alive()


def test_melonds_dns_matches_configured_resolver_address(monkeypatch):
    from types import SimpleNamespace
    from dnslib import DNSRecord
    from game_sync_server.entralinked.network.dns.server import FixedResolver
    from utils import player_dns

    def answers(address, name, kind):
        request = DNSRecord.question(name, kind)
        resolver = FixedResolver(address)
        reply = resolver.resolve(request, SimpleNamespace(client_address=(address, 12345)))
        return [rr.rdata for rr in reply.rr]

    monkeypatch.setenv("DW_GAME_BIND", "127.0.0.1")
    assert str(answers("127.0.0.1", "nas.nintendowifi.net", "A")[0]) == "10.64.0.1"
    assert player_dns.emulator_dns("127.0.0.1", "localhost") == {"status": "ready", "address": "10.64.0.1"}
    assert player_dns.emulator_dns("127.64.0.2", "localhost")["address"] is None
    assert player_dns.emulator_dns("192.168.1.14", "192.168.1.5")["address"] is None
    lan = "192.168.1.5"
    assert str(answers(lan, "nas.nintendowifi.net", "A")[0]) == lan
    monkeypatch.setenv("DW_GAME_BIND", lan)
    assert player_dns.emulator_dns("::1", "localhost") == {"status": "ready", "address": lan}
