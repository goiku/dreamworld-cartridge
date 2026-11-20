"""Exercise the web, Game Sync and Mystery Gift entrances with disposable game data."""
import binascii
import hashlib
import io
import re
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


def test_bulk_wonder_cards_append_across_pages_and_retry(clients, monkeypatch):
    web, _ = clients
    code = gsid_to_gscd(78)
    PlayerManager().register_player(code, 21, 1)
    accounts.link_gscd("BulkTrainer", code)
    with web.session_transaction() as session:
        session.update(username="BulkTrainer", gscd=code)
    cards = [gifts.Gift(f"w-{i}", f"card-{i}", f"Gift {i}", 32, "JPN", number=i) for i in range(1, 31)]
    extra = [gifts.Gift("alt", "card-3", "Third alternative", 32, "JPN", number=3),
             gifts.Gift("unknown", "unknown", "Same-number receipt", 32, "JPN", number=1, independent=True),
             gifts.Gift("other", "card-30", "Wrong edition", 128, "JPN", number=30),
             gifts.Gift("repeat-a", "repeat-a", "Independent A", 32, "JPN", number=40, independent=True),
             gifts.Gift("repeat-b", "repeat-b", "Independent B", 32, "JPN", number=40, independent=True)]
    monkeypatch.setattr(gifts, "catalog", lambda: {g.key:g for g in cards + extra})
    monkeypatch.setattr(gifts, "variant_counts", gifts.variant_counts.__wrapped__)
    monkeypatch.setattr(gifts.japanese_card_archive, "ensure_installed", lambda: None)
    calls = []

    def payload(gift, lang):
        calls.append(gift.key)
        if gift.key == "w-4" and calls.count("w-4") == 1:
            raise OSError("temporarily unavailable")
        return gift.key.encode()

    monkeypatch.setattr(gifts, "card_binary", payload)
    with db.transaction() as conn:
        gifts.schema(conn)
        conn.execute("INSERT INTO distribution_cartridges VALUES(?,?,21,1,?)", (code, "bulk-wfc", '{"1":"collected"}'))
        conn.execute("INSERT INTO distribution_orders VALUES(?,?,?,'queued',?)", (code,"card-2","w-2",b"existing"))
        conn.execute("INSERT INTO distribution_next VALUES(?,?)", (code, "w-2"))
    path = "/campaign/claim-unclaimed"
    page = web.get("/campaign/?kind=wonder&q=Gift+30").text
    assert path in page and path not in web.get("/campaign/?kind=dream").text
    with web.session_transaction() as session:
        form = dict(csrf=session["gift_csrf"], card=code)
    assert web.post(path, data={**form, "card":"another-card"}).status_code == 403
    assert web.post(path, data={**form, "csrf":""}).status_code == 403
    for added, failed in [(28, 1), (1, 0), (0, 0)]:
        out = web.post(path, data={**form, "q":"Gift 30", "page":2})
        assert out.status_code == 303 and "filter=waiting" in out.location
        with web.session_transaction() as session:
            assert session["gift_bulk_totals"] == dict(added=added, failed=failed)
        assert web.get(out.location).status_code == 200
    with db.transaction() as conn:
        ident, orders, album = gifts.state(conn, code)
        expected_new = {g.key for g in cards[3:]} | {"repeat-a", "repeat-b"}
        assert {o["gift"] for o in orders.values()} == expected_new | {"w-2"}
        assert {o["status"] for o in orders.values()} == {"queued"}
        assert album == {"1":"collected"}
        assert conn.execute("SELECT gift FROM distribution_next WHERE card=?", (code,)).fetchone()[0] == "w-2"
        assert conn.execute("SELECT payload FROM distribution_orders WHERE card=? AND gift='w-2'", (code,)).fetchone()[0] == b"existing"
    assert set(calls) == expected_new and len(calls) == len(expected_new) + 1
    # Both alternatives still have their individual forms even after bulk claims and retries.
    remaining = web.get("/campaign/?kind=wonder&filter=unclaimed&q=3").text
    assert 'action="/campaign/claim/w-3"' in remaining and 'action="/campaign/claim/alt"' in remaining
    assert web.post("/campaign/claim/alt", data=form).status_code == 303
    assert web.post(path, data=form).status_code == 303
    with db.transaction() as conn:
        assert gifts.state(conn, code)[1]["card-3"]["gift"] == "alt"


