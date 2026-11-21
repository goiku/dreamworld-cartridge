"""Two private hosts, encrypted pairing, a full host shutdown, and background catch-up."""

import json
import multiprocessing
import os
import re
import socket
import threading
import time
import traceback
from contextlib import contextmanager

import pytest


def web_session(card, number):
    from api.server import create_app
    from utils.account_manager import accounts

    username = f"fixture{number}"
    if not accounts.get_account_by_username(username):
        accounts.create_account(username, "unused", f"{username}@example.invalid", 1, 1, "friends", "friends", username)
        accounts.activate_account(username)
        accounts.link_gscd(username, card)
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    with client.session_transaction() as state:
        state.update(username=username, gscd=card)
    return client


def open_scene(client, island, event_id=None):
    """Follow the roster form, original map API, and the native room movie's own requests."""
    index = client.get("/islands/")
    page = index.get_data(as_text=True)
    assert index.status_code == 200 and f'data-island="{island}"' in page
    assert "?mode=live" not in page and "?mode=offline" not in page
    event_id = event_id or re.search(r'name="event_id" value="([0-9a-f]+)"', page)[1]
    csrf = re.search(r'name="csrf" value="([^"]+)"', page)[1]
    redirect = client.post(f"/islands/{island}/enter", data={"csrf": csrf, "event_id": event_id})
    assert redirect.status_code == 303 and redirect.location == f"/pdw/?island={island}"
    visit_page = client.get(redirect.location)
    assert visit_page.status_code == 200
    html = visit_page.get_data(as_text=True)
    assert "?mode=live" not in html and "?mode=offline" not in html
    info = json.loads(re.search(r'id="dw-friend-data">([^<]*)</script>', html)[1])
    assert 'id="dw-friend-tools"' in html and "<time" in html
    mid = info["member_savedata_id"]
    assert info.pop("visitor_pokemon") is None  # This visitor's cartridge is awake.
    assert info["island_id"] == island and client.get(f"/islands/native/{mid}").json == info
    map_result = client.get("/api/", query_string={"p": "pdw.home.my_island_area"})
    assert map_result.status_code == 200
    (pal,) = (row for row in map_result.json["friend_list"] if row["member_savedata_id"] == mid)
    assert pal["pgl_name"] == info["pgl_name"] and pal["island_id"] == info["house"]
    query = {"p": "pdw.home.friend_island", "friend_member_savedata_id": str(mid)}
    # Clicking a Dream Pal on the original map and entering from the web roster
    # both load the original room layout and refer to the same current visit.
    ordinary_home = client.get("/pdw/")
    assert ordinary_home.status_code == 200
    assert b"?mode=live" not in ordinary_home.data and b"?mode=offline" not in ordinary_home.data
    map_scene = client.get("/api/", query_string=query)
    movie_scene = client.get(f"/islands/{island}/game-api/", query_string=query)
    assert map_scene.status_code == movie_scene.status_code == 200
    assert map_scene.json == movie_scene.json and movie_scene.json["member_savedata_id"] == mid
    return {"event": event_id, "meta": info, "layout": movie_scene.json["arranged_interior_list"]}


