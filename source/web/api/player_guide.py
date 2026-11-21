"""Player instructions embedded in the archived site, with live DNS for the local console."""
import json
import re
from functools import cache
from html import escape
from urllib.parse import urlsplit

from flask import Blueprint, Response, jsonify, render_template, request, url_for

from api.distributions import labels as distribution_labels
from api.pgl_pals import current_save
from config import LANG, LANGUAGE_NAMES, ROOT_DIR, WEB_PORTS
from utils import save_data
from utils.constants import PlayerStatus
from utils.data import load_json_data
from utils.player_dns import emulator_dns, get_player_dns
from utils.web_network import LOCAL_HOSTS, lan_web_address, same_web_lan

player_guide = Blueprint("player_guide", __name__, url_prefix="/player-guide",
                         template_folder="../templates", static_folder="../static", static_url_path="/assets")
_messages = json.loads((ROOT_DIR / "json_data/player_guide.json").read_text(encoding="utf-8"))
_contexts = {
    "/": ("home_tip", "dns"),
    "/introduction/": ("home_tip", "account"),
    "/login/pgl.html": ("login_tip", "account"),
    "/register/": ("register_tip", "register"),
    "/profile/": ("register_tip", "register"),
    "/pdw/": ("dream_tip", "dream"),
}


@cache
def _friends_label() -> str:
    return load_json_data("offline_islands_ui")[LANG]["friends"]


@player_guide.get("/")
def guide() -> str:
    return render_template("player_guide.html", t=_messages[LANG], lang=LANG,
                           language_names=LANGUAGE_NAMES, gifts=distribution_labels())


@player_guide.get("/phone/")
def phone() -> str:
    hostname = urlsplit(request.host_url).hostname
    direct = hostname in LOCAL_HOSTS and request.remote_addr in ("127.0.0.1", "::1")
    address = lan_web_address() if direct or same_web_lan(request.remote_addr, hostname) else None
    return render_template("phone_access.html", t=_messages[LANG], lang=LANG, language_names=LANGUAGE_NAMES,
                           phone_url=f"http://{address}:{WEB_PORTS[LANG]}/" if address else None)


@player_guide.get("/dns.json")
def dns() -> Response:
    response = jsonify(get_player_dns(request.remote_addr, urlsplit(request.host_url).hostname))
    response.cache_control.no_store = True
    return response


@player_guide.get("/emulator-dns.json")
def local_emulator_dns() -> Response:
    response = jsonify(emulator_dns(request.remote_addr, urlsplit(request.host_url).hostname))
    response.cache_control.no_store = True
    return response


def _wake_panel(data: bytes, t: dict) -> bytes | None:
    card = current_save()
    if not card:
        return None
    member = save_data.read_member(card)
    if member.get("play_status") != PlayerStatus.WAKE_READY and not member.get("wake_download_pending"):
        return None
    # Keep the archive's header, account controls and footer. The old entry movie
    # tries to start a dreaming session again after the card has committed to waking.
    start = data.find(b'<div id="main">')
    end = data.find(b'<div id="footer">', start)
    if start < 0 or end < 0:
        return None
    section = render_template("pdw_wake_ready.html", t=t, gifts=distribution_labels())
    return data[:start] + section.encode("ascii", "xmlcharrefreplace") + data[end:]


@player_guide.after_app_request
def insert_player_help(response: Response) -> Response:
    if response.mimetype != "text/html" or response.status_code not in (200, 400):
        return response
    path = request.path.removesuffix("index.html")
    context = _contexts.get(path)
    if request.endpoint in ("signup.trainer_club_signup", "signup.trainer_club_confirmation"):
        context = ("login_tip", "account")
    if context is None:
        return response
    # The home page carries the help when it embeds the original narrow login widget.
    if path == "/login/pgl.html" and request.headers.get("Sec-Fetch-Dest") == "iframe":
        response.vary.add("Sec-Fetch-Dest")
        return response
    tip, section = context
    t = _messages[LANG]
    guide_url = url_for("player_guide.guide")
    css = url_for("player_guide.static", filename="player-guide.css")
    guide_section = "console" if section == "dns" else section
    friends_link = ""
    if path in ("/", "/pdw/", "/profile/"):
        friends_link = f'<a href="/islands/">{escape(_friends_label())}</a>'
        friends_link += f'<a href="/campaign/">{escape(distribution_labels()["title"])}</a>'
        from api.practice import labels as practice_labels
        friends_link += f'<a href="/practice/">{escape(practice_labels()["title"])}</a>'
        friends_link += f'<a target="_blank" rel="noopener" href="{guide_url}#tuck-in">{escape(t["tuck_title"])}</a>'
    data = response.get_data()
    visit = path == "/pdw/" and "island" in request.args
    wake = _wake_panel(data, t) if path == "/pdw/" and not visit else None
    if wake is not None:
        data = wake
        response.cache_control.no_store = True
    tip_html = "" if visit or wake is not None else f"<span>{escape(t[tip])}</span>"
    banner = (f'<aside class="dw-player-help" lang="{LANG}">{tip_html}<nav>'
              f'{friends_link}'
              f'<a target="_blank" rel="noopener" href="{guide_url}#dns">{escape(t["dns_title"])}</a>'
              f'<a target="_blank" rel="noopener" href="{url_for("player_guide.phone")}">{escape(t["phone_title"])}</a>'
              f'<a target="_blank" rel="noopener" href="{guide_url}#{guide_section}">{escape(t["details"])}</a>'
              '</nav></aside>')
    stylesheet = f'<link rel="stylesheet" href="{css}">'.encode("ascii")
    head_end = re.search(rb"</head\s*>|<main\b", data, re.I)
    if head_end:
        data = data[:head_end.start()] + stylesheet + data[head_end.start():]
    # Keep the entire game canvas and the archived form in their original containers.
    # Character references preserve the various encodings of the archived pages.
    if path == "/login/pgl.html":
        marker = rb"</body\s*>"
        if request.headers.get("Sec-Fetch-Dest") == "document":
            data = re.sub(rb"<body\b", b"<body data-dw-login", data, count=1, flags=re.I)
            data = re.sub(rb"</head>", b'<meta name="viewport" content="width=device-width,initial-scale=1"></head>',
                          data, count=1, flags=re.I)
        else:
            banner = banner.replace('class="dw-player-help"', 'class="dw-player-help dw-login-help"')
        response.vary.add("Sec-Fetch-Dest")
    elif request.endpoint == "signup.trainer_club_signup":
        marker = rb'<div\s+id=["\']container["\']'
    elif request.endpoint == "signup.trainer_club_confirmation":
        marker = rb"</main\s*>"
    else:
        marker = rb'<div\s+id=["\']main["\']'
    at = re.search(marker, data, re.I) or re.search(rb"</body\s*>", data, re.I)
    if at:
        data = data[:at.start()] + banner.encode("ascii", "xmlcharrefreplace") + data[at.start():]
        response.set_data(data)
    return response
