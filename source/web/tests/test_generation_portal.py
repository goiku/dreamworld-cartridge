import base64
import hashlib
import struct
from types import SimpleNamespace

from flask import Flask

from api import generations
from api.server import create_app
from game_sync_server.entralinked.model.save_file import _crypt_array
from game_sync_server.entralinked.network.http import gts_handler
from game_sync_server.entralinked.network.http.dls_handler import DlsHandler
from game_sync_server.entralinked.utility.db_manager import DBManager
from game_sync_server.entralinked.utility.url_encoded_form import encode_form
from utils import gen4_events, gen4_gifts


def test_generation_links_and_compatible_gifts(monkeypatch):
    client = create_app().test_client()
    for locale, t in generations._labels.items():
        monkeypatch.setattr(generations, "LANG", locale)
        home = client.get("/?from=bookmark").get_data(as_text=True)
        assert 'href="/gen4/"' in home and 'href="/gen5/"' in home and t["choose"] in home
        assert "dw-player-help" not in home and "_ruffle" not in home
        for code in generations.GAME_CODES:
            page = client.get("/gen4/", query_string={"game":code, "language":"ja"}).get_data(as_text=True)
            count = len(gen4_events.selection(code+"J"))
            assert t["gift"] in page and generations.SHARED_UI[locale]["results"].format(count=count) in page
            assert count > 24 and page.count('class="number"') == generations.PAGE_SIZE
    assert client.get("/gen5/").location == "/index.html"
    assert b"_ruffle" in client.get("/index.html").data
    assert client.get("/languages/en/?page=/gen4/").location.endswith(":8080/gen4/")
    assert client.get("/customize/preview/C008").status_code == client.get("/customize/preview/C014").status_code == 200


def test_native_gift_list_isolated_by_session_game_and_owner(tmp_path, monkeypatch):
    store = DBManager(tmp_path / "gifts.db")
    monkeypatch.setattr(gen4_gifts, "db", store)
    monkeypatch.setattr(gen4_gifts, "_payload", lambda _: b"a" * 936)
    owners = {"a1":"one", "a2":"one", "b":"two"}
    users = SimpleNamespace(get_service_session=lambda token, service:
                            SimpleNamespace(user=SimpleNamespace(id=owners[token])) if token in owners else None)
    app = Flask(__name__)
    app.register_blueprint(DlsHandler(SimpleNamespace(dlc_list=None, user_manager=users)).blueprint())
    client = app.test_client()

    def download(action, token="a1", game="CPUJ", **extra):
        return client.post("/download", data=encode_form(dict(action=action, token=token, gamecd=game, **extra)))

    assert download("count",token="other").status_code == 401
    assert download("count").data == b"1"
    first = download("list").data
    file = first.split(b"\t")[0].decode()
    assert first.endswith(b"\t\t\t\t\t936\r\n") and download("list", offset="1").data == b"\r\n"
    assert download("contents",game="IPKJ",contents=file).status_code == 400
    for _ in range(2):
        assert download("contents",contents=file).data == b"a"*936
        assert download("list").data == first
    assert download("list","a2").data != first
    assert download("list","b").data == first
    store.close()


def _gen4_party(species, wanted):
    record = bytearray(292)
    core = bytearray(128)
    struct.pack_into("<H", core, 0, species)
    checksum = sum(struct.unpack("<64H", core)) & 65535
    struct.pack_into("<H", record, 6, checksum)
    _crypt_array(core, checksum)
    record[8:136] = core
    tail = bytearray(100)
    tail[4] = 10
    _crypt_array(tail, 0)
    record[136:236] = tail
    struct.pack_into("<HBBHBBB", record, 236, species, 1, 10, wanted, 3, 0, 0)
    record[0x122:0x124] = bytes((12, 1))
    return bytes(record)


def test_gen4_native_gts_trade_retries_and_separate_store(tmp_path, monkeypatch):
    monkeypatch.setattr(gts_handler, "SAVE_DIR", tmp_path)
    store5 = DBManager(tmp_path / "gen5.db")
    monkeypatch.setattr(gts_handler, "db", store5)
    users = SimpleNamespace(gts_peer_profile=lambda ip: {"127.0.0.2":2,"127.0.0.3":3}.get(ip))
    service = gts_handler.GtsHandler(SimpleNamespace(user_manager=users))
    app = Flask(__name__)
    app.register_blueprint(service.blueprint())
    client = app.test_client()

    def call(pid, action, data=b""):
        path = f"/pokemondpds/worldexchange/{action}.asp"
        source = {"REMOTE_ADDR": f"127.0.0.{pid}"}
        token = client.get(path, query_string={"pid":pid}, environ_overrides=source).data
        assert len(token) == 32
        packet = struct.pack("<I", pid) + data
        total = sum(packet)
        seed = (total & 65535) * 65537
        wire = bytearray(struct.pack(">I", total ^ 0x4a3b2c1d))
        for byte in packet:
            seed = (69 * seed + 4369) % (2**31)
            wire.append(byte ^ (seed >> 16 & 255))
        query = {"pid":pid,"hash":hashlib.sha1(b"sAdeqWo3voLeC5r16DYv"+token).hexdigest(),
                 "data":base64.urlsafe_b64encode(wire).decode()}
        result = client.get(path, query_string=query, environ_overrides=source)
        assert result.status_code == 200
        return result.data

    a, b = _gen4_party(25, 133), _gen4_party(133, 25)
    ok = b"\1\0"
    assert call(2, "info") == ok and call(2, "result") == b"\5\0"
    assert call(2, "post", a) == ok
    assert call(2, "post_finish", bytes(8)) == ok
    assert call(2, "result") == b"\4\0"
    assert service.station.dispatch("result", 2, b"") == b"\5\0"
    listing = call(3, "search", struct.pack("<H5B", 25,3,0,0,0,7))
    assert len(listing) == 292 and listing[:236] == a[:236]
    for _ in range(2):
        assert call(3, "exchange", b+struct.pack("<I", 2)) == listing
    for _ in range(2):
        assert call(3, "exchange_finish", bytes(8)) == ok
    arrived = call(2, "result")
    assert arrived[:236] == b[:236] and arrived[0x121] == 1
    assert call(2, "delete") == call(2, "delete") == ok
    assert call(2, "result") == b"\5\0"
    store5.close()
    service.gen4.db.close()
