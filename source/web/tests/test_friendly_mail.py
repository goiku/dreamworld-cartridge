import re

from api.server import create_app
from game_sync_server.entralinked.model.player.player_manager import PlayerManager
from game_sync_server.entralinked.utility.db_manager import db
from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
from utils import save_data
from utils.account_manager import accounts


def test_trade_pal_compose_delivery_and_block(tmp_path, monkeypatch):
    for store in (accounts, db):
        store.close()
        monkeypatch.setattr(store, "_db_path", tmp_path / "mail.db")
        monkeypatch.setattr(store, "_created", False)
    monkeypatch.setattr("api.server.get_secret_key", lambda: "test-mail")
    monkeypatch.setattr("api.mailer.LANG", "zh")
    app = create_app()
    alice, bob = app.test_client(), app.test_client()
    assert alice.get("/mailer/").status_code == 401
    a, b = gsid_to_gscd(101), gsid_to_gscd(102)
    for pid, (client, code, name) in enumerate(((alice, a, "Alice"), (bob, b, "Bob")), 1):
        accounts.create_account(name, "unused", "", 1, 1, "everyone", "everyone", name)
        PlayerManager().register_player(code, 20, 1)
        accounts.link_gscd(name, code)
        save_data.update_member({"pgl_name": name}, code)
        with db.transaction() as conn:
            key = bytes([pid])
            conn.execute("INSERT INTO wfc_cartridge_keys VALUES(?,?)", (code, key))
            conn.execute("INSERT INTO wfc_profile_keys VALUES(?,?)", (pid, key))
        with client.session_transaction() as s:
            s.update(username=name, gscd=code)
    with db.transaction() as conn:
        conn.execute("INSERT INTO gts_profile_events VALUES(1,1,2,X'01',X'02','{}','{}',0)")
    recipient = str(save_data.read_member(b)["member_savedata_id"])
    page = alice.get("/mailer?mailto=" + recipient, follow_redirects=True)
    assert page.status_code == 200 and re.search(r'<option value="\d+" selected>Bob</option>', page.text)
    action = re.search(r'<form method="post" action="([^"]+)"', page.text)[1]
    form = {"ticket": re.search(r'name="ticket" value="([^"]+)"', page.text)[1],
            "recipient": recipient, "phrase": "trade"}
    assert bob.post(action, data=form).status_code == 403
    for _ in range(2):
        assert alice.post(action, data=form).status_code == 303
    assert alice.get("/mailer/?box=sent").text.count("<article>") == 1
    inbox = bob.get("/mailer/").text
    assert inbox.count("<article>") == 1 and "谢谢你和我交换宝可梦" in inbox
    assert not re.search("<article>", alice.get("/mailer/").text)
    save_data.update_member({"blocked_profiles": [a]}, b)
    assert alice.post(action, data=form).status_code == 403
    assert "目前无法给这位好友发信" in alice.get("/mailer/?mailto=" + recipient).text
    accounts.close()
    db.close()
