"""Exercise the web, Game Sync and Mystery Gift entrances with disposable game data."""
import binascii
import hashlib
import io
import struct
from types import SimpleNamespace

import pytest

from api.server import create_app as create_web
from game_sync_server.entralinked.configuration import Configuration
from game_sync_server.entralinked.context import Context
from game_sync_server.entralinked.model.dlc.dlc import DlcList
from game_sync_server.entralinked.model.player.player_manager import PlayerManager
from game_sync_server.entralinked.model.save_file import _crypt_array
from game_sync_server.entralinked.model.user.user_manager import UserManager
from game_sync_server.entralinked.network.http.http_server import create_app as create_game
from game_sync_server.entralinked.network.http.pgl_handler import PASSWORD, USERNAME
from game_sync_server.entralinked.utility.db_manager import db
from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
from game_sync_server.entralinked.utility.url_encoded_form import decode_form, encode_form
from utils import distributions as gifts
from utils.account_manager import accounts


def cartridge(gsid, rom, lang, records=None, removed=()):
    raw = bytearray(0x80000)
    raw[0x19404:0x1940a] = "QA".encode("utf-16-le") + b"\xff\xff"
    struct.pack_into("<I", raw, 0x19418, gsid)
    raw[0x1941e:0x19420] = bytes((lang, rom))
    raw[0x1d4a6] = 0x7f
    stored = bytearray(128)
    struct.pack_into("<H", stored, 0, 25)
    checksum = sum(struct.unpack("<64H", stored)) & 0xffff
    _crypt_array(stored, checksum)
    struct.pack_into("<H", raw, 0x1d30e, checksum)
    raw[0x1d310:0x1d390] = stored
    if records is not None:
        album = bytearray(0xa90)
        for number in (*records, *removed):
            album[number//8] |= 1 << (number % 8)
        for i, (number, used) in enumerate(records.items()):
            pos = 0x100 + i*204
            struct.pack_into("<H", album, pos+0xb0, number)
            album[pos+0xb3:pos+0xb5] = bytes((1, 2 if used else 0))
        _crypt_array(album, 12345)
        block = album + struct.pack("<I", 12345)
        raw[0x1c800:0x1d294] = block
        struct.pack_into("<H", raw, 0x1d296, binascii.crc_hqx(block, 0xffff))
    return bytes(raw)


@pytest.fixture
def clients(tmp_path, monkeypatch):
    for store in (accounts, db):
        store.close()
        monkeypatch.setattr(store, "_db_path", tmp_path / "test.db")
        monkeypatch.setattr(store, "_created", False)
    monkeypatch.setattr("api.server.get_secret_key", lambda: "distribution-test")
    manifest = tmp_path / "dlc.json"
    manifest.write_text("{}")
    context = Context(Configuration(), UserManager(), PlayerManager(), DlcList(tmp_path, manifest))
    try:
        yield create_web().test_client(), create_game(context).test_client()
    finally:
        accounts.close()
        db.close()


def test_album_evidence_and_checksum():
    raw = cartridge(11, 23, 1, {12: False, 50: True}, [1990])
    assert gifts.cartridge_album(raw) == {"12":"at_center", "50":"collected", "1990":"received"}
    assert gifts.cartridge_album(raw[:0x1d000]) is None
    broken = bytearray(raw)
    broken[0x1c800] ^= 1
    assert gifts.cartridge_album(broken) is None
    assert gifts.cartridge_album(cartridge(11, 23, 1)) is None


@pytest.mark.parametrize("rom", [20, 21, 22, 23])
def test_wake_capacity_and_version(clients, rom):
    code = gsid_to_gscd(55)
    eligible = [g for g in gifts.catalog().values() if g.species and gifts.compatible(g, rom, 1)]
    first = eligible[0]
    second = next(g for g in eligible if g.group != first.group)
    for gift in (first, second):
        assert gifts.queue(code, gift, rom, 1) == "queued"
    player = SimpleNamespace(gscd=code, rom_id=rom, langcode=1, encounters=[None]*9)
    with db.transaction() as conn:
        assert gifts.add_to_wake(conn, player, 10) == [first.key]
        assert len(player.encounters) == 10 and player.encounters[9].species == first.species
        gifts.confirm_wake(conn,code,[first.key])
        player.encounters.clear()
        assert gifts.add_to_wake(conn, player, 10) == [second.key]


def test_shared_card_number_and_missing_archive(clients, monkeypatch):
    code = gsid_to_gscd(89)
    signatures = {}
    evidence = gifts.cartridge_album(cartridge(89,21,1,{9:False}), signatures)
    sig = next(iter(signatures))
    one = gifts.Gift("w-one", "card-9", "First", 48, "JPN", number=9, signature=sig)
    two = gifts.Gift("w-two", "card-9", "Second", 48, "JPN", number=9, signature="a"*64)
    monkeypatch.setattr(gifts, "catalog", lambda:{one.key:one,two.key:two})
    gifts.variant_signatures.cache_clear()
    try:
        with db.transaction() as conn:
            gifts.schema(conn)
            conn.execute("INSERT INTO distribution_cartridges VALUES(?,?,21,1,NULL)", (code,"test"))
        def missing(*args, **kwargs):
            raise OSError("offline")
        monkeypatch.setattr(gifts, "urlopen", missing)
        with pytest.raises(OSError):
            gifts.queue(code,one,21,1)
        with db.transaction() as conn:
            assert not gifts.state(conn,code)[1]
            gifts.merge_album(conn,code,evidence,signatures)
            album = gifts.state(conn,code)[2]
            assert album[one.key] == "at_center" and two.key not in album and album["9"] == "at_center"
            gifts.merge_album(conn,code,{"9":"received"},{})
            assert gifts.state(conn,code)[2][one.key] == "received"
    finally:
        gifts.variant_signatures.cache_clear()


def test_authenticated_distribution(clients, monkeypatch):
    web, ds = clients
    gsid, rom, lang = 34567, 21, 1
    code = gsid_to_gscd(gsid)

    def service(user, svc):
        def nas(action, **extra):
            response = ds.post("/ac", data=encode_form(dict(action=action, userid=user, passwd="local-test", **extra)))
            return decode_form(response.get_data(as_text=True))
        nas("acctcreate")
        return nas("SVCLOC", svc=svc)["servicetoken"]

    own = "8" * 13
    game_token = service(own, "0000")
    dl_token = service(own, "9000")
    stranger = service("7" * 13, "9000")

    def sync(action, method="GET", raw=b""):
        response = ds.open("/dsio/gw", method=method, auth=(USERNAME, PASSWORD), data=raw,
                           query_string=dict(p=action, gsid=gsid, rom=rom, langcode=lang, tok=game_token))
        assert response.status_code == 200 and response.data[:128] == bytes(128)
        return response.data[128:]

    sync("account.create.upload", "POST")
    sync("savedata.upload", "POST", cartridge(gsid, rom, lang, {}))
    accounts.link_gscd("TestResident", code)
    with web.session_transaction() as s:
        s.update(username="TestResident", gscd=code)
    assert web.get("/campaign/").status_code == 200
    with web.session_transaction() as s:
        fields = dict(csrf=s["gift_csrf"], card=code)
    dream = next(g for g in gifts.catalog().values() if g.species == 134 and gifts.compatible(g, rom, lang))
    def claim(g, data=fields):
        return web.post("/campaign/claim/" + g.key, data=data)
    assert claim(dream, {}).status_code == 403
    for _ in range(2):
        assert claim(dream).status_code == 303
    alternative = next(g for g in gifts.catalog().values() if g.species == 135)
    claim(alternative)
    # Existing Friend Board reward leads the wake packet.
    db.update(code, "game_sync", lambda s:s.update(encounters=[dict(species=173,move=0,gender=1,form=0,animation=0)]))
    packet = sync("savedata.download")
    assert len(packet) == 284 and struct.unpack_from("<H",packet,4)[0] == 173
    assert struct.unpack_from("<H",packet,12)[0] == 134 and packet[20:84] == bytes(64)
    assert sync("savedata.download") == packet
    with db.transaction() as conn:
        assert gifts.state(conn, code)[1][dream.group]["status"] == "queued"
    sync("savedata.download.finish", "POST")
    sync("savedata.download.finish", "POST")
    with db.transaction() as conn:
        assert gifts.state(conn, code)[1][dream.group]["status"] == "delivered"

    # A tiny synthetic PGF exercises the same hash check and envelope builder as the archive.
    raw = bytearray(204)
    struct.pack_into("<H",raw,0xb0,41)
    raw[0xb3:0xb5] = bytes((1, 2))
    raw[0x60:0x66] = "QA".encode("utf-16-le") + b"\xff\xff"
    digest = hashlib.sha1(b"blob 204\0" + raw).hexdigest()
    wonder = gifts.Gift("w-test", "card-41","Fixture",48,"JPN","test.pgf",digest,41)
    catalog = {**gifts.catalog(), wonder.key:wonder}
    monkeypatch.setattr(gifts,"catalog",lambda:catalog)
    monkeypatch.setattr(gifts,"urlopen",lambda *a,**kw:io.BytesIO(raw))
    for _ in range(2):
        assert claim(wonder).status_code == 303
    def dls(action, token=dl_token, **params):
        return ds.post("/download",data=encode_form(dict(action=action,token=token,gamecd="IRAO",**params)))
    params = dict(attr1="MYSTERY_J",rhgamecd="IRBJ")
    assert dls("count", **params).data == b"1"
    assert dls("count", stranger, **params).data == b"0"
    assert dls("count", attr1="MYSTERY_J", rhgamecd="IRAJ").data == b"0"
    assert dls("count", "invalid", **params).status_code == 401
    listing = dls("list", **params).data.decode()
    name = listing.split("\t")[0]
    assert listing.endswith("\tMYSTERY_J\t300000\t\t720\r\n")
    payload = dls("contents",contents=name).data
    assert len(payload) == 720 and dls("contents",contents=name).data == payload
    assert dls("contents",stranger,contents=name).status_code == 404
    assert payload[0xb4] == 0 and payload[-5] == 1 and payload[0xce] == 48
    assert binascii.crc_hqx(payload[:-2],0xffff) == int.from_bytes(payload[-2:],"little")
    with db.transaction() as conn:
        assert gifts.state(conn, code)[1][wonder.group]["status"] == "sent"
    assert dls("count", service(own, "9000"), **params).data == b"0"
    sync("savedata.upload", "POST", cartridge(gsid,rom,lang,{41:False}))
    assert dls("count", **params).data == b"0"
    with db.transaction() as conn:
        _, orders, album = gifts.state(conn,code)
        assert orders[wonder.group]["status"] == "delivered" and album["41"] == "at_center"
    # An uploaded backup cannot confirm another cartridge's gifts.
    def scan(owner):
        raw = cartridge(owner,rom,lang,{41:True})
        return web.post("/campaign/album", data={**fields,"save":(io.BytesIO(raw),"test.sav")})
    assert scan(gsid+1).status_code == 303
    with db.transaction() as conn:
        assert gifts.state(conn,code)[2]["41"] == "at_center"
    assert scan(gsid).status_code == 303
    with db.transaction() as conn:
        assert gifts.state(conn,code)[2]["41"] == "collected"
    with web.session_transaction() as s:
        s["visit_guest"] = True
    assert claim(wonder).status_code == 403
