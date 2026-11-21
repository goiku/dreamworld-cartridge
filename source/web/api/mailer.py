"""Friendly Mail between cartridge contacts and accepted Dream Pals."""
import json
from secrets import token_urlsafe

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from itsdangerous import BadData, URLSafeSerializer

from api.pgl_member import _cartridge_contacts
from api.pgl_pals import current_save
from config import LANG, ROOT_DIR
from game_sync_server.entralinked.utility.db_manager import db
from utils import save_data, visits

mailer = Blueprint("mailer", __name__, template_folder="../templates")
LABELS = json.loads((ROOT_DIR / "json_data/friendly_mail.json").read_text(encoding="utf-8"))


def _contacts(viewer):
    partners = set(_cartridge_contacts(viewer))
    for row in db.read_rows("SELECT left_gscd,right_gscd FROM dream_pals WHERE accepted=1 "
                            "AND (left_gscd=? OR right_gscd=?)", viewer, viewer):
        partners.add(row[1] if row[0] == viewer else row[0])
    contacts = {}
    for other in partners:
        if other == viewer or not visits.published(other, viewer, dream_world=False):
            continue
        member = save_data.read_member(other)
        if member.get("pgl_name") and member.get("member_savedata_id") is not None:
            contacts[str(member["member_savedata_id"])] = (other, member["pgl_name"])
    return dict(sorted(contacts.items(), key=lambda item: item[1][1].casefold()))


@mailer.get("/mailer/index.html")
@mailer.route("/mailer/", methods=["GET", "POST"])
def mailbox():
    t = LABELS[LANG]
    viewer = current_save()
    def page(status=200, **data):
        return render_template("friendly_mail.html", t=t, lang=LANG, **data), status, {"Cache-Control": "no-store"}
    if not viewer:
        return page(401, login=True)

    contacts = _contacts(viewer)
    selected = request.args.get("mailto")
    if request.method == "POST":
        selected = request.form.get("recipient", "")
    unavailable = selected is not None and selected not in contacts
    signer = URLSafeSerializer(current_app.secret_key, salt="pgl-friendly-mail")
    if request.method == "POST":
        try:
            owner, nonce = signer.loads(request.form.get("ticket", ""))
        except BadData:
            return page(400, error=t["unavailable"])
        phrase = request.form.get("phrase", "")
        if owner != viewer or unavailable or phrase not in t["phrases"]:
            return page(403, error=t["unavailable"])
        other, name = contacts[selected]
        with db.transaction() as conn:
            conn.execute("INSERT INTO dream_mail(sender,recipient,sender_name,recipient_name,phrase,submission) "
                         "VALUES(?,?,?,?,?,?) ON CONFLICT(sender,submission) DO NOTHING",
                         (viewer, other, save_data.read_member(viewer)["pgl_name"], name, phrase, nonce))
        return redirect(url_for("mailer.mailbox", box="sent", delivered=1), 303)

    sent = request.args.get("box") == "sent"
    column = "sender" if sent else "recipient"
    rows = db.read_rows(f"SELECT sender_name,recipient_name,phrase,created FROM dream_mail "
                        f"WHERE {column}=? ORDER BY id DESC", viewer)
    return page(contacts=contacts, selected=selected, unavailable=unavailable, rows=rows,
                sent=sent, ticket=signer.dumps((viewer, token_urlsafe(18))))