def test_bulk_respects_identity_and_new_receipts_while_preparing(clients, monkeypatch):
    code = gsid_to_gscd(79)
    gift = gifts.Gift("qa-card", "card-20", "Test card", 32, "ENG", number=20)
    monkeypatch.setattr(gifts, "catalog", lambda: {gift.key:gift})
    monkeypatch.setattr(gifts, "variant_counts", gifts.variant_counts.__wrapped__)
    with db.transaction() as conn:
        gifts.schema(conn)
        conn.execute("INSERT INTO distribution_cartridges VALUES(?,?,21,2,NULL)", (code,"shared-wfc"))
    assert gifts.queue_unclaimed_cards(code, 21, 2) == ("unknown_help", 0, 0)
    with db.transaction() as conn:
        conn.execute("UPDATE distribution_cartridges SET album='{}' WHERE card=?", (code,))
        conn.execute("INSERT INTO distribution_cartridges VALUES('other','shared-wfc',21,2,'{}')")
    assert gifts.queue_unclaimed_cards(code, 21, 2) == ("ambiguous", 0, 0)
    with db.transaction() as conn:
        conn.execute("DELETE FROM distribution_cartridges WHERE card='other'")

    def receive_during_fetch(gift, lang):
        with db.transaction() as conn:
            gifts.merge_album(conn, code, {"20":"at_center"})
        return b"test"

    monkeypatch.setattr(gifts, "card_binary", receive_during_fetch)
    assert gifts.queue_unclaimed_cards(code, 21, 2) == ("bulk_result", 0, 0)
    with db.transaction() as conn:
        assert gifts.state(conn, code)[1:] == ({}, {"20":"at_center"})


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
        assert gifts.add_to_wake(conn, player, 10, 20) == [first.key]
        assert len(player.encounters) == 10 and player.encounters[9].species == first.species
        gifts.confirm_wake(conn,code,[first.key])
        player.encounters.clear()
        assert gifts.add_to_wake(conn, player, 10, 20) == [second.key]


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


def test_receiver_queue_matches_ds_order_and_frozen_wake(clients):
    web, _ = clients
    code = gsid_to_gscd(245)
    PlayerManager().register_player(code, 21, 1)
    accounts.link_gscd("QueueTrainer", code)
    page = "/campaign/queue/"
    wonder = [g for g in gifts.catalog().values() if g.number and gifts.compatible(g, 21, 1)]
    a, b = wonder[0], next(g for g in wonder if g.group != wonder[0].group)
    dreams = [g for g in gifts.catalog().values() if g.species and gifts.compatible(g, 21, 1)]
    first = dreams[0]
    second = next(g for g in dreams if g.group != first.group)
    with db.transaction() as conn:
        gifts.schema(conn)
        conn.execute("INSERT INTO distribution_cartridges VALUES(?,?,21,1,'{}')", (code, "queue-wfc"))
        for card in (a, b):
            conn.execute("INSERT INTO distribution_orders VALUES(?,?,?,'queued',?)",
                         (code, card.group, card.key, card.key.encode()))
        conn.execute("INSERT INTO distribution_orders VALUES('another','other','outside-queue','queued',x'01')")
    for gift in (first, second):
        assert gifts.queue(code, gift, 21, 1) == "queued"
    # Nine occupied encounter slots leave room for just one more partner.
    encounters = [dict(species=173,move=0,gender=1,form=0,animation=0)] * 9
    db.update(code, "game_sync", lambda state: state.update(encounters=encounters))
    assert 'data-gift=' not in web.get(page).text
    with web.session_transaction() as s:
        s.update(username="QueueTrainer", gscd=code)
    def entries(html, section):
        match = re.search(f'<section id="{section}">(.*?)</section>', html, re.S)
        return re.findall(r'data-gift="([^"]+)"', match[1]) if match else []

    initial = web.get(page)
    assert initial.status_code == 200 and initial.cache_control.private
    assert web.get(page, headers={"If-None-Match":initial.headers["ETag"]}).status_code == 304
    assert entries(initial.text,"wonder") == [a.key, b.key]
    assert entries(initial.text,"dream") == [first.key, second.key]
    assert "outside-queue" not in initial.text and db.read(code, "game_sync")["encounters"] == encounters
    with web.session_transaction() as s:
        fields = dict(card=code, csrf=s["gift_csrf"], next="1", from_queue="1")
    reordered = web.post("/campaign/claim/"+b.key, data=fields)
    assert reordered.status_code == 303 and reordered.location == page
    new = web.get(page, headers={"If-None-Match":initial.headers["ETag"]})
    assert new.status_code == 200 and entries(new.text,"wonder") == [b.key, a.key]
    f = dict(token="ds-session", rhgamecd="IRBJ", attr1="MYSTERY_J")
    listing, status = gifts.download("queue-wfc", dict(f, action="list"))
    name = listing.split("\t")[0]
    assert status == 200 and name == "DW"+b.digest[:12]+".bin"
    assert gifts.download("queue-wfc",dict(f, action="contents", contents=name)) == (b.key.encode(),200)
    assert gifts.download("queue-wfc",dict(f, action="contents", contents=name)) == (b.key.encode(),200)
    assert gifts.download("queue-wfc",dict(f, token="new", action="list"))[0].startswith("DW"+a.digest[:12])
    # After download starts the stored batch takes precedence over the current free slots.
    db.update(code, "game_sync", lambda state: state.update(pending_wake={"distribution_ids":[second.key]}))
    current = web.get(page).text
    assert entries(current,"wonder") == [a.key] and entries(current,"sent") == [b.key]
    assert entries(current,"dream") == [second.key, first.key]
    with db.transaction() as conn:
        gifts.confirm_wake(conn, code, [second.key])
        gifts.merge_album(conn, code, {str(b.number):"at_center"}, {b.signature:"at_center"})
    db.update(code, "game_sync", lambda state: state.pop("pending_wake"))
    done = web.get(page).text
    assert entries(done,"dream") == [first.key] and b.key not in entries(done,"sent")
    with web.session_transaction() as s:
        s["username"] = "Other"
    assert "data-gift=" not in web.get(page).text


