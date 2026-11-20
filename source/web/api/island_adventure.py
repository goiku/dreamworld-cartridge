"""A visitor's footprint trail, using the home's own Dream Tree and cartridge queue."""
import hashlib
import random
import secrets
from pathlib import Path

from flask import Blueprint, Response, abort, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.wrappers import Response as WerkzeugResponse

from api import pdw_dreamland as dream
from api.pdw_home import pdw_end, pdw_start
from api.pgl_pals import current_save
from config import LANG, ROOT_DIR
from game_sync_server.entralinked.utility.db_manager import db
from utils import managers, save_data, text
from utils.berries import is_berry
from utils.constants import PlayerStatus, is_b2w2
from utils.data import load_json_data
from utils.models import Member
from utils.offline_islands import IslandNotFound, get_friend

island_adventure = Blueprint("island_adventure", __name__, template_folder="../templates",
                             static_folder="../static", static_url_path="/islands/adventure-assets")
_labels = load_json_data("island_adventure")
_footprints = ROOT_DIR / "dreamworld_assets/shared.pokemon-gl.com/report/assets/images/footprint"


def _my_card() -> str:
    code = current_save()
    if not code or session.get("visit_guest"):
        abort(403, _labels[LANG]["home_login"])
    return code


def _choose_content(snapshot: dict, member: Member) -> dict:
    """Pick an original encounter eligible for the visitor's cartridge and progress."""
    content = snapshot["content"]
    preferred = [content["sleeper"], *reversed(content["board"])]
    landscape = str(content["theme"])
    sequel = is_b2w2(member["rom_id"])
    offset = dream.B2W2_AREA_OFFSET if sequel else 0
    pools = {
        region: [entry for slot in dream._DREAMLAND["areas"][str(int(region) + offset)]
                 if dream._SLOTS[slot]["min_points"] <= member["experiment_point"]
                 for entry in dream._SLOTS[slot]["contents"] if "pokemon_no" in entry]
        for region in dream.accessible_areas(member, "b2w2" if sequel else "bw")
    }
    # Pick a display Pokémon where the original game has a matching encounter.
    # Otherwise the visitor encounters a native species from the shared landscape.
    catalog = [entry for pool in pools.values() for entry in pool]
    area = pools.get(landscape) or catalog
    for display in preferred:
        if "pokemon_no" in display:
            species = display["pokemon_no"], display.get("form_no", 0)
            match = [entry for entry in catalog if (entry["pokemon_no"], entry["form_no"]) == species]
            if match:
                area = match
                break
    seed = f'{snapshot["island_id"]}:{snapshot["version"]}'.encode()
    number = int.from_bytes(hashlib.sha256(seed).digest(), "big")
    return area[number % len(area)]


def _print_art(species: int) -> Path:
    return _footprints / f"{species:03}.png"


def _new_trail(snapshot: dict, member: Member) -> dict:
    content = _choose_content(snapshot, member)
    species = content["pokemon_no"]
    own_print = _print_art(species)
    # Some species have no visible foot. In those cases the trail uses a guide Pokémon's tracks.
    target = species if own_print.is_file() and own_print.stat().st_size > 120 else 25
    other_prints = [i for i in (6, 25, 54, 173, 9) if _print_art(i).read_bytes() != _print_art(target).read_bytes()]
    rng = random.SystemRandom()
    choices = [target, *rng.sample(other_prints, 2)]
    rng.shuffle(choices)
    return {"version": snapshot["version"], "theme": snapshot["content"]["theme"],
            "object_id": content["object_pokemon_id"], "target": target, "choices": choices, "friend_id": None}


def _playing(member: Member) -> bool:
    return bool(member.get("sleeping_flag") and not member.get("wake_download_pending") and not member.get("is_downloaded")
                and member.get("play_status") in (PlayerStatus.PLAY_READY, PlayerStatus.DREAMING))


def _stage(member: Member, state: dict, trail: dict) -> str:
    chosen = state["wished"]
    if chosen is not None and chosen == trail.get("friend_id"):
        return "wished" if _playing(member) else "finished"
    if not _playing(member):
        return "sleep"
    if chosen is not None:
        return "other"
    if trail.get("friend_id"):
        return "met"
    return "track" if trail else "new"


@island_adventure.route("/islands/<island_id>/adventure", methods=["GET", "POST"])
def adventure(island_id: str) -> str | WerkzeugResponse:
    code = _my_card()
    try:
        snapshot = get_friend(code, island_id)
    except IslandNotFound:
        abort(404)
    csrf = session.setdefault("adventure_csrf", secrets.token_hex(24))
    labels = _labels[LANG]
    if request.method == "POST":
        if not secrets.compare_digest(csrf.encode(), request.form.get("csrf", "").encode()):
            abort(403)
        _act(code, island_id, snapshot, labels)
        return redirect(url_for(".adventure", island_id=island_id), 303)
    data = save_data.read_player_data(code)
    member = data["member"]
    state = dream._island_state(data)
    trail = state.get("island_trails", {}).get(island_id, {})
    stage = _stage(member, state, trail)
    encounter = dream._CONTENTS[trail["object_id"]] if trail else {}
    berries = [item for item in managers.get_chest(code).data["list"]
               if is_berry(item["pokeitem_id"]) and item["item_cnt"] > 0] if stage == "met" else []
    notice = session.pop("adventure_notice", None)
    return render_template("island_adventure.html", t=labels, lang=LANG, csrf=csrf, island_id=island_id,
                           owner=snapshot["content"]["profile"].get("pgl_name"), trail=trail, stage=stage,
                           theme=labels["areas"][trail.get("theme", snapshot["content"]["theme"]) - 3],
                           tuck=member["sleep_pokemon_count"], notice=notice, berries=berries,
                           species=text.lookup_str("pokemon", encounter["pokemon_no"]) if encounter else "")


