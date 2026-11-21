from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from game_sync_server.entralinked.utility.db_manager import DBManager
from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
from tests.test_offline_islands import create
from utils import island_actions as actions
from utils import managers, save_data, visits
from utils import offline_islands as islands


@contextmanager
def active(path):
    db = DBManager(path)
    try:
        with ExitStack() as stack:
            for module in (actions, managers, islands, save_data):
                stack.enter_context(patch.object(module, "db", db))
            yield db
    finally:
        db.close()


def count(card, item):
    stack = managers.get_chest(card).fetch_item_by_id(item)
    return stack["item_cnt"] if stack else 0


def test_offline_reservations_delayed_ack_and_changed_shelf(tmp_path):
    host, guest = gsid_to_gscd(70), gsid_to_gscd(71)
    with active(tmp_path / "home") as db:
        create(db, host, "Host")
        shelf = managers.get_shelf(host)
        for x in (0, 1, 2):
            shelf.place(x, 0, 149, host)
        owner = islands.export_island(host)
    island = owner["island_id"]
    with active(tmp_path / "away") as db:
        create(db, guest, "Visitor")
        visitor = islands.export_island(guest)
        islands.import_island(guest, owner)
        actions.receive(guest, island, [])
        managers.get_chest(guest).add_item(150, 3)
        initial = count(guest, 150), count(guest, 149)
        for slot in (0, 1, 2, 2):
            actions.request_action(guest, island, owner["version"], "trade", slot, 150)
        batch = actions.pending(guest, island)
        assert len(batch) == 3 and count(guest, 150) == initial[0] - 3
        assert actions.pending_action_counts(guest) == {island: {"trade": 3}}
    with active(tmp_path / "home"):
        islands.import_island(host, visitor)
        stale = managers.get_shelf(host).data["share_list"][2]
        managers.get_shelf(host).swap_from_island(stale["material_id"], 149, "Other")
        results = actions.receive(host, visitor["island_id"], batch)
        assert list(results.values()) == [True, True, False]
        assert actions.receive(host, visitor["island_id"], batch) == results
        assert [s["item_id"] for s in managers.get_shelf(host).data["share_list"]] == [150, 150, 149]
    with active(tmp_path / "away"):
        actions.settle(guest, island, batch, results)
        actions.settle(guest, island, batch, results)
        assert (count(guest, 150), count(guest, 149)) == (initial[0] - 2, initial[1] + 2)
        assert not actions.pending(guest, island)
        assert actions.pending_action_counts(guest) == {}


def test_water_receipts_and_refund(tmp_path):
    host, guest = gsid_to_gscd(46), gsid_to_gscd(47)
    with active(tmp_path / "home") as db:
        create(db, host, "Host")
        garden = managers.get_crops(host)
        for plot in garden.data["croft_list"][:2]:
            garden.sow(plot["my_croft_id"], 149)

        def dry(data):
            for plot in data["croft_list"][:2]:
                plot["dirt_hp"] = 20

        db.update(host, "crop_data", dry)
        owner = islands.export_island(host)
    island = owner["island_id"]
    with active(tmp_path / "away") as db:
        create(db, guest, "Visitor")
        visitor = islands.export_island(guest)
        islands.import_island(guest, owner)
        actions.receive(guest, island, [])
        remaining = visits.friend_waterings_left(guest)
        for i in (0, 1):
            actions.request_action(guest, island, owner["version"], "water", i)
        batch = actions.pending(guest, island)
        assert visits.friend_waterings_left(guest) == remaining - 2
        assert actions.pending_action_counts(guest) == {island: {"water": 2}}
    with active(tmp_path / "home"):
        islands.import_island(host, visitor)
        garden = managers.get_crops(host)
        garden.water_plot(garden.data["croft_list"][1]["my_croft_id"])
        results = actions.receive(host, visitor["island_id"], batch)
        assert list(results.values()) == [True, False]
        assert actions.receive(host, visitor["island_id"], batch) == results
    with active(tmp_path / "away"):
        points = save_data.read_member(guest)["experiment_point"]
        actions.settle(guest, island, batch, results)
        actions.settle(guest, island, batch, results)
        assert visits.friend_waterings_left(guest) == remaining - 1
        assert save_data.read_member(guest)["experiment_point"] == points + 10
        assert actions.pending_action_counts(guest) == {}


def test_roster_counts_all_batches_and_only_the_selected_save(tmp_path):
    from api import offline_friends

    visitor, other, owner = map(gsid_to_gscd, (201, 202, 203))
    labels = offline_friends._labels[offline_friends.LANG]
    with active(tmp_path / "roster") as db:
        for card in (visitor, other, owner):
            create(db, card, "Fixture")
        friend = islands.export_island(owner)
        island = friend["island_id"]
        for card, amount in ((visitor, islands.MAX_BATCH + 1), (other, 1)):
            islands.import_island(card, friend)
            for i in range(amount):
                islands.record_footprint(card, island, f"{i:032x}")
        with db.transaction() as conn:
            actions.schema(conn)
            conn.executemany(
                "INSERT INTO island_actions VALUES(?,?,?,?,?)",
                [(visitor, island, str(i), '{"kind":"water"}', "pending") for i in range(31)]
                + [(other, island, "0", '{"kind":"trade"}', "pending")],
            )
        for card, feet, water, trade in ((visitor, islands.MAX_BATCH + 1, 31, 0), (other, 1, 0, 1)):
            row = offline_friends._delivery_status(card, [friend], {})[island]
            assert row["last_sync"] is None
            assert row["summary"] == labels["pending_counts"].format(feet=feet, water=water, trade=trade) + " " + labels["pair_to_send"]


def test_profile_form_reserves_trade_only_with_its_session_token(tmp_path, monkeypatch):
    from api import native_islands
    from api.server import create_app
    from utils import island_peers

    host, guest = gsid_to_gscd(25), gsid_to_gscd(27)
    with active(tmp_path / "host") as db:
        create(db, host, "Host")
        managers.get_shelf(host).place(0, 0, 149, host)
        doc = islands.export_island(host)
    island = doc["island_id"]
    monkeypatch.setattr(island_peers, "SAVE_DIR", tmp_path / "links")
    monkeypatch.setattr(native_islands, "resident", lambda: guest)
    with active(tmp_path / "guest") as db:
        create(db, guest, "Visitor")
        managers.get_chest(guest).add_item(150, 1)
        islands.import_island(guest, doc)
        with island_peers.database() as conn:
            conn.execute(
                "INSERT INTO links(id,secret,card,island,address) VALUES(?,?,?,?,?)",
                ("fixture", "x", guest, island, "127.0.0.1"),
            )
        actions.receive(guest, island, [])
        client = create_app().test_client()
        base = "/islands/" + island
        response = client.get(base + "/profile")
        assert response.status_code == 200 and b'name="payment"' in response.data
        form = {"kind": "trade", "version": doc["version"], "slot": 0, "payment": 150}
        assert client.post(base + "/interact", data=form).status_code == 403
        with client.session_transaction() as session:
            form["csrf"] = session["island_csrf"]
        panel = client.get(base + "/profile?in_room=1")
        assert b'name="in_room" value="1"' in panel.data and b'class="mast"' not in panel.data
        assert client.post(base + "/interact", data=form).status_code == 303
        assert len(actions.pending(guest, island)) == 1
        response = client.post(base + "/interact", data={**form, "in_room": "1"}, follow_redirects=True)
        assert response.status_code == 200 and response.request.args.get("in_room") == "1"
        assert b'role="status"' in response.data and b'class="mast"' not in response.data
        assert len(actions.pending(guest, island)) == 1
