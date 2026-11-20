"""Exercise both directions of a visit, a browser reward and the home cartridge wake protocol.

Run with the installed Dream World Python. Two local servers bind ephemeral loopback
ports and use separate temporary saves. No ROM, Tailscale connection or DS is needed.
"""
import argparse
import json
import logging
import multiprocessing
import os
from contextlib import contextmanager
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import threading
import traceback


def fixture(runtime, cartridge, pipe, directory):
    os.environ.update(DW_LANG="en", DW_SAVE_DIR=str(directory))
    sys.path.insert(0, str(runtime))
    from werkzeug.serving import make_server
    from api.server import create_app
    from game_sync_server.entralinked.configuration import Configuration
    from game_sync_server.entralinked.context import Context
    from game_sync_server.entralinked.model.dlc.dlc import DlcList
    from game_sync_server.entralinked.model.pkmn.pkmn_info import PkmnInfo
    from game_sync_server.entralinked.model.player.player import Player
    from game_sync_server.entralinked.model.player.player_manager import PlayerManager
    from game_sync_server.entralinked.model.user.user_manager import UserManager
    from game_sync_server.entralinked.network.http.http_server import create_app as game_app
    from game_sync_server.entralinked.network.http.pgl_handler import PASSWORD, USERNAME
    from game_sync_server.entralinked.utility.db_manager import db
    from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
    from game_sync_server.entralinked.utility.url_encoded_form import decode_form, encode_form
    from scripts.visit_friend import Conflict, LinkStore, Peer, pair, sync_once
    from utils import visit_storage
    from utils.account_manager import accounts
    from utils.constants import PlayerStatus, Rom

    assert accounts._db_path.parent.resolve() == db._db_path.parent.resolve() == directory
    name = "ForestTest"
    code = gsid_to_gscd(cartridge)
    assert accounts.create_account(name, "test-password-only", "fixture@example.invalid", 1, 1,
                                   "friends", "friends", "local-activation")
    accounts.activate_account("local-activation")
    assert accounts.link_gscd(name, code)
    accounts.mark_registered(name)

    players = PlayerManager()
    sleeper = PkmnInfo(pokemon_no=25, form_no=0, type1=12, type2=None, pokemon_nickname="Spark",
                       oyaname="Test", level=10, sex=0, personality=0, ball_name=4)
    players.save_player(Player(code, play_status=PlayerStatus.PLAY_READY, rom_id=Rom.BLACK,
                               langcode=1, player_name="Test", dreamer_info=sleeper))
    db.update(code, "game_sync", lambda state: state.update(last_wake_id=40))
    island = json.loads((runtime / "json_data/dream_islands.json").read_text("utf-8"))
    cleffa = next(item for slot in island["objects"].values() for item in slot["contents"]
                  if item.get("pokemon_no") == 173)
    move = cleffa["special_moves"][0]
    friend = dict(id=1, object_id=cleffa["object_pokemon_id"], move=move, met_at="2000-01-01 00:00")
    db.update(code, "player_data", lambda data: data.update(dream_island={
        "tuck": data["member"]["sleep_pokemon_count"], "visit": {}, "friends": [friend], "wished": None}))
    dlc = directory / "dlc.json"
    dlc.write_text("{}", encoding="utf-8")
    context = Context(Configuration(), UserManager(), players, DlcList(directory, dlc))
    game = game_app(context).test_client()
    app = create_app()
    web = app.test_client()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    pipe.send((True, (server.server_port, code)))
    links = LinkStore(directory)
    peer = key = None

    def page(action, method="GET", **fields):
        response = web.open("/api/", method=method, query_string={"p": action, **fields})
        assert response.status_code == 200, (action, response.status_code)
        return response.get_json()

    def verify_wake():
        def nas(action, **fields):
            form = encode_form(dict(action=action, userid="9" * 13, passwd="synthetic-ds", **fields))
            response = game.post("/ac", data=form, content_type="application/x-www-form-urlencoded")
            return decode_form(response.get_data(as_text=True))
        assert nas("acctcreate")["returncd"] == "002"
        token = nas("SVCLOC", svc="0000")["servicetoken"]

        def packet(action, method="GET"):
            response = game.open("/dsio/gw", method=method, auth=(USERNAME, PASSWORD),
                                 query_string=dict(p=action, tok=token, gsid=cartridge, rom=int(Rom.BLACK), langcode=1))
            assert response.status_code == 200 and response.data[:128] == bytes(128), action
            return response.data[128:]
        assert packet("account.playstatus") == struct.pack("<H", PlayerStatus.WAKE_READY)
        data = packet("savedata.download")
        assert len(data) == 284 and struct.unpack_from("<IHH", data) == (41, 173, move)
        assert packet("savedata.download") == data
        assert db.read(code, "sleeping_pokemon")["pokemon_no"] == 25
        try:
            visit_storage.export_local(name, code)
        except visit_storage.VisitConflict:
            pass
        else:
            raise AssertionError("An unconfirmed wake must wait for the cartridge.")
        assert packet("savedata.download.finish", "POST") == b""
        assert packet("savedata.download.finish", "POST") == b""
        assert packet("account.playstatus") == struct.pack("<H", PlayerStatus.AWAKE)
        assert db.read(code, "player_data")["member"]["send_pokemon_count"] == 1

    try:
        while True:
            command, args = pipe.recv()
            result = None
            if command == "stop":
                break
            if command == "invite":
                result = visit_storage.create_invite()
            elif command == "pair":
                port, invite = args
                peer = Peer("127.0.0.1", port)
                key = (f"127.0.0.1:{port}", name, code)
                pair(peer, links, key, lambda: invite)
                result = sync_once(peer, links, key)
            elif command == "ticket":
                result = peer.request("ticket", links.lookup(key)["token"], {})["ticket"]
            elif command == "open":
                ticket, expected_code = args
                response = web.post("/visit-sync/login", data={"ticket": ticket})
                assert response.status_code == 303 and response.headers["Location"] == "/pdw/"
                with web.session_transaction() as session:
                    assert session["visit_guest"] and session["gscd"] == expected_code
                    assert session["username"] != name
                assert app.test_client().post("/visit-sync/login", data={"ticket": ticket}).status_code == 401
            elif command == "point":
                card, amount = args
                db.update(card, "player_data", lambda data: data["member"].update(point=amount))
            elif command == "summary":
                card, = args
                member = db.read(card, "player_data")["member"]
                result = (member["member_id"], member["point"], member["send_pokemon_count"])
            elif command == "sync":
                try:
                    result = sync_once(peer, links, key, resolve=args[0] if args else None)
                except Conflict:
                    result = "conflict"
            elif command == "wish":
                page("pgl.member.profile.my_state")
                page("pdw.home.pdw_start", "POST")
                berry, = page("pdw.item.item_list")["list"]
                card, = page("pdw.dreamland.tree_top")["encount_list"]
                assert card["pokemon_no"] == 173
                page("pdw.dreamland.tree_offer", "POST", pokeitem_id=berry["pokeitem_id"],
                     get_pokemon_id=card["get_pokemon_id"])
                page("pdw.home.board_pokemon_selects", "POST", **{"get_pokemon_id[0]": card["get_pokemon_id"]})
                page("pdw.home.pdw_end")
            elif command == "wake":
                verify_wake()
            else:
                raise AssertionError(f"Unknown test step {command}")
            pipe.send((True, result))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        links.db.close()
        db.close()
        accounts.close()


