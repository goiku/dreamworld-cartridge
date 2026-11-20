"""A home cartridge's cached islands, share controls, native room links, and visitor log."""
import hashlib
import json
import secrets
from datetime import UTC, datetime
from urllib.parse import urlsplit

from flask import Blueprint, Response, abort, jsonify, redirect, render_template, request, session, url_for
from werkzeug.wrappers import Response as WerkzeugResponse

from api import native_islands
from api.pgl_pals import dream_pals
from config import LANG
from utils import island_peers as peers
from utils import island_actions as actions, managers, text
from utils import offline_islands as islands
from utils.data import load_json_data
from utils.island_art import house_thumbnail
from utils.island_profile import groups
from utils.web_network import is_web_host

offline_friends = Blueprint("offline_friends", __name__, url_prefix="/islands", template_folder="../templates",
                            static_folder="../static", static_url_path="/assets")
_labels = load_json_data("offline_islands_ui")


def _card() -> str:
    return native_islands.resident() or abort(403)


def _check_form() -> None:
    token = session.get("island_csrf")
    if (not isinstance(token, str) or not is_web_host(urlsplit(request.host_url).hostname)
            or request.headers.get("Sec-Fetch-Site") == "cross-site"
            or request.headers.get("Origin", request.host_url.rstrip("/")) != request.host_url.rstrip("/")
            or not secrets.compare_digest(token.encode(), request.form.get("csrf", "").encode())):
        abort(403)