def test_japanese_catalogue_and_game_filters(clients):
    web, _ = clients
    from api.distributions import labels
    all_jp = [g for g in gifts.catalog().values() if any(gifts.compatible(g, r, 1) for r in gifts.VERSIONS)]
    assert sum(bool(g.number) for g in all_jp) == 472
    assert sum(bool(g.species) for g in all_jp) == 47
    assert sum(g.event == "berries" for g in all_jp) == 6
    assert sum(g.event == "cafe" for g in all_jp) == 12
    response = web.get("/campaign/japan/?kind=wonder")
    assert labels()["results"].format(count=472) in response.text
    assert "/campaign/claim/" not in response.text
    assert "Liberty Pass" in web.get("/campaign/japan/", query_string={"kind":"wonder","q":"＃２０４６","version":21}).text
    assert "Liberty Pass" not in web.get("/campaign/japan/?kind=wonder&q=2046&version=23").text
    assert "d-192-575-286" in web.get("/campaign/japan/?version=23").text
    assert "d-192-575-286" not in web.get("/campaign/japan/?version=21").text
    for species in (387, 390, 393):
        assert gifts.compatible(gifts.catalog()[f"d-48-{species}-0"], 21, 1)


def test_cafe_gender_and_bundled_item_wait_for_room(clients):
    from game_sync_server.entralinked.model.player.dream_data import DreamItem
    code = gsid_to_gscd(441)
    cafe = gifts.catalog()["d-48-133-204"]
    partner = gifts.catalog()["d-192-575-286"]
    assert gifts.queue(code,cafe,21,2,0) == "incompatible"
    assert gifts.queue(code,cafe,21,1,0) == "queued"
    assert gifts.queue(code,cafe,21,1,1) == "queued"
    player = SimpleNamespace(gscd=code, rom_id=21, langcode=1, encounters=[], items=[])
    with db.transaction() as conn:
        assert gifts.add_to_wake(conn,player,10,20) == [cafe.key]
        assert (player.encounters[0].move, player.encounters[0].gender) == (204,0)
        gifts.confirm_wake(conn,code,[cafe.key])
    player.rom_id = 23
    assert gifts.queue(code,partner,23,1) == "queued"
    player.items = [DreamItem(10,1)]
    player.encounters.clear()
    with db.transaction() as conn:
        assert gifts.add_to_wake(conn,player,10,1) == []
        assert not player.encounters
        player.items = [DreamItem(230,255)]
        assert gifts.add_to_wake(conn,player,10,1) == []
        player.items.clear()
        assert gifts.add_to_wake(conn,player,10,1) == [partner.key]
        assert player.items == [DreamItem(230,1)] and player.encounters[0].move == 286
        gifts.confirm_wake(conn,code,[partner.key])
        assert gifts.add_to_wake(conn,player,10,1) == []


def test_repeatable_japanese_cards_use_exact_receipts(clients, monkeypatch):
    code = gsid_to_gscd(74)
    first, second = [g for g in gifts.catalog().values() if g.language == "JPN" and g.number == 95][:2]
    assert first.independent and second.independent and first.group != second.group
    with db.transaction() as conn:
        gifts.schema(conn)
        conn.execute("INSERT INTO distribution_cartridges VALUES(?,?,23,1,NULL)",(code,"test"))
        conn.execute("INSERT INTO distribution_orders VALUES(?,?,?,'sent',?)",(code,"card-95",first.key,b"old"))
        gifts.merge_album(conn,code,{"95":"received"}, {})
        _, orders, album = gifts.state(conn,code)
        assert gifts.status(first,orders,album) == "sent"
        assert gifts.status(second,orders,album) == "unknown"
    monkeypatch.setattr(gifts, "card_binary", lambda *_: b"second")
    assert gifts.queue(code,second,23,1) == "queued"
    with db.transaction() as conn:
        gifts.merge_album(conn,code,{"95":"at_center"}, {first.signature:"at_center"})
        _, orders, album = gifts.state(conn,code)
        assert gifts.status(first,orders,album) == "at_center"
        assert orders[first.group]["status"] == "delivered"
        assert gifts.status(second,orders,album) == "queued"