def _act(code: str, island_id: str, snapshot: dict, labels: dict) -> None:
    with db.transaction():
        data = save_data.read_player_data(code)
        member = data["member"]
        tuck = member["sleep_pokemon_count"]
        if request.form.get("tuck") != str(tuck):
            abort(409, labels["sleep"])
        state = dream._island_state(data)
        trails = state.setdefault("island_trails", {})
        trail = trails.get(island_id, {})
        stage = _stage(member, state, trail)
        action = request.form.get("action")
        if action == "start":
            if stage == "new":
                if not member.get("first_flag"):
                    pdw_start({})  # The same one-time starter Berries as entering the original game.
                trails[island_id] = _new_trail(snapshot, member)
                dream._save_island(state)
            elif not trail:
                abort(409, labels[stage])
        elif action == "track" and stage in ("track", "met"):
            if stage == "track":
                if request.form.get("track") != str(trail["target"]):
                    session["adventure_notice"] = labels["retry"]
                    return
                content = dream._CONTENTS[trail["object_id"]]
                ident = db.next_id("dream_encounter_id")[0]
                state["friends"].append({"id": ident, "object_id": trail["object_id"],
                                         "move": dream._special_move(content, 3), "met_at": save_data.now_jst_str()[:16]})
                trail["friend_id"] = ident
                dream._save_island(state)
        elif action == "wish" and stage in ("met", "wished", "finished"):
            if stage == "met":
                if len(save_data.read_game_sync().get("encounters", [])) >= 10:
                    abort(409, labels["queue_full"])
                berry = request.form.get("berry", "")
                if not berry.isascii() or not berry.isdecimal() or len(berry) > 3 or not is_berry(int(berry)):
                    abort(400)
                dream.tree_offer({"get_pokemon_id": str(trail["friend_id"]), "pokeitem_id": berry})
        elif action == "finish" and stage in ("wished", "finished"):
            if stage == "wished":
                pdw_end({})
        else:
            abort(409, labels["stale"])


_VISIT_MOVIES = {"/src/swf/theme/assets/common/main.swf": "main",
                 "/src/swf/pdw/assets/pdw_main.swf": "pdw_main"}
_VISIT_GET = {"pdw.home.friend_island": "friend_member_savedata_id",
              "pdw.home.friend_island_area": "friend_member_savedata_id",
              "pdw.home.friend_friend_list": "friend_member_savedata_id",
              "pdw.home.friend_bridge": "friend_member_savedata_id",
              "pdw.item.friend_trade_list": "other_member_savedata_id",
              "pdw.croft.friend_croft_list": "member_savedata_id"}
_pal_labels = load_json_data("offline_islands_ui")


@island_adventure.before_app_request
def prepare_visit() -> Response | None:
    from api.offline_friends import native_info
    from utils.native_movies import visit_movie

    if request.path in _VISIT_MOVIES and request.args.get("dw-visit") == "1":
        response = Response(visit_movie(_VISIT_MOVIES[request.path]), mimetype="application/x-shockwave-flash")
        response.add_etag()
        response.cache_control.public = True
        response.cache_control.max_age = 0
        return response.make_conditional(request)
    if request.path in ("/pdw/", "/pdw/index.html") and "island" in request.args:
        from api.pdw_home import _island_pokemon
        from utils.pokemon import get_sleeper

        g.island_target = native_info(request.args["island"]).get_json()
        g.island_target["visitor_pokemon"] = _island_pokemon(get_sleeper())
    return None


@island_adventure.route("/islands/<island_id>/game-api/", methods=["GET", "POST"])
def visit_api(island_id: str) -> Response:
    """The read-only movie has its own API URL, including on tabs with an awake cartridge."""
    from api.native_islands import read_only
    from api.pgl_top import init as pgl_init
    from api.offline_friends import native_info
    from api.routes import HANDLERS

    meta = native_info(island_id).get_json()
    action = request.args.get("p", "")
    arg = _VISIT_GET.get(action)
    if request.method == "GET" and action == "pgl.top.init":
        result = pgl_init({}, settle_items=False)
    elif request.method == "GET" and arg and request.args.get(arg) == str(meta["member_savedata_id"]):
        result = HANDLERS["GET"][action](request.args.to_dict())
    elif request.method == "GET" and action in ("pdw.home.friend_list", "pdw.home.my_island_area"):
        result = HANDLERS["GET"][action](request.args.to_dict())
    else:
        result = read_only("invalid_access")
    response = jsonify(result)
    response.cache_control.no_store = True
    return response


@island_adventure.after_app_request
def bridge_menu(response: Response) -> Response:
    if request.path not in ("/pdw/", "/pdw/index.html") or response.status_code != 200 or response.mimetype != "text/html":
        return response
    html = response.get_data()
    pos = html.lower().find(b"<div", html.lower().find(b"<body"))
    if pos >= 0:
        menu = render_template("island_bridge_menu.html", s=_pal_labels[LANG], ui=load_json_data("island_actions")[LANG],
                               target=getattr(g, "island_target", None))
        response.set_data(html[:pos] + menu.encode("ascii", "xmlcharrefreplace") + html[pos:])
        response.cache_control.no_store = True
    return response
