"""Promotions for the cartridge linked to the signed-in resident."""
import secrets
from functools import cache

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from api.native_islands import resident
from config import LANG
from game_sync_server.entralinked.model.save_file import SaveFile, SaveFileError
from game_sync_server.entralinked.utility.db_manager import db
from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
from utils import distributions as gifts
from utils import save_data, text
from utils.data import load_json_data

campaigns = Blueprint("campaigns", __name__, template_folder="../templates")
PAGE_SIZE = 24


@cache
def labels():
    return load_json_data("distribution_ui")[LANG]


def title():
    return labels()["title"]


def _post(card):
    expected = session.get("gift_csrf", "")
    if (not card or not expected or not secrets.compare_digest(expected.encode(), request.form.get("csrf", "").encode())
            or request.form.get("card") != card):
        abort(403)


def _return(kind, message, anchor=""):
    session["gift_notice"] = message
    args = {"kind": kind, "filter": request.form.get("filter", "all"), "page": request.form.get("page", "1")}
    return redirect(url_for("campaigns.index", **args, _anchor=anchor), code=303)


@campaigns.get("/campaign/")
def index():
    card = resident()
    member = save_data.read_member(card) if card else {}
    rom, lang = member.get("rom_id"), member.get("langcode")
    kind = "wonder" if request.args.get("kind") == "wonder" else "dream"
    mode = request.args.get("filter", "all")
    if mode not in ("all", "unclaimed", "waiting", "complete", "unknown_filter"):
        mode = "all"
    rows = []
    ident = album = None
    if card:
        with db.transaction() as conn:
            ident, orders, album = gifts.state(conn, card)
        for gift in gifts.catalog().values():
            if not gifts.compatible(gift, rom, lang) or bool(gift.number) != (kind == "wonder"):
                continue
            status = gifts.status(gift, orders, album)
            if status == "alternative":
                bucket = None
            elif status == "unknown":
                bucket = "unknown_filter"
            elif status == "available":
                bucket = "unclaimed"
            else:
                bucket = "waiting" if status in ("queued", "sent") else "complete"
            if mode != "all" and mode != bucket:
                continue
            same = bool(gift.number and gifts.variant_counts(rom, lang)[gift.group] > 1 and
                        status in ("received", "at_center", "collected") and
                        gift.key not in (album or {}))
            rows.append(dict(key=gift.key, name=gift.name or text.lookup_str("pokemon", gift.species),
                             number=gift.number, status=status, same=same,
                             claim=status in ("available", "unknown") and (not gift.number or ident is not None)))
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(pages, request.args.get("page", 1, type=int)))
    response = render_template("distributions.html", t=labels(), lang=LANG, kind=kind, mode=mode, card=card,
                               ident=ident, album_known=album is not None, rom=text.lookup_str("game", rom),
                               rows=rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE], page=page, pages=pages,
                               csrf=session.setdefault("gift_csrf", secrets.token_hex(24)),
                               notice=session.pop("gift_notice", None))
    return response, 200, {"Cache-Control": "private, no-store"}


@campaigns.post("/campaign/claim/<key>")
def claim(key):
    card = resident()
    _post(card)
    gift = gifts.catalog().get(key) or abort(404)
    member = save_data.read_member(card)
    if request.form.get("next") == "1":
        return _return("wonder", gifts.prioritize(card, gift), gift.key)
    try:
        result = gifts.queue(card, gift, member.get("rom_id"), member.get("langcode"))
    except (OSError, ValueError):
        result = "unavailable"
    return _return("wonder" if gift.number else "dream", result, gift.key)


@campaigns.post("/campaign/album")
def inspect_album():
    request.max_content_length = 0x80000 + 16384
    card = resident()
    _post(card)
    upload = request.files.get("save")
    if not upload:
        return _return("wonder", "invalid")
    raw = upload.stream.read(0x80001)
    try:
        trainer = SaveFile(raw).trainer
    except (SaveFileError, IndexError, ValueError):
        return _return("wonder", "invalid")
    signatures = {}
    album = gifts.cartridge_album(raw, signatures)
    with db.transaction() as conn:
        ident, _, _ = gifts.state(conn, card)
        if (len(raw) != 0x80000 or not trainer.game_sync_id or gsid_to_gscd(trainer.game_sync_id) != card
                or not ident or (trainer.game, trainer.language) != (ident["rom"], ident["lang"]) or album is None):
            return _return("wonder", "invalid")
        gifts.merge_album(conn, card, album, signatures)
    return _return("wonder", "scanned")
