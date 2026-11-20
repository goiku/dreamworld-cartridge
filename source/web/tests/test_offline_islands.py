"""A shared postcard, offline visit and delivery across independent game stores."""
import copy
import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from game_sync_server.entralinked.model.player.player import new_player_data
from game_sync_server.entralinked.utility.db_manager import DBManager
from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
from utils import offline_islands as islands


@contextmanager
def server(path):
    store = DBManager(path)
    try:
        with patch.object(islands, "db", store):
            yield store
    finally:
        store.close()


def create(store, code, name):
    store.write_gscd(code)
    data = new_player_data(1, [1, 2])
    data["member"].update(gscd=code, gsid=123, pgl_name=name, player_name="Trainer", rom_id=20,
                          player_badge_num=3, blocked_profiles=["a private contact"],
                          my_interior_list=[{"interior_id": 3001, "my_interior_id": 5, "x": 17, "y": 9}])
    data["token"] = "private credential"
    store.write_full_state(code, data, {"hours_played": 74, "upload_digest": "a private upload hash"},
                           {"pokemon_no": 173, "level": 10, "pokemon_nickname": "pipi", "type1": 0,
                            "oyaname": "third party", "secret_id": 44})


def test_import_stale_tamper_and_independent_owners(tmp_path):
    host = gsid_to_gscd(19)
    guest = gsid_to_gscd(29)
    with server(tmp_path / "host") as store:
        create(store, host, "Shared name")
        store.update(host, "crop_data", lambda crop: crop["croft_list"][0].update(
            server={"planted_at": 1720000000, "watered_at": 1720040000, "last_visitor": "private contact"}))
        store.update(host, "game_sync", lambda sync: sync.update(levels_gained=1, loblolly_decor=3,
                                                                  encounters=[{"name": "private contact"}], items=[]))
        before = store.read_full_state(host)
        old = islands.export_island(host)
        assert islands.export_island(host) == old
        assert store.read_full_state(host) == before
        assert old["content"]["decor"] == [{"interior_id": 3001, "x": 17, "y": 9}]
        assert old["content"]["profile"]["hours_played"] == 74
        for key, expected in (("levels_gained", 1), ("loblolly_decor", 3), ("pending_partner_count", 1),
                              ("pending_item_stacks", 0)):
            assert old["content"]["profile"][key] == expected
        assert old["content"]["garden"][0]["planted_at"] == 1720000000
        assert old["content"]["garden"][0]["watered_at"] == 1720040000
        assert old["content"]["sleeper"]["pokemon_no"] == 173
        raw = json.dumps(old).encode()
        for secret in (host.encode(), b"private credential", b"upload_digest", b"private contact", b"third party", b"secret_id"):
            assert secret not in raw
        assert islands.decode_snapshot(raw) == old
        store.update(host, "player_data", lambda p: p["member"]["my_interior_list"][0].update(x=18))
        new = islands.export_island(host)
        assert new["version"] == old["version"] + 1 and old["island_id"] == new["island_id"]
        latest_state = store.read_full_state(host)
    # Host connection is closed. The guest has only its own database and the shared files.
    with server(tmp_path / "guest") as store:
        create(store, guest, "Shared name")
        before = store.read_full_state(guest)
        assert islands.import_island(guest, new) == new
        assert islands.import_island(guest, old) == new
        assert islands.import_island(guest, new) == new
        assert islands.get_friend(guest, new["island_id"])["content"]["decor"][0]["x"] == 18
        roster = islands.list_friends(guest)
        assert len(roster) == 1 and roster[0]["house"] == new["content"]["island"]["island_id"]
        assert islands.list_friends(host) == []
        assert islands.export_island(guest)["island_id"] != new["island_id"]
        bad = copy.deepcopy(new)
        bad["content"]["decor"][0]["x"] = 217
        with pytest.raises(islands.IslandError):
            islands.import_island(guest, bad)
        assert islands.get_friend(guest, new["island_id"]) == new
        assert store.read_full_state(guest) == before
    with server(tmp_path / "host") as store:
        assert latest_state == store.read_full_state(host)