def _date(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d %H:%M UTC")


def _revision(friends: list[dict], feet: list[dict], paired: set[str]) -> str:
    # A heartbeat alone should not redraw the list or disturb an active invitation form.
    rows = [(f["island_id"], f["version"], f["island_id"] in paired) for f in friends]
    ids = [(f["guest_island"], f["event_id"]) for f in feet]
    return hashlib.sha256(json.dumps([rows, ids]).encode()).hexdigest()[:24]


@offline_friends.context_processor
def context() -> dict:
    return {"t": _labels[LANG], "lang": "zh-CN" if LANG == "zh" else LANG, "date": _date}


@offline_friends.before_app_request
def on_game_page() -> None:
    if request.path in ("/pdw/", "/pdw/index.html", "/islands/"):
        native_islands.start_browser()


@offline_friends.after_request
def private(response: Response) -> Response:
    if request.endpoint not in ("offline_friends.picture", "offline_friends.static"):
        response.cache_control.no_store = True
        response.headers["Referrer-Policy"] = "same-origin"
    return response


def _index_url(notice: str) -> WerkzeugResponse:
    return redirect(url_for(".roster", notice=notice), 303)


@offline_friends.errorhandler(413)
def too_large(_error: Exception) -> WerkzeugResponse:
    return _index_url("error")


@offline_friends.get("/")
def roster() -> str:
    card = native_islands.resident()
    pals = []
    archive = []
    feet = []
    revision = ""
    if card:
        connections = {entry["island"]: entry for entry in peers.link_rows(card)}
        for entry in islands.list_friends(card):
            peer = connections.get(entry["island_id"])
            entry["paired"] = peer is not None
            entry["event_id"] = secrets.token_hex(16)
            archive.append(entry)
        pals = dream_pals({"rowcount": "9999"})["list"]
        feet = islands.received_footprints(card)
        revision = _revision(archive, feet, set(connections))
    return render_template("island_friends.html", card=card, friends=archive, original=pals,
                           notice=request.args.get("notice"),
                           csrf=session.setdefault("island_csrf", secrets.token_hex(24)) if card else "",
                           feet=feet, revision=revision)


@offline_friends.get("/updates")
def updates() -> Response:
    card = _card()
    links = peers.link_rows(card)
    revision = _revision(islands.list_friends(card), islands.received_footprints(card), {row["island"] for row in links})
    return jsonify(revision=revision)


@offline_friends.get("/export")
def download() -> WerkzeugResponse:
    try:
        doc = islands.export_island(_card())
    except islands.IslandError:
        return _index_url("error")
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    response = Response(body, mimetype="application/json")
    response.headers["Content-Disposition"] = f'attachment; filename="dream-island-{doc["island_id"][:12]}.json"'
    return response


@offline_friends.post("/import")
def upload() -> WerkzeugResponse:
    card = _card()
    request.max_content_length = islands.MAX_BYTES + 16384
    _check_form()
    file = request.files.get("snapshot")
    if not file:
        return _index_url("error")
    try:
        doc = islands.decode_snapshot(file.read(islands.MAX_BYTES + 1))
        cached = islands.import_island(card, doc)
    except islands.IslandError:
        return _index_url("error")
    return _index_url("kept" if cached["version"] > doc["version"] else "imported")


def _snapshot(card: str, island_id: str) -> dict:
    try:
        return islands.get_friend(card, island_id)
    except islands.IslandNotFound:
        abort(404)


@offline_friends.post("/<island_id>/enter")
def enter(island_id: str) -> WerkzeugResponse:
    card = _card()
    _check_form()
    _snapshot(card, island_id)
    try:
        native_islands.prepare(card, island_id, request.form.get("event_id", ""))
    except islands.IslandError:
        abort(400)
    return redirect(url_for("site.catch_all", path="pdw/", island=island_id), 303)


@offline_friends.get("/<island_id>/")
def room(island_id: str) -> WerkzeugResponse:
    _snapshot(_card(), island_id)
    return redirect(url_for("site.catch_all", path="pdw/", island=island_id))


@offline_friends.get("/<island_id>/profile")
def profile(island_id: str) -> str:
    card = _card()
    doc = _snapshot(card, island_id)
    content = doc["content"]
    paired = any(row["island"] == island_id for row in peers.link_rows(card))
    active = paired and actions.compatible(card,island_id)
    stock = [(item["pokeitem_id"],item["item_cnt"]) for item in managers.get_chest(card).data["list"]
             if item["item_cnt"] > 0] if active else []
    return render_template("island_profile.html", doc=doc, owner=content["profile"]["pgl_name"],
                           in_room=request.args.get("in_room") == "1",
                           groups=groups(content, LANG, _labels[LANG]), interactive=active, stock=stock,
                           ui=load_json_data("island_actions")[LANG], item_name=lambda n:text.lookup_str("item", n),
                           history=actions.history(card,island_id) if paired else [],
                           full=managers.CropManager.FULL_DIRT_HP, ripe=managers.CropManager.GROWTH_STAGES,
                           csrf=session.setdefault("island_csrf",secrets.token_hex(24)))


@offline_friends.post("/<island_id>/interact")
def interact(island_id: str) -> WerkzeugResponse:
    card = _card()
    _check_form()
    _snapshot(card,island_id)
    try:
        peers.request_interaction(card,island_id,int(request.form["version"]),request.form["kind"],
                                  int(request.form["slot"]),request.form.get("payment",type=int))
        notice = "saved"
    except (ValueError,KeyError):
        notice = "changed"
    return redirect(url_for(".profile",island_id=island_id,notice=notice,_anchor="interactions",
                            in_room="1" if request.form.get("in_room") == "1" else None),303)


@offline_friends.get("/native/<identifier>")
def native_info(identifier: str) -> Response:
    card = _card()
    if len(identifier) == 64:
        doc = _snapshot(card, identifier)
    elif identifier.isascii() and identifier.isdecimal() and len(identifier) < 17:
        doc = islands.get_native_friend(card, int(identifier)) or abort(404)
    else:
        abort(404)
    island_id = doc["island_id"]
    member_id = islands.native_member_id(card, island_id)
    return jsonify(island_id=island_id, member_savedata_id=member_id, country_id=1,
                   house=doc["content"]["island"]["island_id"], pgl_name=doc["content"]["profile"]["pgl_name"],
                   updated_at=doc["updated_at"], adventure_url=url_for("island_adventure.adventure", island_id=island_id),
                   profile_url=url_for("offline_friends.profile", island_id=island_id))


@offline_friends.get("/houses/<int:item_id>/thumbnail")
def picture(item_id: int) -> WerkzeugResponse:
    try:
        image, mime = house_thumbnail(item_id)
    except (ValueError, FileNotFoundError):
        abort(404)
    response = Response(image, mimetype=mime)
    response.cache_control.public = True
    response.cache_control.max_age = 86400
    response.add_etag()
    return response.make_conditional(request)
