"""A Dream World visit may already be over while the DS still has to download its skin."""
import re
from unittest.mock import patch

from api import pgl_pals
from api.server import create_app
from tests.test_visit_storage import Server
from utils import save_data
from utils.constants import PlayerStatus


def test_select_skin_after_web_wake(tmp_path, monkeypatch):
    server = Server(tmp_path / "wake.sqlite")
    try:
        card = server.resident(14)
        monkeypatch.setattr(pgl_pals, "accounts", server.accounts)
        monkeypatch.setattr(save_data, "db", server.db)
        client = create_app().test_client()
        with client.session_transaction() as state:
            state.update(username="Trainer", gscd=card)
        server.db.update(card, "player_data", lambda data: data["member"].update(
            sleeping_flag=1, play_status=PlayerStatus.DREAMING))
        with patch("api.native_islands.start_browser"):
            assert b'id="flashcontent"' in client.get("/pdw/").data
            assert client.get("/api/?p=pdw.home.pdw_end").status_code == 200
            for path in ("/pdw/", "/pdw/index.html"):
                result = client.get(path)
                assert result.cache_control.no_store
                assert b'id="dw-wake-title"' in result.data and b'id="flashcontent"' not in result.data
                assert b'/customize/?kind=cgear' in result.data
                assert b'/player-guide/#distributions' in result.data
            guide = client.get("/player-guide/").data
            assert b'id="distributions"' in guide
            assert b'/campaign/?kind=dream' in guide and b'/campaign/?kind=wonder' in guide
            response = client.get("/customize/?kind=cgear")
            csrf = re.search(r'name="csrf" value="([^"]+)"', response.get_data(as_text=True))[1]
            assert client.post("/customize/", data={"card": card, "csrf": csrf, "choice": "C014"}).status_code == 303
            sync = server.db.read(card, "game_sync")
            assert sync["cgear_skin"] == "C014_reshiram_0_j.bin" and not sync.get("pending_wake")
            assert server.db.read(card, "player_data")["member"]["play_status"] == PlayerStatus.WAKE_READY
            assert b'id="flashcontent"' in create_app().test_client().get("/pdw/").data
    finally:
        server.close()