def run_fixture(runtime, cartridge, pipe):
    try:
        logging.disable(logging.CRITICAL)
        with TemporaryDirectory(prefix="dreamworld-visit-check-") as directory:
            fixture(runtime, cartridge, pipe, Path(directory).resolve())
    except Exception:
        pipe.send((False, traceback.format_exc()))
    finally:
        pipe.close()


def receive(pipe):
    if not pipe.poll(45):
        raise TimeoutError("The temporary server did not complete its test step.")
    ok, result = pipe.recv()
    if not ok:
        raise AssertionError(result)
    return result


@contextmanager
def host(runtime, cartridge):
    context = multiprocessing.get_context("spawn")
    local, child = context.Pipe()
    process = context.Process(target=run_fixture, args=(runtime, cartridge, child))
    process.start()
    child.close()
    try:
        port, code = receive(local)
        def call(command, *args):
            local.send((command, args))
            return receive(local)
        yield call, port, code
    finally:
        if process.is_alive():
            try:
                local.send(("stop", ()))
            except (BrokenPipeError, EOFError, OSError):
                pass
        local.close()
        process.join(5)
        if process.is_alive():
            process.terminate()
            process.join()


def check(runtime):
    with host(runtime, 100001) as (a, port_a, card_a), host(runtime, 100002) as (b, port_b, card_b):
        original_a = a("summary", card_a)
        original_b = b("summary", card_b)
        assert original_a[0] == original_b[0], "The test requires an initial member number collision."
        assert a("pair", port_b, b("invite")) == "current"
        b("open", a("ticket"), card_a)
        assert b("summary", card_a)[0] != original_b[0], "Visitor inherited a resident's member number."
        b("wish")
        assert a("sync") == "home" and a("sync") == "current"
        assert b("summary", card_b) == original_b
        a("wake")
        assert a("sync") == "host" and a("sync") == "current"
        assert a("summary", card_a)[0] == original_a[0] and b("summary", card_a)[2] == 1

        assert b("pair", port_a, a("invite")) == "current"
        a("open", b("ticket"), card_b)
        b("point", card_b, 120)
        assert b("sync") == "host" and a("summary", card_b)[1] == 120
        b("point", card_b, 130)
        a("point", card_b, 140)
        assert b("sync") == "conflict"
        assert b("summary", card_b)[1] == 130 and a("summary", card_b)[1] == 140
        assert b("sync", "host") == "home"
        assert b("summary", card_b) == (original_b[0], 140, original_b[2])
        assert b("sync") == "current"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path, help="Installed Dream World directory")
    args = parser.parse_args()
    if not __debug__ or not (args.runtime / "scripts/visit_friend.py").is_file():
        parser.error("Use the patched runtime and run Python without -O.")
    check(args.runtime.resolve())
    print("PASS: two isolated hosts, both visit directions, separate residents, browser wish,"
          " conflicting edits and one confirmed Black cartridge reward.")
