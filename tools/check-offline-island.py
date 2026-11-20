"""Walk from a friend's exported home through an offline wish to a Japanese Black wake packet.

The owner's process exits before the visitor starts. Both cartridges and both
accounts are disposable fixtures. The test never contacts a DS or a peer.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import socket
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4


def open_fixture(runtime, directory, name, gsid, species):
    directory.mkdir(exist_ok=True)
    os.environ.update(DW_LANG="ja", DW_SAVE_DIR=str(directory))
    sys.path.insert(0, str(runtime))
    from api.server import create_app
    from game_sync_server.entralinked.model.pkmn.pkmn_info import PkmnInfo
    from game_sync_server.entralinked.model.player.player import Player
    from game_sync_server.entralinked.model.player.player_manager import PlayerManager
    from game_sync_server.entralinked.utility.db_manager import db
    from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
    from utils.account_manager import accounts
    from utils.constants import PlayerStatus, Rom

    assert db._db_path.parent.resolve() == directory and accounts._db_path.parent.resolve() == directory
    code = gsid_to_gscd(gsid)
    players = PlayerManager()
    sleeper = PkmnInfo(pokemon_no=species, form_no=0, type1=0, type2=None, pokemon_nickname=name[:8],
                       oyaname=name[:7], level=10, sex=0, personality=0, ball_name=4)
    players.save_player(Player(code, play_status=PlayerStatus.PLAY_READY, rom_id=Rom.BLACK,
                               langcode=1, player_name=name[:7], dreamer_info=sleeper))
    assert accounts.create_account(name, "fixture", name+"@example.invalid", 1, 1, "friends", "friends", "activate")
    accounts.activate_account("activate")
    accounts.mark_registered(name)
    assert accounts.link_gscd(name, code)
    db.update(code, "player_data", lambda data: data["member"].update(pgl_name=name, trial_flag=0))
    web = create_app().test_client()
    with web.session_transaction() as session:
        session.update(username=name, gscd=code)
    return web, db, accounts, players, code


def publish(runtime, base):
    web, db, accounts, _, code = open_fixture(runtime, base/"owner", "IslandOwner", 600001, 173)
    try:
        db.update(code, "crop_data", lambda value: value.update(croft_list=[
            {"my_croft_id": 5, "x": 1, "y": 1, "pokeitem_id": 149, "dirt_hp": 60, "kinomi_state": 2}]))
        db.update(code, "share_data", lambda value: value.update(cnt=1, share_list=[
            {"material_id": 6, "x": 1, "y": 2, "item_id": 150}]))
        for version, x in ((1, 9), (2, 15)):
            def decorate(data):
                data["member"]["my_interior_list"][0].update(x=x, y=1)
            db.update(code, "player_data", decorate)
            response = web.get("/islands/export")
            assert response.status_code == 200 and response.is_json
            doc = response.get_json()
            assert (doc["version"], doc["content"]["decor"][0]["x"], doc["content"]["sleeper"]["pokemon_no"]) == (version, x, 173)
            (base/f"island-{version}.json").write_bytes(response.data)
    finally:
        db.close()
        accounts.close()


def verify(runtime, base):
    gsid = 700001
    web, db, accounts, players, code = open_fixture(runtime, base/"visitor", "IslandVisitor", gsid, 25)
    from game_sync_server.entralinked.configuration import Configuration
    from game_sync_server.entralinked.context import Context
    from game_sync_server.entralinked.model.dlc.dlc import DlcList
    from game_sync_server.entralinked.model.user.user_manager import UserManager
    from game_sync_server.entralinked.network.http.http_server import create_app as create_game
    from game_sync_server.entralinked.network.http.pgl_handler import PASSWORD, USERNAME
    from game_sync_server.entralinked.utility.url_encoded_form import decode_form, encode_form
    from utils import offline_islands as islands
    from utils.constants import PlayerStatus, Rom

    db.update(code, "game_sync", lambda state: state.update(last_wake_id=40))
    def no_connection(*args, **kwargs):
        raise AssertionError("The visitor attempted to contact a network while the owner was offline.")
    socket.socket.connect = no_connection
    island_id = json.loads((base/"island-1.json").read_bytes())["island_id"]
    room = f"/islands/{island_id}/"
    trail = room+"adventure"
    def page(action, method="GET", **fields):
        response = web.open("/api/", method=method, query_string={"p": action, **fields})
        assert response.status_code == 200, (action, response.status_code)
        return response.get_json()

    def import_copy(version):
        return web.post("/islands/import", data={"csrf": csrf, "snapshot": (
            io.BytesIO((base/f"island-{version}.json").read_bytes()), "island.json")})

    def trail_data():
        return db.read(code, "player_data")["dream_island"]

    try:
        assert web.get(trail).status_code == 404
        assert web.get("/islands/").status_code == 200
        with web.session_transaction() as state:
            csrf = state["island_csrf"]
        assert import_copy(1).status_code == 303
        roster = web.get("/islands/")
        assert roster.status_code == 200 and b"IslandOwner" in roster.data
        assert b'name="mode"' not in roster.data
        entry = {"csrf": csrf, "event_id": uuid4().hex}
        friends = page("pdw.home.my_island_area")["friend_list"]
        assert len(friends) == 1 and friends[0]["pgl_name"] == "IslandOwner"
        native_id = friends[0]["member_savedata_id"]
        map_fields = {"friend_member_savedata_id": native_id}
        for _ in range(2):
            response = web.post(room+"enter", data=entry)
            assert response.status_code == 303 and response.location.endswith(f"/pdw/?island={island_id}")
        assert web.get(room).location.endswith(f"/pdw/?island={island_id}")
        assert not islands.pending_footprints(code, island_id)
        details = web.get("/islands/native/" + island_id)
        assert details.status_code == 200
        navigation = details.get_json()
        assert navigation["member_savedata_id"] == native_id and navigation["adventure_url"] == trail
        assert navigation == web.get("/islands/native/" + str(native_id)).get_json()
        assert navigation["updated_at"] == islands.get_friend(code, island_id)["updated_at"]
        assert b"IslandOwner" in web.get(navigation["profile_url"]).data
        def check_scene(x):
            scene = page("pdw.home.friend_island", **map_fields)
            assert scene["member_savedata_id"] == native_id and scene["friend_pokemon"]["pokemon_no"] == 173
            assert scene["pgl_name"] == "IslandOwner" and scene["pokemon"]["pokemon_no"] == 25
            assert any((item["x"], item["y"]) == (x, 1) for item in scene["arranged_interior_list"])
            return scene["visit_count"]
        assert check_scene(9) == check_scene(9) == 1
        garden = page("pdw.croft.friend_croft_list", member_savedata_id=native_id)
        plot = garden["croft_list"][0]
        assert (plot["pokeitem_id"], plot["dirt_hp"], plot["kinomi_state"]) == (149, 60, 2)
        shelf = page("pdw.item.friend_trade_list", other_member_savedata_id=native_id)
        assert [(slot["x"], slot["y"], slot["item_id"]) for slot in shelf] == [(1, 2, 150)]
        assert web.post(room+"enter", data=entry).status_code == 303 and check_scene(9) == 1
        assert len(islands.pending_footprints(code, island_id)) == 1
        assert islands.get_friend(code, island_id)["content"]["decor"][0]["x"] == 9
        initial = web.get(trail)
        assert initial.status_code == 200 and initial.mimetype == "text/html"
        html = initial.get_data(as_text=True)
        form = {field: re.search(f'name="{field}" value="([^"]+)"', html).group(1) for field in ("csrf", "tuck")}
        def play(action, **fields):
            return web.post(trail, data={**form, "action": action, **fields})

        assert play("start", csrf="invalid").status_code == 403
        assert play("start", tuck="-1").status_code == 409
        assert play("start").status_code == 303 and play("start").status_code == 303
        initial_trail = dict(trail_data()["island_trails"][island_id])
        assert import_copy(2).status_code == 303 and import_copy(1).status_code == 303
        assert islands.get_friend(code, island_id)["content"]["decor"][0]["x"] == 15
        assert check_scene(15) == 1
        assert trail_data()["island_trails"][island_id] == initial_trail
        html = web.get(trail).get_data(as_text=True)
        target = int(re.search(r'class="trail-sample" src="/report/assets/images/footprint/(\d+)\.png"', html).group(1))
        assert target == 173 and web.get(f"/report/assets/images/footprint/{target:03}.png").status_code == 200
        choices = [int(n) for n in re.findall(r'name="track" value="(\d+)"', html)]
        assert len(set(choices)) == 3 and target in choices
        assert play("track", track=next(n for n in choices if n != target)).status_code == 303
        assert not trail_data()["friends"]
        for _ in range(2):
            assert play("track", track=target).status_code == 303
        friend, = trail_data()["friends"]
        card, = page("pdw.dreamland.tree_top")["encount_list"]
        assert (card["pokemon_no"], card["form_no"], card["get_pokemon_id"]) == (173, 0, friend["id"])
        berry, = page("pdw.item.item_list")["list"]
        assert berry["item_cnt"] == 5
        for _ in range(2):
            assert play("wish", berry=berry["pokeitem_id"]).status_code == 303
        page("pdw.dreamland.tree_offer", "POST", get_pokemon_id=friend["id"], pokeitem_id=berry["pokeitem_id"])
        assert page("pdw.item.item_list")["list"][0]["item_cnt"] == 4
        assert page("pdw.home.board_pokemon_list", status_type=1)["total_count"] == 1
        for _ in range(2):
            assert play("finish").status_code == 303

        catalog = base/"empty-dlc.json"
        catalog.write_text("{}", encoding="utf-8")
        game = create_game(Context(Configuration(), UserManager(), players, DlcList(base, catalog))).test_client()
        def nas(action, **fields):
            data = encode_form({"action": action, "userid": "9"*13, "passwd": "fixture", **fields})
            return decode_form(game.post("/ac", data=data, content_type="application/x-www-form-urlencoded").get_data(as_text=True))
        assert nas("acctcreate")["returncd"] == "002"
        token = nas("SVCLOC", svc="0000")["servicetoken"]
        def card_request(action, method="GET"):
            response = game.open("/dsio/gw", method=method, auth=(USERNAME, PASSWORD), query_string={
                "p": action, "tok": token, "gsid": gsid, "rom": int(Rom.BLACK), "langcode": 1})
            assert response.status_code == 200 and response.data[:128] == bytes(128)
            return response.data[128:]
        assert card_request("account.playstatus") == struct.pack("<H", PlayerStatus.WAKE_READY)
        packet = card_request("savedata.download")
        assert len(packet) == 284 and card_request("savedata.download") == packet
        assert struct.unpack_from("<IHH", packet) == (41, 173, friend["move"] or 0)
        assert packet[12:84] == bytes(72)
        assert db.read(code, "sleeping_pokemon")["pokemon_no"] == 25
        for _ in range(2):
            assert card_request("savedata.download.finish", "POST") == b""
        assert card_request("account.playstatus") == struct.pack("<H", PlayerStatus.AWAKE)
        assert card_request("savedata.download") == b""
        assert page("pdw.home.board_pokemon_list", status_type=2)["total_count"] == 1
        assert db.read(code, "player_data")["member"]["send_pokemon_count"] == 1
        assert db.read(code, "sleeping_pokemon") is None

        # Two tabs on the same signed-in account: visiting only reads a long-absent
        # player's Berries. The normal PGL tab still applies the original conversion.
        db.update(code, "player_data", lambda data: data["member"].update(last_started_at=1, item_deleted_flag=0))
        berries_before = db.read(code, "chest_data")
        assert any(row["item_cnt"] > 1 for row in berries_before["list"])
        visiting = web.get(room+"game-api/", query_string={"p": "pgl.top.init"})
        assert visiting.status_code == 200 and visiting.get_json()["member"]["item_deleted_flag"] == 0
        assert db.read(code, "chest_data") == berries_before
        resident = page("pgl.top.init")["member"]
        assert resident["item_deleted_flag"] == 1 and resident["item_deleted_point"] > 0
        assert db.read(code, "chest_data") != berries_before
    finally:
        db.close()
        accounts.close()


def tree_hash(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).digest() for path in directory.iterdir() if path.is_file()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--owner-fixture", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run without -O to enable checks.")
    runtime = args.runtime.resolve()
    if args.owner_fixture:
        publish(runtime, args.owner_fixture)
    else:
        with TemporaryDirectory(prefix="dreamworld-offline-") as temp:
            base = Path(temp).resolve()
            subprocess.run([sys.executable, __file__, str(runtime), "--owner-fixture", str(base)], check=True)
            before = tree_hash(base/"owner")
            verify(runtime, base)
            assert before and tree_hash(base/"owner") == before
        print("PASS: owner stopped, house and footprint persisted, snapshot upgrade preserved adventure, one Berry, "
              "one Cleffa, one Japanese Black wake delivery after retries; owner files unchanged.")
