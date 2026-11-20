"""Resident browser controls for pairing and refreshing two privately hosted islands."""

import secrets
from urllib.parse import urlsplit

from flask import Blueprint, Response, jsonify, request, session

from utils import island_peers as peers
from utils import offline_islands as islands
from utils.account_manager import accounts
from utils.visit_storage import GUEST_PREFIX
from utils.web_network import is_web_host

island_peers = Blueprint("island_peers", __name__, url_prefix="/island-peers")


@island_peers.before_request
def authorize() -> tuple[Response, int] | None:
    user, card = session.get("username"), session.get("gscd")
    if (
        not isinstance(user, str)
        or user.startswith(GUEST_PREFIX)
        or session.get("visit_guest")
        or not card
        or accounts.get_gscd_owner(card) != user
    ):
        return jsonify(error="home_account_required"), 403
    if request.method == "POST":
        csrf = session.get("island_csrf")
        if (
            not request.is_json
            or request.headers.get("Sec-Fetch-Site") == "cross-site"
            or not isinstance(csrf, str)
            or not secrets.compare_digest(csrf.encode(), request.headers.get("X-Island-CSRF", "").encode())
            or request.headers.get("Origin", request.host_url.rstrip("/")) != request.host_url.rstrip("/")
            or not is_web_host(urlsplit(request.host_url).hostname)
        ):
            return jsonify(error="same_origin_required"), 403
        request.max_content_length = 1024
    return None


@island_peers.after_request
def private(response: Response) -> Response:
    response.cache_control.no_store = True
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@island_peers.errorhandler(peers.PeerError)
def failed(exc: peers.PeerError) -> tuple[Response, int]:
    error = str(exc)
    return jsonify(error=error), 503 if error in (
        "offline",
        "no_private_listener",
        "unreachable_private_network",
    ) else 409


@island_peers.errorhandler(islands.IslandError)
def bad_island(_exc: islands.IslandError) -> tuple[Response, int]:
    return jsonify(error="invalid_island"), 409


@island_peers.post("/invite")
def create() -> Response:
    return jsonify(peers.invite(session["gscd"]))


@island_peers.post("/pair")
def pair() -> Response:
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or not isinstance(body.get("code"), str):
        raise peers.PeerError("invalid_code")
    return jsonify(peers.join(session["gscd"], body["code"]))


@island_peers.get("/status")
def status() -> Response:
    return jsonify(
        peers=[
            {
                "island_id": r["island"],
                "last_sync": r["heard"] or None,
                "online": bool(r["reachable"]) and r["heard"] > peers.now() - 3 * peers.INTERVAL,
            }
            for r in peers.link_rows(session["gscd"])
        ]
    )


@island_peers.post("/live/<island>")
def live(island: str) -> Response:
    peers.sync(peers.lookup(session["gscd"], island))
    session["island_live_confirmed"] = {"id": island, "at": peers.now()}
    return jsonify(island_id=island, last_sync=peers.now(), online=True)


@island_peers.post("/forget/<island>")
def forget(island: str) -> Response:
    peers.forget(session["gscd"], island)
    return jsonify(island_id=island, paired=False)
