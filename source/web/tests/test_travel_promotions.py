import copy
import secrets
from unittest.mock import patch

import pytest

from tests import test_visit_storage
from utils import distributions as gifts
from utils import visit_storage as visits

paired = test_visit_storage.servers


def test_paired_claim_round_trip_and_retry(paired):
    home, host = paired
    code = home.resident(17)
    with home.active(), home.db.transaction() as conn:
        gifts.schema(conn)
        conn.execute("INSERT INTO distribution_cartridges VALUES(?,?,?,?,?)", (code, "home-only-identity", 20, 1, "{}"))
        original = visits.export_local("Trainer", code)
    token = secrets.token_urlsafe(32)
    gift = next(g for g in gifts.catalog().values() if g.language == "JPN" and g.number and gifts.compatible(g, 20, 1))
    with host.active(), patch.object(gifts, "db", host.db):
        visits.redeem(visits.create_invite(), original["snapshot"], token)
        assert gifts.queue(code, gift, 20, 1) == "queued"
        assert gifts.queue(code, gift, 20, 1) == "queued"
        new = visits.read_snapshot(token)
        with host.db.transaction() as conn:
            assert gifts.state(conn, code)[0]["wfc"] is None
            assert conn.execute("SELECT COUNT(*) FROM distribution_orders").fetchone()[0] == 1
    with home.active():
        assert visits.apply_local("Trainer", code, original["revision"], new["snapshot"]) == new
        assert visits.apply_local("Trainer", code, original["revision"], new["snapshot"]) == new
        modified = copy.deepcopy(new["snapshot"])
        modified["save"]["player_data"]["travel_gifts"]["orders"][0][1] = "sent"
        with pytest.raises(visits.VisitInvalid):
            visits.apply_local("Trainer", code, new["revision"], modified)
        del modified["save"]["player_data"]["travel_gifts"]
        with pytest.raises(visits.VisitConflict):
            visits.apply_local("Trainer", code, new["revision"], modified)
        assert visits.export_local("Trainer", code) == new
        with home.db.transaction() as conn:
            assert gifts.state(conn, code)[0]["wfc"] == "home-only-identity"