def serve_fixture(pipe, directory, address, port, number):
    os.environ["DW_SAVE_DIR"] = str(directory)
    from game_sync_server.entralinked.model.player.player import Player, new_player_data
    from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
    from scripts.island_friends import main
    from utils import island_peers as peers
    from utils import offline_islands as islands

    assert peers.SAVE_DIR.resolve() == directory.resolve() == islands.db._db_path.parent.resolve()
    peers.PORT = port
    peers.INTERVAL = 1
    peers.interfaces = lambda: [address + "/8"]
    card = gsid_to_gscd(number)
    if not islands.db.read(card, "player_data"):
        islands.db.write_gscd(card)
        data = new_player_data(1, [1, 2])
        player = Player(card, rom_id=20, langcode=1)
        data["member"].update(player.member_fields(), pgl_name=f"Owner {number}", point=number)
        islands.db.write_full_state(card, data, player.game_sync_data(), None)
    doc = islands.export_island(card)
    client = None
    stop = threading.Event()
    worker = threading.Thread(target=main, args=(stop,), daemon=True)
    worker.start()
    eventually(peers.available)
    pipe.send((True, doc["island_id"]))
    try:
        while True:
            cmd, args = pipe.recv()
            if cmd == "stop":
                break
            if cmd == "invite":
                result = peers.invite(card)["codes"][0]["code"]
            elif cmd == "join":
                result = peers.join(card, *args)
            elif cmd == "remove":
                result = peers.forget(card, *args)
            elif cmd == "visit":
                result = islands.record_footprint(card, *args)
            elif cmd == "cached":
                result = islands.get_friend(card, *args)
            elif cmd == "inbox":
                result = islands.received_footprints(card)
            elif cmd == "outbox":
                result = islands.pending_footprints(card, *args)
            elif cmd == "change":
                islands.db.update(card, "player_data", lambda d, points=args[0]: d["member"].update(point=points))
                result = islands.export_island(card)
            elif cmd == "decorate":
                def place(save, x=args[0]):
                    save["member"]["my_interior_list"] = [{"interior_id": 1036, "my_interior_id": 3, "x": x, "y": 9}]

                islands.db.update(card, "player_data", place)
                result = islands.export_island(card)
            elif cmd == "scene":
                client = client or web_session(card, number)
                result = open_scene(client, *args)
            elif cmd == "delivery":
                client = client or web_session(card, number)
                result = client.get("/islands/updates").json["delivery"][args[0]]
            elif cmd == "refresh":
                result = peers.sync(peers.lookup(card, *args))
            else:
                raise AssertionError(cmd)
            pipe.send((True, result))
    except Exception:
        pipe.send((False, traceback.format_exc()))
    finally:
        stop.set()
        worker.join(12)
        pipe.close()


@contextmanager
def host(directory, address, port, number):
    ctx = multiprocessing.get_context("spawn")
    local, child = ctx.Pipe()
    process = ctx.Process(target=serve_fixture, args=(child, directory, address, port, number))
    process.start()
    child.close()

    def read():
        assert local.poll(20), "test server timed out"
        ok, value = local.recv()
        assert ok, value
        return value

    def command(cmd, *args):
        local.send((cmd, args))
        return read()

    try:
        yield read(), command
    finally:
        if process.is_alive():
            local.send(("stop", ()))
        process.join(15)
        if process.is_alive():
            process.terminate()
            process.join()
        local.close()
        assert process.exitcode == 0


def eventually(test):
    until = time.monotonic() + 18
    while time.monotonic() < until:
        if test():
            return
        time.sleep(0.15)
    pytest.fail("background synchronization did not catch up")


def test_offline_and_automatic_reconnect(tmp_path):
    from config import LANG
    from utils.data import load_json_data

    labels = load_json_data("offline_islands_ui")[LANG]
    host_a, host_b = "127.0.0.12", "127.0.0.13"
    with socket.socket() as sock:
        sock.bind((host_a, 0))
        port = sock.getsockname()[1]
    a, b = tmp_path / "A", tmp_path / "B"
    with host(a, host_a, port, 7) as (island_a, A):
        with host(b, host_b, port, 8) as (island_b, B):
            assert A("join", B("invite"))["island_id"] == island_b
            assert A("delivery", island_b)["last_sync"] and B("delivery", island_a)["last_sync"]
            assert B("cached", island_a)["content"]["profile"]["pgl_name"] == "Owner 7"
            B("change", 42)
            eventually(lambda: A("cached", island_b)["content"]["profile"]["point"] == 42)
        # There is no process at B now and no relay in this fixture.
        assert A("cached", island_b)["content"]["profile"]["point"] == 42
        event = "5d" * 16
        A("visit", island_b, event)
        A("visit", island_b, event)
        assert len(A("outbox", island_b)) == 1
        waiting = A("delivery", island_b)
        assert waiting["summary"] == labels["pending_counts"].format(feet=1, water=0, trade=0)
        with host(b, host_b, port, 8) as (restored, B):
            assert restored == island_b
            eventually(lambda: len(B("inbox")) == 1 and not A("outbox", island_b))
            A("refresh", island_b)
            B("refresh", island_a)
            synced = A("delivery", island_b)
            assert synced["last_sync"] >= waiting["last_sync"] and synced["summary"] == labels["nothing_pending"]
            assert [entry["event_id"] for entry in B("inbox")] == [event]
            assert A("cached", island_b)["content"]["profile"]["point"] == 42