def test_berry_sets_use_one_destination_and_all_fit(clients):
    from game_sync_server.entralinked.model.player.dream_data import DreamItem
    from utils import managers
    code = gsid_to_gscd(116)
    game = gifts.catalog()["b-challenge-2013-06"]
    chest = gifts.catalog()["b-challenge-2013-04"]
    assert gifts.queue(code,chest,23,1,chest=True) == "sync"
    db.write_gscd(code)
    assert gifts.queue(code,game,21,1) == "incompatible"
    assert gifts.queue(code,game,23,1) == "queued"
    assert gifts.queue(code,game,23,1,chest=True) == "queued"
    for _ in range(2):
        assert gifts.queue(code,chest,23,1,chest=True) == "in_chest"
    assert gifts.queue(code,chest,23,1) == "in_chest"
    inventory = {r["pokeitem_id"]: r["item_cnt"] for r in managers.get_chest(code).data["list"]}
    assert [inventory[k] for k in chest.items] == [1,1]
    player = SimpleNamespace(gscd=code, rom_id=23, langcode=1, encounters=[None]*10, items=[DreamItem(202,2)])
    with db.transaction() as conn:
        assert gifts.add_to_wake(conn,player,10,2) == []
        assert player.items == [DreamItem(202,2)]
        assert gifts.add_to_wake(conn,player,10,3) == [game.key]
        assert player.items == [DreamItem(202,3),DreamItem(204,1),DreamItem(205,1)]
        gifts.confirm_wake(conn,code,[game.key])
        assert gifts.add_to_wake(conn,player,10,3) == []


def test_pwt_wireless_catalog_and_game_sync_creation(clients, monkeypatch):
    from utils import pwt_archive
    web, ds = clients

    def auth(action, **fields):
        response = ds.post("/ac", data=encode_form(dict(userid="3" * 13, passwd="qa", action=action, **fields)))
        return decode_form(response.text)

    auth("acctcreate")
    dl_token = auth("SVCLOC", svc="9000")["servicetoken"]
    game_token = auth("SVCLOC", svc="0000")["servicetoken"]

    def download(action, token=dl_token, **fields):
        params = dict(action=action, token=token, gamecd="IRAO", attr1="WBT_J", rhgamecd="IREJ")
        return ds.post("/download", data=encode_form({**params, **fields}))

    def record(row):
        data = bytearray(4884)
        struct.pack_into("<H", data, 8, row["number"])
        struct.pack_into("<H", data, 0x1210, binascii.crc_hqx(data[:0x1210], 0xffff))
        return bytes(data)

    monkeypatch.setattr(pwt_archive, "tournament_file", record)
    assert download("list", token="invalid").status_code == 401
    assert download("count").data == b"1"
    assert download("count", rhgamecd="IRDJ").data == b"1"
    assert download("count", rhgamecd="IRAJ").data == b"0"
    assert download("count", attr1="WBT_E").data == b"0"
    assert download("list", offset="1").data.strip() == b""
    assert download("list", num="0").data.strip() == b""
    name, label, kind, _, _, size = download("list").text.strip().split("\t")
    import base64
    assert base64.b64decode(label.translate(str.maketrans("*.-", "=+/"))).decode("utf-16le")
    assert kind == "WBT_J" and int(size) == 9 * 0x1214 + 4
    payload = download("contents", contents=name, attr1="")
    assert payload.status_code == 200 and payload.mimetype == "application/x-dsdl"
    assert len(payload.data) == int(size)
    rows = pwt_archive.current_events()
    assert len({row["number"] for row in rows}) == 9 and not any("(Bug)" in row["file"] for row in rows)
    assert payload.data[:-4] == b"".join(record(row)[:0x1214] for row in rows)
    assert struct.unpack("<I", payload.data[-4:])[0] == binascii.crc_hqx(payload.data[:-4], 0xffff)
    assert download("contents", contents=name, rhgamecd="IRBO").status_code == 404

    def create(value, **params):
        return ds.post("/dsio/gw", auth=(USERNAME, PASSWORD), data=str(value),
                       query_string=dict(p="account.createdata", tok=game_token, **params))

    def check(value):
        return web.get("/api/", query_string=dict(p="pgl.member.profile.rom_check", gscd=gsid_to_gscd(value))).json

    assert create(672, rom=20, langcode=1).data[:128] == bytes(128)
    assert check(672) == {"rom_id": 20}
    assert create(673).data[:128] == bytes(128)
    assert create(-1).status_code == 200 and create(1 << 32).data[:128] != bytes(128)
    assert check(673)["error"]["details"]["gscd"] != check(674)["error"]["details"]["gscd"]
