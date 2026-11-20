"""Two temporary servers with colliding account names and member IDs."""
import copy
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from unittest.mock import patch

import pytest
from werkzeug.security import check_password_hash

from game_sync_server.entralinked.model.player.player import Player, new_player_data
from game_sync_server.entralinked.utility.db_manager import DBManager
from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
from utils import visit_storage as visits
from utils.account_manager import AccountManager


class Server:
    def __init__(self, path):
        self.db = DBManager(path)
        self.accounts = AccountManager(path)

    @contextmanager
    def active(self):
        with patch.object(visits, "db", self.db), patch.object(visits, "accounts", self.accounts):
            yield

    def resident(self, gsid):
        code = gsid_to_gscd(gsid)
        username = "Trainer"
        self.accounts.create_account(username, "private-login", "local@example.invalid", 1, 2,
                                     "everyone", "friends", "private-activation")
        self.accounts.activate_account("private-activation")
        self.accounts.link_gscd(username, code)
        self.db.write_gscd(code)
        profile = new_player_data(self.db.next_id("member_id")[0], self.db.next_id("my_interior_id", 2))
        player = Player(code, rom_id=20, langcode=1)
        profile["member"].update(player.member_fields(), pgl_name=username)
        profile["token"] = "private-session"
        sync = dict(player.game_sync_data(), upload_digest="private-upload", last_wake_id=42)
        self.db.write_full_state(code, profile, sync, None)
        return code

    def close(self):
        self.db.close()
        self.accounts.close()


@pytest.fixture
def servers(tmp_path):
    home, host = Server(tmp_path / "home.sqlite"), Server(tmp_path / "host.sqlite")
    try:
        yield home, host
    finally:
        home.close()
        host.close()


def test_roundtrip_and_retry(servers):
    home, host = servers
    code = home.resident(1)
    resident = host.resident(2)
    with home.active():
        home.db.update(code, "share_data", lambda data: data["share_list"].append({
            "material_id": 7, "old_member_savedata_id": 1, "item_id": 149, "x": 0, "y": 0}))
        original = visits.export_local("Trainer", code)
        assert visits.snapshot_revision(original["snapshot"]) == original["revision"]
        wire = json.dumps(original)
        assert all(word not in wire for word in ("local@example", "private-", "last_wake_id", "upload_digest"))
        with pytest.raises(visits.VisitAuthError):
            visits.export_local("Other", code)
    with host.active():
        before = visits.export_local("Trainer", resident)
        invite = visits.create_invite()
        token = secrets.token_urlsafe(32)
        registered = visits.redeem(invite, original["snapshot"], token)
        assert registered["revision"] == original["revision"]
        assert visits.redeem(invite, original["snapshot"], token) == registered
        with pytest.raises(visits.VisitAuthError):
            visits.redeem(invite, original["snapshot"], secrets.token_urlsafe(32))
        ticket = visits.create_ticket(token)
        alias, selected, display_name = visits.consume_ticket(ticket)
        assert alias.startswith(visits.GUEST_PREFIX) and selected == code and display_name == "Trainer"
        with pytest.raises(visits.VisitAuthError):
            visits.consume_ticket(ticket)
        guest_account = host.accounts.get_account_by_username(alias)
        assert not guest_account["activated"] and not guest_account["email"] and not guest_account["activation_token"]
        assert not check_password_hash(guest_account["password_hash"], "private-login")
        assert not host.accounts.link_gscd(alias, gsid_to_gscd(19))
        with pytest.raises(visits.VisitAuthError):
            visits.export_local(alias, code)
        member_id = host.db.read(code, "player_data")["member"]["member_savedata_id"]
        assert member_id != host.db.read(resident, "player_data")["member"]["member_savedata_id"]
        assert host.db.read(code, "share_data")["share_list"][0]["old_member_savedata_id"] == member_id
        host.db.update(code, "game_sync", lambda sync: sync["encounters"].append(
            {"species": 173, "form": 0, "move": 1, "gender": 0, "animation": 0}))
        host.db.update(code, "player_data", lambda state: state.update(dream_board=[{"id": 3, "selected": True}]))
        edited = visits.read_snapshot(token)
        assert edited["revision"] != original["revision"]
        assert visits.export_local("Trainer", resident) == before
        with pytest.raises(visits.VisitConflict):
            visits.replace_snapshot(token, original["revision"], original["snapshot"])
        with pytest.raises(visits.VisitConflict):
            visits.replace_snapshot(token, edited["revision"], before["snapshot"])
    with home.active():
        assert visits.apply_local("Trainer", code, original["revision"], edited["snapshot"]) == edited
        assert visits.apply_local("Trainer", code, original["revision"], edited["snapshot"]) == edited
        assert visits.export_local("Trainer", code) == edited
        assert home.db.read(code, "game_sync")["last_wake_id"] == 42
        assert home.db.read(code, "game_sync")["encounters"][0]["species"] == 173
        assert home.db.read(code, "player_data")["token"] == "private-session"
        assert home.db.read(code, "player_data")["member"]["member_savedata_id"] == 1
        assert home.db.read(code, "share_data")["share_list"][0]["old_member_savedata_id"] == 1
        assert home.db.next_id("dream_encounter_id")[0] == 4