def test_event_replay_after_owner_goes_offline(tmp_path):
    host, guest = gsid_to_gscd(1), gsid_to_gscd(2)
    with server(tmp_path / "host") as store:
        create(store, host, "Host")
        original = store.read_full_state(host)
        target = islands.export_island(host)
    with server(tmp_path / "guest") as store:
        create(store, guest, "Friend")
        islands.import_island(guest, target)
        source = islands.export_island(guest)
        event = islands.record_footprint(guest, target["island_id"], "a" * 32)
        assert islands.record_footprint(guest, target["island_id"], "a" * 32) == event
        pending = islands.pending_footprints(guest, target["island_id"])
        assert pending == [event]
    with server(tmp_path / "host") as store:
        islands.import_island(host, source)
        bad = dict(event, name="This should roll back")
        with pytest.raises(islands.IslandError):
            islands.receive_footprints(host, source["island_id"], [event, bad])
        assert islands.received_footprints(host) == []
        ack = islands.receive_footprints(host, source["island_id"], pending)
        # The visitor missed the first ACK.
        assert islands.receive_footprints(host, source["island_id"], pending) == ack
        assert len(islands.received_footprints(host)) == 1
        assert islands.received_footprints(host)[0]["name"] == "Friend"
        assert store.read_full_state(host) == original
    with server(tmp_path / "guest"):
        islands.acknowledge_footprints(guest, target["island_id"], ack)
        islands.record_footprint(guest, target["island_id"], "a" * 32)
        assert islands.pending_footprints(guest, target["island_id"]) == []


def test_import_limits_and_invalid_json():
    for raw in (b" " * (islands.MAX_BYTES + 1), b"[]", b'{"x":1,"x":2}', b"\xff", b"[" * 1200 + b"]" * 1200):
        with pytest.raises(islands.IslandError):
            islands.decode_snapshot(raw)



def test_awake_island_can_share_and_leave_a_footprint(tmp_path):
    host, guest = gsid_to_gscd(5), gsid_to_gscd(6)
    with server(tmp_path / "host") as store:
        create(store, host, "Owner")
        doc = islands.export_island(host)
    with server(tmp_path / "guest") as store:
        create(store, guest, "Awake")
        data, sync, _sleeper = store.read_full_state(guest)
        store.write_full_state(guest, data, sync, None)
        assert islands.export_island(guest)["content"]["sleeper"] == {}
        islands.import_island(guest, doc)
        assert islands.record_footprint(guest, doc["island_id"], "b" * 32)["pokemon_no"] is None


def test_legacy_nickname_and_confirmed_literal_question_marks(tmp_path):
    host = gsid_to_gscd(7)
    with server(tmp_path / "host") as store:
        create(store, host, "Owner")
        store.update(host, "sleeping_pokemon", lambda sleeper: sleeper.update(pokemon_nickname="???"))
        old = islands.export_island(host)
        assert "pokemon_nickname" not in old["content"]["sleeper"]
        assert store.read(host, "sleeping_pokemon")["pokemon_nickname"] == "???"
        store.update(host, "sleeping_pokemon", lambda sleeper: sleeper.update(nickname_verified=True))
        fresh = islands.export_island(host)
        assert fresh["version"] > old["version"]
        assert fresh["content"]["sleeper"]["pokemon_nickname"] == "???"
        store.update(host, "sleeping_pokemon", lambda sleeper: sleeper.update(pokemon_nickname="ピィ　Ａ"))
        assert islands.export_island(host)["content"]["sleeper"]["pokemon_nickname"] == "ピィ　Ａ"


def test_native_ids_follow_local_sequence_and_are_private_to_each_visitor(tmp_path):
    host, one, two = (gsid_to_gscd(i) for i in (101, 102, 103))
    with server(tmp_path / "origin") as store:
        create(store, host, "Host")
        island = islands.export_island(host)
    with server(tmp_path / "visitor") as store:
        for code in (one, two):
            create(store, code, "Local")
        assert islands.get_native_friend(one, 1) is None
        with pytest.raises(islands.IslandNotFound):
            islands.native_member_id(one, island["island_id"])
        islands.import_island(one, island)
        first = islands.list_friends(one)[0]["member_savedata_id"]
        assert first > 1 and islands.get_native_friend(one, first) == island
        islands.import_island(two, island)
        second = islands.native_member_id(two, island["island_id"])
        assert second > first and store.next_id("member_id")[0] > second
        assert islands.get_native_friend(two, first) is None
        assert islands.get_native_friend(one, second) is None
        assert set(store.get_all_gscds()) == {one, two}
        with store.transaction() as conn:
            conn.execute("DELETE FROM offline_island_map WHERE gscd=?", (one,))
        # Upgrade a legacy cache with no map ID. Once allocated it survives updates and reopen.
        restored = islands.list_friends(one)[0]["member_savedata_id"]
        assert restored > second and islands.get_native_friend(one, restored) == island
        islands.import_island(one, island)
    with server(tmp_path / "visitor"):
        assert islands.native_member_id(one, island["island_id"]) == restored
