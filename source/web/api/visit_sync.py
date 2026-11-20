"""Pair one visiting cartridge and open its isolated browser session."""
import json
import re
import secrets

from flask import Blueprint, Response, jsonify, make_response, redirect, render_template_string, request, session
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.wrappers import Response as WerkzeugResponse

from utils import visit_storage as storage

visit_sync = Blueprint("visit_sync", __name__, url_prefix="/visit-sync")

_SECRET = re.compile(r"[A-Za-z0-9_-]{20,128}")
_PAIR_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_REVISION = re.compile(r"[0-9a-f]{64}")


def _bearer() -> str:
    scheme, _, value = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not _SECRET.fullmatch(value):
        raise storage.VisitAuthError()
    return value


def _body(*fields: str) -> dict:
    request.max_content_length = storage.MAX_SNAPSHOT_BYTES + 4096
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or set(data) != set(fields):
        raise storage.VisitInvalid()
    return data


def _snapshot_response(result: dict, *, conditional: bool = False) -> Response:
    revision = result["revision"]
    if conditional and request.if_none_match.contains_weak(revision):
        response = make_response("", 304)
    else:
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        response = Response(payload, mimetype="application/json")
    response.set_etag(revision)
    return response


@visit_sync.after_request
def private_response(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@visit_sync.errorhandler(storage.VisitAuthError)
def unauthorized(_exc: Exception) -> tuple[Response, int]:
    return jsonify(error="unauthorized"), 401


@visit_sync.errorhandler(storage.VisitInvalid)
def invalid_request(_exc: Exception) -> tuple[Response, int]:
    return jsonify(error="invalid_request"), 400


@visit_sync.errorhandler(storage.VisitConflict)
def conflict(_exc: Exception) -> tuple[Response, int]:
    return jsonify(error="conflict"), 409


@visit_sync.errorhandler(RequestEntityTooLarge)
def too_large(_exc: Exception) -> tuple[Response, int]:
    return jsonify(error="too_large"), 413


@visit_sync.post("/api/redeem")
def redeem() -> Response:
    invite = _bearer()
    data = _body("token", "snapshot")
    token = data["token"]
    if not isinstance(token, str) or not _PAIR_TOKEN.fullmatch(token):
        raise storage.VisitInvalid()
    return _snapshot_response(storage.redeem(invite, data["snapshot"], token))


@visit_sync.get("/api/snapshot")
def read_snapshot() -> Response:
    return _snapshot_response(storage.read_snapshot(_bearer()), conditional=True)


@visit_sync.put("/api/snapshot")
def write_snapshot() -> Response:
    token = _bearer()
    data = _body("revision", "snapshot")
    revision = data["revision"]
    if not isinstance(revision, str) or not _REVISION.fullmatch(revision):
        raise storage.VisitInvalid()
    return _snapshot_response(storage.replace_snapshot(token, revision, data["snapshot"]))


@visit_sync.post("/api/ticket")
def issue_ticket() -> Response:
    return jsonify(ticket=storage.create_ticket(_bearer()))


_LOGIN_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pokémon Dream World</title></head><body><main>
<p id="message">Open your visit link from your home server. / 自分のサーバーで訪問リンクを開いてください。 / 请从自己的服务器打开访问链接。</p>
<form method="post" action="/visit-sync/login"><input type="hidden" name="ticket"></form>
<script nonce="{{nonce}}">
const ticket = location.hash.slice(1);
history.replaceState(null, "", location.pathname);
if (/^[A-Za-z0-9_-]{20,128}$/.test(ticket)) {
    document.getElementById("message").hidden = true;
    const form = document.querySelector("form");
    form.elements.ticket.value = ticket;
    form.submit();
}
</script></main></body></html>"""


@visit_sync.get("/login")
def login_page() -> Response:
    nonce = secrets.token_urlsafe(24)
    response = make_response(render_template_string(_LOGIN_PAGE, nonce=nonce))
    response.headers["Content-Security-Policy"] = (
        f"default-src 'none'; script-src 'nonce-{nonce}'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
    )
    return response


@visit_sync.post("/login")
def ticket_login() -> WerkzeugResponse:
    # The browser exchanges the one-use ticket at its own origin. Never read
    # the ticket from the query string, which may be recorded in access logs.
    origin = request.headers.get("Origin")
    if (origin and origin != request.host_url.rstrip("/")) or request.headers.get("Sec-Fetch-Site") == "cross-site":
        raise storage.VisitAuthError()
    request.max_content_length = 2048
    ticket = request.form.get("ticket", "")
    if not _SECRET.fullmatch(ticket):
        raise storage.VisitAuthError()
    username, gscd, display_name = storage.consume_ticket(ticket)
    session.clear()
    session.update(username=username, gscd=gscd, visit_guest=True, visit_display_name=display_name)
    return redirect("/pdw/", 303)