def test_atomic_collisions_and_wake(servers):
    home, host = servers
    code = home.resident(5)
    duplicate = host.resident(5)
    assert duplicate == code
    with home.active():
        original = visits.export_local("Trainer", code)
        other = visits.export_local("Trainer", home.resident(6))
    with host.active():
        before_collision = visits.export_local("Trainer", duplicate)
        invite, token = visits.create_invite(), secrets.token_urlsafe(32)
        with pytest.raises(visits.VisitConflict):
            visits.redeem(invite, original["snapshot"], token)
        assert visits.export_local("Trainer", code) == before_collision
        invalid = copy.deepcopy(other["snapshot"])
        invalid["save"]["share_data"]["share_list"] = [{"material_id": -1}]
        with pytest.raises(visits.VisitInvalid):
            visits.redeem(invite, invalid, token)
        assert host.accounts.count_accounts() == 1
        assert not host.db.gscd_exists(other["snapshot"]["gscd"])
        assert visits.redeem(invite, other["snapshot"], token)["revision"] == other["revision"]
    with home.active():
        home.db.update(code, "game_sync", lambda state: state.update(pending_wake={"payload": "private"}))
        with pytest.raises(visits.VisitConflict):
            visits.export_local("Trainer", code)
        with pytest.raises(visits.VisitConflict):
            visits.apply_local("Trainer", code, original["revision"], original["snapshot"])
        assert home.db.read(code, "game_sync")["pending_wake"] == {"payload": "private"}


def test_simultaneous_cas_and_ticket_expiry(servers):
    home, host = servers
    with home.active():
        code = home.resident(9)
        original = visits.export_local("Trainer", code)
    with host.active():
        with patch.object(visits.time, "time", return_value=100):
            expired = visits.create_invite()
        token = secrets.token_urlsafe(32)
        with pytest.raises(visits.VisitAuthError):
            visits.redeem(expired, original["snapshot"], token)
        visits.redeem(visits.create_invite(), original["snapshot"], token)
        with patch.object(visits.time, "time", return_value=100):
            expired_ticket = visits.create_ticket(token)
        with pytest.raises(visits.VisitAuthError):
            visits.consume_ticket(expired_ticket)
        barrier = Barrier(2)

        def edit(points):
            snapshot = copy.deepcopy(original["snapshot"])
            snapshot["save"]["player_data"]["member"]["point"] = points
            barrier.wait(timeout=5)
            try:
                return visits.replace_snapshot(token, original["revision"], snapshot)["revision"]
            except visits.VisitConflict:
                return None
            finally:
                host.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(edit, (100, 200)))
        assert results.count(None) == 1
        assert visits.read_snapshot(token)["revision"] in results
