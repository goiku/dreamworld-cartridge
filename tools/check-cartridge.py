"""Exercise the restored friend selection and Black cartridge download with an isolated synthetic save.

Run with the installed runtime's Python. The fixture starts just after befriending
Cleffa. Requests use Flask test clients and never open sockets or load a game ROM.
"""
import argparse
import json
import os
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory


def check(runtime, store):
    os.environ.update(DW_LANG="en", DW_SAVE_DIR=str(store))
    sys.path.insert(0, str(runtime))
    from api.server import create_app as create_web
    from game_sync_server.entralinked.configuration import Configuration
    from game_sync_server.entralinked.context import Context
    from game_sync_server.entralinked.model.dlc.dlc import DlcList
    from game_sync_server.entralinked.model.pkmn.pkmn_info import PkmnInfo
    from game_sync_server.entralinked.model.player.player import Player
    from game_sync_server.entralinked.model.player.player_manager import PlayerManager
    from game_sync_server.entralinked.model.user.user_manager import UserManager
    from game_sync_server.entralinked.network.http.http_server import create_app as create_game
    from game_sync_server.entralinked.network.http.pgl_handler import PASSWORD, USERNAME
    from game_sync_server.entralinked.utility.db_manager import db
    from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
    from game_sync_server.entralinked.utility.url_encoded_form import decode_form, encode_form
    from utils.account_manager import accounts
    from utils.constants import PlayerStatus, Rom

    assert db._db_path.parent.resolve() == store and accounts._db_path.parent.resolve() == store
    gsid = 100001
    code = gsid_to_gscd(gsid)
    players = PlayerManager()
    sleeper = PkmnInfo(pokemon_no=25, form_no=0, type1=12, type2=None, pokemon_nickname="Spark",
                       oyaname="Test", level=10, sex=0, personality=0, ball_name=4)
    players.save_player(Player(code, play_status=PlayerStatus.PLAY_READY, rom_id=Rom.BLACK,
                               langcode=1, player_name="Test", dreamer_info=sleeper))
    db.update(code, "game_sync", lambda state: state.update(last_wake_id=40))
    catalog = json.loads((runtime / "json_data/dream_islands.json").read_text(encoding="utf-8"))
    cleffa = next(entry for slot in catalog["objects"].values() for entry in slot["contents"]
                  if entry.get("pokemon_no") == 173)
    chosen_move = cleffa["special_moves"][0]
    friend_id = 1
    friend = dict(id=friend_id, object_id=cleffa["object_pokemon_id"], move=chosen_move, met_at="2000-01-01 00:00")
    db.update(code, "player_data", lambda data: data.update(dream_island={
        "tuck": data["member"]["sleep_pokemon_count"], "visit": {}, "friends": [friend], "wished": None}))

    # No cosmetic DLC is required for a forest encounter.
    empty_catalog = store / "empty-dlc.json"
    empty_catalog.write_text("{}", encoding="utf-8")
    context = Context(Configuration(), UserManager(), players, DlcList(store, empty_catalog))
    game = create_game(context).test_client()
    web = create_web().test_client()
    with web.session_transaction() as session:
        session.update(username="ForestCheck", gscd=code)

    def page(action, method="GET", **fields):
        response = web.open("/api/", method=method, query_string={"p": action, **fields})
        assert response.status_code == 200, (action, response.status_code)
        return response.get_json()

    def nas(action, **fields):
        form = encode_form({"action": action, "userid": "9" * 13, "passwd": "synthetic-fixture", **fields})
        response = game.post("/ac", data=form, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 200, (action, response.status_code)
        return decode_form(response.get_data(as_text=True))

    try:
        page("pgl.member.profile.my_state")
        page("pdw.home.pdw_start", "POST")
        berry, = page("pdw.item.item_list")["list"]
        assert berry["item_cnt"] == 5
        card, = page("pdw.dreamland.tree_top")["encount_list"]
        assert (card["pokemon_no"], card["get_pokemon_id"]) == (173, friend_id)
        for _ in range(2):
            page("pdw.dreamland.tree_offer", "POST", pokeitem_id=berry["pokeitem_id"], get_pokemon_id=friend_id)
            page("pdw.home.board_pokemon_selects", "POST", **{"get_pokemon_id[0]": friend_id})
        assert page("pdw.item.item_list")["list"][0]["item_cnt"] == 4
        assert page("pdw.home.board_pokemon_list", status_type=1)["total_count"] == 1
        page("pdw.home.pdw_end")

        assert nas("acctcreate")["returncd"] == "002"
        token = nas("SVCLOC", svc="0000")["servicetoken"]

        def cartridge(action, method="GET"):
            response = game.open("/dsio/gw", method=method, auth=(USERNAME, PASSWORD),
                                 query_string=dict(p=action, tok=token, gsid=gsid, rom=int(Rom.BLACK), langcode=1))
            assert response.status_code == 200 and response.data[:128] == bytes(128), action
            return response.data[128:]

        assert cartridge("account.playstatus") == struct.pack("<H", PlayerStatus.WAKE_READY)
        packet = cartridge("savedata.download")
        assert len(packet) == 284 and cartridge("savedata.download") == packet
        assert struct.unpack_from("<IHH", packet) == (41, 173, chosen_move)
        assert packet[12:84] == bytes(72), "A second encounter appeared in the wake payload"
        assert db.read(code, "sleeping_pokemon")["pokemon_no"] == sleeper.pokemon_no
        for _ in range(2):
            assert cartridge("savedata.download.finish", "POST") == b""
        assert cartridge("account.playstatus") == struct.pack("<H", PlayerStatus.AWAKE)
        assert cartridge("savedata.download") == b""
        assert page("pdw.home.board_pokemon_list", status_type=1)["total_count"] == 0
        assert page("pdw.home.board_pokemon_list", status_type=2)["total_count"] == 1
        assert db.read(code, "player_data")["member"]["send_pokemon_count"] == 1
        assert db.read(code, "sleeping_pokemon") is None
    finally:
        db.close()
        accounts.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runtime", type=Path, help="Patched Dream World runtime directory")
    args = parser.parse_args()
    if not __debug__:
        parser.error("Run without -O so the smoke test can check its results.")
    runtime = args.runtime.resolve()
    if not (runtime / "game_sync_server/server.py").is_file():
        parser.error("Supply the installed runtime containing game_sync_server/server.py.")
    with TemporaryDirectory(prefix="dreamworld-cartridge-check-") as directory:
        check(runtime, Path(directory).resolve())
    print("PASS: selected Cleffa, spent one Berry, decoded one Black encounter, confirmed one delivery after retries.")
