"""Exercise the original movie's garden, shelf and footprint requests with its owner offline."""
import json
from unittest.mock import patch

from flask import Flask
from test_offline_islands import create, server

from api import native_islands, pdw_croft, pdw_home, pdw_item
from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
from utils import offline_islands as islands
from utils import pokemon, save_data, text, visits


def test_cached_garden_shelf_and_return_visit(tmp_path, monkeypatch):
    me, pal = gsid_to_gscd(91), gsid_to_gscd(92)
    with server(tmp_path / "me") as local:
        create(local, me, "Resident")
        my_doc = islands.export_island(me)

    with server(tmp_path / "pal") as remote:
        create(remote, pal, "Friend")
        remote.update(pal, "crop_data", lambda crop: crop["croft_list"][0].update(
            pokeitem_id=149, dirt_hp=13, kinomi_state=2, server={"planted_at": 100, "watered_at": 101}))
        remote.update(pal, "share_data", lambda shelf: shelf.update(
            share_list=[{"item_id": 149, "x": 1, "y": 2, "old_item_id": 149}]))
        islands.import_island(pal, my_doc)
        with patch.object(islands.time, "time", return_value=1700000000):
            event = islands.record_footprint(pal, my_doc["island_id"], "a5" * 16)
        remote.update(pal, "sleeping_pokemon", lambda sleeper: sleeper.update(pokemon_no=25))
        pal_doc = islands.export_island(pal)
        immutable = remote.read_full_state(pal)
        immutable_garden = remote.read(pal, "crop_data")
        immutable_shelf = remote.read(pal, "share_data")

    with server(tmp_path / "me") as local, Flask("offline-scenes").test_request_context("/"):
        islands.import_island(me, pal_doc)
        island = pal_doc["island_id"]
        mid = islands.native_member_id(me, island)
        assert islands.receive_footprints(me, island, [event, event]) == [event["event_id"], event["event_id"]]
        monkeypatch.setattr(native_islands, "resident", lambda: me)
        monkeypatch.setattr(save_data, "require_gscd", lambda: me)
        monkeypatch.setattr(pokemon, "shows_shiny", lambda shiny: shiny)
        before = local.read_full_state(me), local.read(me, "chest_data"), local.read(me, "crop_data")
        garden = pdw_croft.friend_croft_list({"member_savedata_id": str(mid)})
        plant = garden["croft_list"][0]
        assert garden["remains_watering"] == 0
        assert (plant["x"], plant["y"], plant["kinomi_id"], plant["kinomi_state"], plant["dirt_hp"]) == (1, 1, 1, 2, 13)
        assert plant["kinomi"] == text.lookup_str("item", 149)
        assert "server" not in plant
        shelf = pdw_item.friend_trade_list({"other_member_savedata_id": str(mid)})
        assert len(shelf) == 1 and (shelf[0]["x"], shelf[0]["y"], shelf[0]["item_id"]) == (1, 2, 149)
        assert shelf[0]["pokeitem"] == plant["kinomi"]
        water = pdw_croft.friend_water({"member_savedata_id": str(mid), "my_croft_id": str(plant["my_croft_id"])})
        trade = pdw_item.item_trade_update({"other_member_id": str(mid), "item_id": "149",
                                           "other_material_id": str(shelf[0]["material_id"])})
        assert water["error"]["details"]["message"]
        assert trade["error"]["details"]["message"]
        assert (local.read_full_state(me), local.read(me, "chest_data"), local.read(me, "crop_data")) == before
        monkeypatch.setattr(visits, "footprints", lambda code: [{
            "guest": "local", "updated_at": "2023-11-13 01:02:03", "pokemon": json.dumps({
                "pokemon_no": 7, "type1": 11, "type2": None, "personality": 0, "ball_name": 4, "sex": 0}),
            "watered": 1, "traded": 0,
        }])
        monkeypatch.setattr(save_data, "read_member", lambda code: {
            "pgl_name": "Local friend", "member_id": 80, "member_savedata_id": 81, "island_id": 201})
        monkeypatch.setattr(visits, "relationship", lambda code, guest: visits.PalStatus.FRIEND)
        pad = pdw_home.footprint_list({"rowcount": "1"})
        assert pad["cnt"] == 2 and len(pad["list"]) == 1
        first = pad["list"][0]
        assert first["updated_at"] == "2023-11-15 07:13"
        assert first["pokemon_no"] == 173 and first["pgl_name"] == "Friend" and "level" not in first
        assert first["is_pdw"] == 1 and first["visitor_member_savedata_id"] == first["member_id"] == mid
        assert native_islands.resolve(first["visitor_member_savedata_id"]) == pal_doc
        assert pdw_home.footprint_list({"offset": "1"})["list"][0]["pgl_name"] == "Local friend"

    with server(tmp_path / "pal") as remote:
        assert remote.read_full_state(pal) == immutable
        assert remote.read(pal, "crop_data") == immutable_garden
        assert remote.read(pal, "share_data") == immutable_shelf
