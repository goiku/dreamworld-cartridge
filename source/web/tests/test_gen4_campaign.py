import binascii
import io
import re
import struct
from types import SimpleNamespace

from flask import Flask

from api.server import create_app
from game_sync_server.entralinked.network.http.dls_handler import DlsHandler
from game_sync_server.entralinked.utility.db_manager import DBManager
from game_sync_server.entralinked.utility.url_encoded_form import encode_form
from utils import gen4_events, gen4_gifts


def _save(number):
    raw = bytearray(0x80000)
    end = 0xcf2c
    raw[0x68+0x19] = 1
    raw[0xb4c0+number//8] = 1 << (number%8)
    struct.pack_into("<I", raw, end-12, end)
    struct.pack_into("<H", raw, end-2, binascii.crc_hqx(raw[:end-20],65535))
    return bytes(raw)


def test_physical_pairing_queue_retries_exclusivity_and_album(tmp_path, monkeypatch):
    db = DBManager(tmp_path/"gifts.db")
    monkeypatch.setattr(gen4_gifts,"db",db)
    payload = bytes(range(156))*6
    monkeypatch.setattr(gen4_gifts,"_payload",lambda _: payload)
    web = create_app().test_client()
    native = Flask(__name__)
    users = SimpleNamespace(get_service_session=lambda token,svc: SimpleNamespace(user=SimpleNamespace(id=token.split("-")[0])))
    native.register_blueprint(DlsHandler(SimpleNamespace(user_manager=users,dlc_list=None)).blueprint())
    ds = native.test_client()
    def req(tok,action,**kwargs):
        return ds.post("/download",data=encode_form(dict(token=tok,gamecd="CPUJ",action=action,**kwargs))).data
    def getfile(tok):
        name = req(tok,"list").split(b"\t")[0].decode()
        return name,req(tok,"contents",contents=name)
    page="/gen4/?game=CPU&language=ja"
    web.get(page)
    with web.session_transaction() as s:
        csrf=s["g4_csrf"]
    form=dict(game="CPU",language="ja",csrf=csrf)
    def post(action,**kwargs):
        return web.post("/gen4/gifts/"+action,data=dict(form,**kwargs))
    assert post("start").status_code==303
    _, preview=getfile("ds-pair")
    pin="".join(str(n-0x121) for n in struct.unpack_from("<10H",preview))
    assert len(pin)==10 and preview[80:]==payload[80:]
    assert post("pair",pin=pin).status_code==303
    html=web.get(page).get_data(as_text=True)
    form["target"]=re.search(r'name="target" value="([0-9a-f]{24})"',html)[1]
    assert getfile("ds-pair")[1]==preview
    assert req("ds-next","count")==b"0"
    assert req("other-friend","count")==b"1"
    pool=gen4_events.selection("CPUJ")
    picks=[k for k,e in pool.items() if e["number"]==182]
    assert len(picks)==4
    for k in picks[:2]:
        assert post("claim",key=k).status_code==303
    assert post("album",save=(io.BytesIO(_save(36)),"test.sav")).status_code==303
    assert post("bulk").status_code==post("bulk").status_code==303
    with db.transaction() as c:
        rows=c.execute("SELECT * FROM g4_orders ORDER BY position").fetchall()
        assert rows[0]["gift"]==picks[0] and len(rows)>40
        assert not any(r["number"]==36 for r in rows)
        assert not any(r["number"] in (59,60,61) for r in rows)
        assert len({r["number"] for r in rows})==len(rows)
        last=rows[-1]["gift"]
    assert post("next",key=last).status_code==303
    name,raw=getfile("ds-take1")
    assert name==gen4_gifts.filename(last) and raw==payload
    assert getfile("ds-take1")== (name,payload)
    assert getfile("ds-take2")[0]==gen4_gifts.filename(picks[0])
    queue=web.get("/gen4/queue/?game=CPU&language=ja").get_data(as_text=True)
    assert 'id="receiver-queue"' in queue and 'distribution-queue.js' in queue
    assert post("claim",key=picks[2],target="invalid").status_code==403
    assert post("album",save=(io.BytesIO(bytes(0x80000)),"bad.sav")).status_code==303
    with db.transaction() as c:
        album=c.execute("SELECT album FROM g4_receivers").fetchone()[0]
        assert '"36"' in album
    db.close()
