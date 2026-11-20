"""Promotions for the cartridge linked to the signed-in resident."""
import secrets
import unicodedata
from functools import cache

from flask import Blueprint, abort, redirect, render_template, request, session, url_for

from api.native_islands import resident
from api.pgl_pals import current_save
from utils.visit_storage import GUEST_PREFIX
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
    args = {k: request.form[k] for k in ("filter", "page", "q", "version") if request.form.get(k)}
    endpoint = "campaigns.japan" if request.form.get("scope") == "jp" else "campaigns.index"
    return redirect(url_for(endpoint, kind=kind, **args, _anchor=anchor), code=303)


@campaigns.get("/campaign/")
def index():
    return _listing(False)


@campaigns.get("/campaign/japan/")
def japan():
    return _listing(True)


def _fold(value):
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _campaign_card():
    username = session.get("username") or ""
    if bool(session.get("visit_guest")) != username.startswith(GUEST_PREFIX):
        return None
    return current_save()


def _listing(japanese):
    card = _campaign_card()
    member = save_data.read_member(card) if card else {}
    rom, lang = member.get("rom_id"), member.get("langcode")
    kind = "wonder" if request.args.get("kind") == "wonder" else "dream"
    mode = request.args.get("filter", "all")
    if mode not in ("all", "unclaimed", "waiting", "complete", "unknown_filter"):
        mode = "all"
    rows = []
    ident = album = None
    orders = {}
    if card:
        with db.transaction() as conn:
            ident, orders, album = gifts.state(conn, card)
    search = request.args.get("q", "").strip()[:100]
    needle = _fold(search)
    version = request.args.get("version", type=int)
    versions = {r: text.lookup_str("game", r) for r in gifts.VERSIONS}
    if version not in versions:
        version = None
    if japanese or card:
        for gift in gifts.catalog().values():
            if bool(gift.number) != (kind == "wonder"):
                continue
            eligible = bool(card and gifts.compatible(gift, rom, lang))
            if japanese:
                targets = [r for r in versions if gifts.compatible(gift, r, 1)]
                if not targets or version and version not in targets:
                    continue
            elif not eligible:
                continue
            name = gift.name or text.lookup_str("pokemon", gift.species)
            if gift.japanese_title and LANG == "ja":
                name = gift.japanese_title
            details = []
            noun = "item" if gift.card_type == 2 else "pokemon"
            if gift.card_type:
                details.extend((text.lookup_str(noun, gift.subject), gift.card_title))
            if gift.move:
                details.append(text.lookup_str("move", gift.move))
            details.extend(text.lookup_str("item", item) for item in gift.items)
            if gift.event:
                details.append(labels()[gift.event])
            details = [v for v in details if v]
            if needle:
                numeric = needle.lstrip("#")
                if numeric.isdecimal():
                    if not gift.number or str(gift.number) != (numeric.lstrip("0") or "0"):
                        continue
                else:
                    aliases = [text.lookup_str(noun, gift.subject or gift.species, language=locale) or ""
                               for locale in ("ja", "en", "zh")]
                    if needle not in _fold(" ".join([name or "", gift.name, gift.japanese_title, *details, *aliases])):
                        continue
            status = gifts.status(gift, orders, album) if eligible else "incompatible"
            exclusive = bool(eligible and gift.number and gifts.variant_counts(rom, lang)[gift.group] > 1)
            same = exclusive and status in ("received", "at_center", "collected") and gift.key not in (album or {})
            if status == "alternative":
                bucket = None
            elif status == "unknown" or same:
                bucket = "unknown_filter"
            elif status == "available":
                bucket = "unclaimed"
            else:
                bucket = "waiting" if status in ("queued", "sent") else "complete"
            if mode != "all" and (not eligible or mode != bucket):
                continue
            rows.append(dict(key=gift.key, name=name, details=details, event=gift.event,
                             versions=[versions[r] for r in targets] if japanese else [],
                             number=gift.number, status=status, same=same, exclusive=exclusive,
                             claim=eligible and status in ("available", "unknown") and (not gift.number or ident is not None)))
    pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(pages, request.args.get("page", 1, type=int)))
    bulk_count = None
    if kind == "wonder" and ident and (not japanese or lang == 1 and version in (None, rom)):
        bulk_count = len(gifts.unclaimed_cards(rom, lang, orders, album))
    response = render_template("distributions.html", t=labels(), lang=LANG, kind=kind, mode=mode, card=card,
                               japanese=japanese, endpoint=request.endpoint, search=search, version=version,
                               versions=versions, count=len(rows),
                               ident=ident, home_card=not session.get("visit_guest"), album_known=album is not None, rom=text.lookup_str("game", rom),
                               rows=rows[(page-1)*PAGE_SIZE:page*PAGE_SIZE], page=page, pages=pages,
                               csrf=session.setdefault("gift_csrf", secrets.token_hex(24)),
                               notice=session.pop("gift_notice", None), bulk_count=bulk_count,
                               bulk_totals=session.pop("gift_bulk_totals", None))
    return response, 200, {"Cache-Control": "private, no-store"}


@campaigns.post("/campaign/claim/<key>")
def claim(key):
    card = _campaign_card()
    _post(card)
    gift = gifts.catalog().get(key) or abort(404)
    member = save_data.read_member(card)
    if request.form.get("next") == "1":
        return _return("wonder", gifts.prioritize(card, gift), gift.key)
    try:
        gender = int(request.form["gender"]) if "gender" in request.form else None
        result = gifts.queue(card, gift, member.get("rom_id"), member.get("langcode"), gender,
                             chest=request.form.get("destination") == "chest")
    except (OSError, ValueError):
        result = "unavailable"
    return _return("wonder" if gift.number else "dream", result, gift.key)


@campaigns.post("/campaign/claim-unclaimed")
def claim_unclaimed():
    card = _campaign_card()
    _post(card)
    member = save_data.read_member(card)
    result, added, failed = gifts.queue_unclaimed_cards(card, member.get("rom_id"), member.get("langcode"))
    session["gift_notice"] = result
    if result == "bulk_result":
        session["gift_bulk_totals"] = {"added": added, "failed": failed}
    return redirect(url_for("campaigns.index", kind="wonder", filter="waiting"), code=303)


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