def test_native_map_and_room_when_peer_shuts_down_and_returns(tmp_path):
    addr_a, addr_b = "127.0.0.14", "127.0.0.15"
    with socket.socket() as sock:
        sock.bind((addr_a, 0))
        port = sock.getsockname()[1]
    dir_a, dir_b = tmp_path / "A", tmp_path / "B"
    with host(dir_a, addr_a, port, 17) as (island_a, A):
        with host(dir_b, addr_b, port, 18) as (island_b, B):
            initial = B("decorate", 12)
            A("join", B("invite"))
            online = A("scene", island_b)
            assert online["meta"]["updated_at"] == initial["updated_at"]
            assert [(obj["interior_id"], obj["x"], obj["y"]) for obj in online["layout"]] == [(1036, 12, 9)]
            eventually(lambda: [e["event_id"] for e in B("inbox")] == [online["event"]] and not A("outbox", island_b))
        # The owner's complete Python process and socket are gone.
        offline = A("scene", island_b)
        assert offline["layout"] == online["layout"] and offline["meta"] == online["meta"]
        assert offline["event"] != online["event"]
        assert A("scene", island_b, offline["event"]) == offline
        assert [ev["event_id"] for ev in A("outbox", island_b)] == [offline["event"]]
        with host(dir_b, addr_b, port, 18) as (restored, B):
            assert restored == island_b
            changed = B("decorate", 26)
            assert changed["version"] > initial["version"] and changed["updated_at"] > initial["updated_at"]
            eventually(lambda: A("cached", island_b)["version"] == changed["version"] and not A("outbox", island_b))
            after = A("scene", island_b, offline["event"])
            assert after["meta"]["updated_at"] == changed["updated_at"]
            assert after["meta"]["member_savedata_id"] == online["meta"]["member_savedata_id"]
            assert [(obj["interior_id"], obj["x"], obj["y"]) for obj in after["layout"]] == [(1036, 26, 9)]
            for _ in range(2):
                A("refresh", island_b)
                B("refresh", island_a)
            assert sorted(e["event_id"] for e in B("inbox")) == sorted([online["event"], offline["event"]])


def test_sealed_messages_require_the_right_secret_and_context():
    from utils import island_peers as peers

    key = "21" * 32
    ctx = b"island-v1/sync"
    envelope = peers.seal(key, {"private": "private fixture"}, ctx)
    assert b"private fixture" not in envelope
    assert peers.unseal(key, envelope, ctx) == {"private": "private fixture"}
    for secret, body, tag in (
        (key, envelope[:-1] + bytes([envelope[-1] ^ 1]), ctx),
        ("22" * 32, envelope, ctx),
        (key, envelope, b"island-v1/pair"),
    ):
        with pytest.raises(peers.PeerError):
            peers.unseal(secret, body, tag)


def test_local_controls_require_the_owners_session_and_csrf(monkeypatch):
    from flask import Flask

    from api import island_peers as control

    app = Flask("island-peer-controls-test")
    app.secret_key = "fixture-only"
    app.register_blueprint(control.island_peers)
    monkeypatch.setattr(
        control.accounts, "get_gscd_owner", lambda card: "Resident" if card == "resident-card" else None
    )
    monkeypatch.setattr(control.peers, "invite", lambda card: {"codes": ["example"]})
    client = app.test_client()

    def post(origin="http://localhost", token="local-form"):
        return client.post("/island-peers/invite", json={}, headers={"Origin": origin, "X-Island-CSRF": token})

    assert post().status_code == 403
    with client.session_transaction() as state:
        state.update(username="Resident", gscd="resident-card", island_csrf="local-form")
    assert post().json == {"codes": ["example"]}
    assert post(origin="http://elsewhere.invalid").status_code == 403
    assert post(token="mismatch").status_code == 403
    with client.session_transaction() as state:
        state["visit_guest"] = True
    assert post().status_code == 403
    with client.session_transaction() as state:
        state.update(visit_guest=False, gscd="other-card")
    assert post().status_code == 403


def test_exchange_destinations_stay_inside_the_selected_network(monkeypatch):
    from utils import island_peers as peers

    monkeypatch.setattr(peers, "available", lambda: ["192.168.25.3/24", "100.98.1.9/10"])
    assert peers.source_address("192.168.25.54") == "192.168.25.3"
    assert peers.source_address("100.100.1.7") == "100.98.1.9"
    for destination in ("127.0.0.1", "8.8.8.8", "192.168.50.3", "192.168.25.3", "192.168.25.255", "example.invalid"):
        with pytest.raises(ValueError):
            peers.source_address(destination)
