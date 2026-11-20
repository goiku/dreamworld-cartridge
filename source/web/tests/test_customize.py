"""The wallpaper picker must work without the missing present.swf."""
import re

from api import pgl_pals, pgl_present
from api.server import create_app
from game_sync_server.entralinked.model.dlc.dlc import DlcList
from tests.test_visit_storage import Server
from utils import save_data


def test_movie_skin_selection(tmp_path, monkeypatch):
    server = Server(tmp_path / "skin.sqlite")
    try:
        card = server.resident(7)
        monkeypatch.setattr(pgl_pals, "accounts", server.accounts)
        monkeypatch.setattr(save_data, "db", server.db)
        client = create_app().test_client()
        url = "/customize/"
        page = client.get(url)
        assert page.status_code == 200 and b"present.swf" not in page.data
        assert b'name="choice"' not in page.data
        assert client.post(url, data={"choice": "C014"}).status_code == 403
        with client.session_transaction() as state:
            state.update(username="Trainer", gscd=card)
        page = client.get(url)
        assert b'value="C013"' in page.data and b'value="C014"' in page.data
        assert b'value="C014-2"' not in page.data
        assert client.get("/customize/index.html").location == url
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.get_data(as_text=True))[1]
        post = dict(card=card, csrf=csrf, choice="C014")
        assert client.post(url, data=dict(post, card="stale")).status_code == 403
        assert client.post(url, data=dict(post, csrf="stale")).status_code == 403
        assert client.post(url, data=dict(post, choice="C014-2")).status_code == 400
        initial = server.db.read(card, "game_sync")
        for skin, idx in (("C013", 13), ("C014", 14)):
            response = client.post(url, data=dict(post, choice=skin), follow_redirects=True)
            assert response.status_code == 200 and f'value="{skin}" checked'.encode() in response.data
            sync = server.db.read(card, "game_sync")
            assert DlcList().get_dlc_index("CGEAR", sync["cgear_skin"]) == idx
            assert dict(sync, cgear_skin=initial.get("cgear_skin")) == initial
            if pgl_present._preview(skin):
                preview = client.get("/customize/preview/" + skin)
                assert preview.data.startswith(b"\x89PNG")
        server.db.update(card, "player_data", lambda data: data["member"].update(rom_id=23))
        assert b'value="C014-2"' in client.get(url).data
        assert client.post(url, data=post).status_code == 400
        assert client.get("/customize/?kind=zukan").status_code == 200
        assert client.get("/customize/?kind=musical").status_code == 200
        assert client.post(url, data=dict(post, choice="none")).status_code == 303
        assert server.db.read(card, "game_sync")["cgear_skin"] is None
    finally:
        server.close()
