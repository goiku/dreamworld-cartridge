"""The Flask app.

It serves the ?p=<endpoint> API (api/routes.py), Trainer Club sign-up
(api/signup.py), and the mirrored site assets with their patches (utils/assets.py).
"""
import atexit
import json
import logging
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from flask import Blueprint, Flask, Response, current_app, redirect, render_template_string, request, session
from werkzeug.wrappers import Response as WerkzeugResponse

from api.distributions import campaigns
from api.island_adventure import island_adventure
from api.island_peers import island_peers
from api.offline_friends import offline_friends
from api.player_guide import player_guide
from api.routes import HANDLERS, Query, load_handlers
from api.signup import signup
from api.visit_sync import visit_sync
from config import LANG, LANGUAGE_NAMES, WEB_PORTS, get_secret_key, normalize_language
from game_sync_server.entralinked.utility.db_manager import db
from utils.account_manager import accounts
from utils.assets import SITE_DIR, not_found, path_inside, resolve_static, serve_file, site_directories
from utils.patching import SWF_PATHS, get_patched_swf
from utils.web_network import is_web_host

# Copied from a real pdw1.pokemon-gl.com /api/ response
NO_CACHE_HEADERS = {
    "Expires": "Thu, 19 Nov 1981 08:52:00 GMT",
    "Cache-Control": "no-store, no-cache, must-revalidate, post-check=0, pre-check=0",
    "Pragma": "no-cache",
}

site = Blueprint("site", __name__)


# ---------------
# Before every request
# ---------------

@site.before_app_request
def rewrite_incoming_path() -> WerkzeugResponse | None:
    """Enforce a trailing slash on paths that map to a site directory."""
    path = request.path
    if not path.endswith("/") and next(site_directories(path.lstrip("/")), None):
        return redirect(f"{path}/", 301)
    return None


# ---------------
# The ?p=<endpoint> API
# ---------------

def _params(data: str) -> Query:
    return {name: values[0] for name, values in parse_qs(data, strict_parsing=True).items()}


def _call_api(method: str, query: Query) -> Response:
    api_name = query.get("p")
    if session.get("visit_guest") and api_name in {
        "pgl.top.login", "pgl.member.profile.init_create", "pgl.member.profile.gsid_create",
        "pgl.member.profile.gsid_switch",
    }:
        return Response('{"error":"visit_account_read_only"}', status=403, mimetype="application/json",
                        headers=NO_CACHE_HEADERS)
    logged_query = {name: "***" if "password" in name else value for name, value in query.items()}
    current_app.logger.info("API %s: %s %s", method, api_name, logged_query)

    handler = HANDLERS[method].get(api_name or "")
    if handler is None:
        current_app.logger.warning("Unknown API: %s %s", method, api_name)
        return Response("{}", status=501, content_type="application/json; charset=utf-8")

    return Response(json.dumps(handler(query)), content_type="application/json; charset=utf-8", headers=NO_CACHE_HEADERS)


@site.get("/api/")
def api_get() -> Response:
    """Handle an API call with its parameters in the query string."""
    return _call_api("GET", _params(request.query_string.decode()))


@site.post("/api/")
def api_post() -> Response:
    """Handle an API call with parameters in the query string and the form body."""
    return _call_api("POST", {**_params(request.query_string.decode()), **_params(request.get_data(as_text=True))})


# ---------------
# Site files
# ---------------

_LANGUAGE_PAGES = {"/", "/pdw/", "/introduction/", "/profile/", "/register/", "/login/pgl.html", "/player-guide/",
                   "/player-guide/phone/", "/report/", "/customize/", "/campaign/", "/help/", "/islands/"}


def _language_page() -> str:
    source = request.args.get("page") or urlsplit(request.referrer or "").path
    return source if source in _LANGUAGE_PAGES else "/"


@site.get("/languages/")
def languages() -> str:
    return render_template_string(
        '<!doctype html><html lang="{{lang}}"><meta charset="utf-8"><title>Pokémon Global Link</title>'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><main>'
        '<h1>Pokémon Global Link</h1><nav><ul>{% for code, name in names.items() %}'
        '<li><a lang="{{ "zh-CN" if code == "zh" else code }}" '
        'href="/languages/{{code}}/{% if page != "/" %}?page={{page}}{% endif %}">{{name}}</a></li>'
        '{% endfor %}</ul></nav></main></html>', lang="zh-CN" if LANG == "zh" else LANG, names=LANGUAGE_NAMES,
        page=_language_page(),
    )


@site.get("/languages/<code>/")
def change_language(code: str) -> Response:
    language = normalize_language(code)
    if language not in WEB_PORTS:
        return not_found(request.path)
    hostname = urlsplit(request.host_url).hostname
    if not hostname or not is_web_host(hostname):
        hostname = "127.0.0.1"
    if ":" in hostname:
        hostname = f"[{hostname}]"
    target = _language_page()
    return redirect(f"{request.scheme}://{hostname}:{WEB_PORTS[language]}{target}")


@site.get("/portal/login/pgl.html")
def archive_login() -> Response:
    return redirect("/login/pgl.html")


@site.get("/pglcheck")
def login_available() -> Response:
    return Response(status=204)


@site.route("/", defaults={"path": ""})
@site.route("/<path:path>")
def catch_all(path: str) -> Response:
    """Serve a patched SWF, a site directory's page, or a static asset for any other path."""
    if not path and request.args.get("p") == "logout":
        session.clear()
        response = redirect("/")
        response.headers["Cache-Control"] = "no-store"
        return response

    path = path.split("&")[0]
    full_path = f"/{path}"

    # return patched SWFs from our cache
    filename = Path(path).name
    if filename in SWF_PATHS:
        if LANG == "zh":
            override = path_inside(SITE_DIR, path)
            if override and override.is_file():
                return serve_file(override)
        return Response(get_patched_swf(filename), content_type="application/x-shockwave-flash")

    # find first HTML file inside given directory
    for dir_path in site_directories(path):
        index = min(dir_path.glob("*.html"), default=None)
        if index is not None:
            return serve_file(index)

    # static asset
    file_path = resolve_static(full_path)
    if file_path is None:
        return not_found(full_path)

    return serve_file(file_path)


# ---------------
# App
# ---------------

def create_app() -> Flask:
    """Create the Flask app."""
    load_handlers()

    app = Flask(__name__)
    app.logger.setLevel(logging.DEBUG if logging.getLogger().isEnabledFor(logging.DEBUG) else logging.INFO)
    app.secret_key = get_secret_key()
    app.register_blueprint(signup)
    app.register_blueprint(campaigns)
    app.register_blueprint(player_guide)
    app.register_blueprint(visit_sync)
    app.register_blueprint(offline_friends)
    app.register_blueprint(island_peers)
    app.register_blueprint(island_adventure)
    app.register_blueprint(site)

    @app.teardown_appcontext
    def close_connections(_exc: BaseException | None) -> None:
        # close the request thread's connections
        db.close()
        accounts.close()

    atexit.register(db.close)
    atexit.register(accounts.close)
    return app
