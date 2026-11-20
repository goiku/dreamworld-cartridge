"""pgl.present.*: the Customize page (present.swf) for picking C-Gear skins, Pokédex skins, and Musicals."""
import secrets
from functools import cache
from pathlib import Path, PurePosixPath
from typing import Literal

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, session, url_for

from api.pgl_pals import current_save
from api.routes import Query, endpoint
from config import ASSET_LANG, LANG, ROOT_DIR
from utils import save_data
from utils.constants import is_b2w2
from utils.data import load_json_data
from utils.language import LANGCODES
from utils.models import GameSync, Member

_IMG_DIR = (ROOT_DIR / "dreamworld_assets" / f"{ASSET_LANG}.pokemon-gl.com"
            / "src" / "swf" / "customize" / "assets" / ASSET_LANG / "img")

_PRESENTS: dict[str, dict] = load_json_data("customize")
_CHINESE_NAMES: dict[str, str] = load_json_data("customize_zh") if LANG == "zh" else {}
customize = Blueprint("customize", __name__, template_folder="../templates")
_UI = load_json_data("customize_ui")[LANG]

_SkinField = Literal["cgear_skin", "dex_skin", "musical"]

# category -> GameSync field. present_list calls the category's list <category>_list,
# and present_dldata_update takes its pick as <category>_id.
_CATEGORIES: dict[str, _SkinField] = {
    "cgear":   "cgear_skin",
    "zukan":   "dex_skin",
    "musical": "musical",
}


def _musical_file(entry: dict) -> str | None:
    """Return the URL of the Musical's mp3, which sits next to its thumbnail."""
    thumb = entry["data"][ASSET_LANG][2]
    if entry["type"] != "MUSICAL" or not thumb:
        return None
    mp3 = min((_IMG_DIR / thumb).parent.glob("*.mp3"), default=None)
    return "/" + mp3.relative_to(_IMG_DIR).as_posix() if mp3 else None


_MUSICAL_FILES = {present_id: _musical_file(entry) for present_id, entry in _PRESENTS.items()}


def _dlc_filenames(entry: dict) -> list[str]:
    """Return the file names in every language."""
    return [PurePosixPath(file).name for _, file, _ in entry["data"].values() if file]


def _dlc_filename(entry: dict, member: Member) -> str | None:
    """Choose the file the linked cartridge can download."""
    language = LANGCODES.get(member.get("langcode"), ASSET_LANG)
    file = entry["data"][language][1]
    return PurePosixPath(file).name if file else None


def _folder(category: str, member: Member) -> str:
    """Return the customize.json type that holds the category's skins for the player's game."""
    if category == "cgear":
        return "CGEAR2" if is_b2w2(member.get("rom_id")) else "CGEAR"
    return category.upper()


def _offered(entry: dict, category: str, member: Member) -> bool:
    """Return whether a DLC is valid for the player's game."""
    trainer_gender = "female" if member.get("trainer_gender") == 1 else "male"
    return entry["type"] == _folder(category, member) and entry.get("gender", trainer_gender) == trainer_gender


def _name(entry: dict, present_id: str) -> str:
    """Return the DLC's name in the site language, else in English."""
    if LANG == "zh":
        return _CHINESE_NAMES[present_id]
    return entry["data"][LANG][0] or entry["data"]["en"][0]


def _entry(present_id: str, entry: dict, member: Member) -> dict | None:
    """Build the DLC's present_list item.

    Return None if the site language lacks its file or thumbnail."""
    thumb = entry["data"][ASSET_LANG][2]
    if thumb is None or _dlc_filename(entry, member) is None:
        return None
    item = {
        "present_id":   present_id,
        "present_file": "/" + thumb,
        "present_name": _name(entry, present_id),
        "is_select":    "0",
    }
    if musical_file := _MUSICAL_FILES[present_id]:
        item["musical_file"] = musical_file
    return item


@endpoint("pgl.present.present_list")
def present_list(_query: Query) -> dict:
    """Return the C-Gear skins, Pokédex skins, and Musicals the player can pick."""
    game_sync = save_data.read_game_sync()
    member = save_data.read_member()
    response = {}
    # basic/default skins first, then the rest in customize.json order
    presents = sorted(_PRESENTS.items(), key=lambda item: not item[1].get("default"))
    for category, field in _CATEGORIES.items():
        selected = game_sync.get(field)
        items = []
        for present_id, entry in presents:
            item = _entry(present_id, entry, member) if _offered(entry, category, member) else None
            if item is None:
                continue

            if selected in _dlc_filenames(entry):
                item["is_select"] = "1"
                selected = None
            items.append(item)
        response[f"{category}_list"] = items
    return response


@endpoint("pgl.present.present_dldata_update", methods=("POST",))
def present_dldata_update(query: Query) -> dict:
    """Store the file names of the DLC the player picked, for Game Sync to send."""
    member = save_data.read_member()
    changes: GameSync = {}
    for category, field in _CATEGORIES.items():
        entry = _PRESENTS.get(query.get(f"{category}_id") or "")
        if entry is None or not _offered(entry, category, member):
            continue
        dlc = _dlc_filename(entry, member)
        if dlc:
            changes[field] = dlc
    if changes:
        save_data.change_game_sync(lambda game_sync: game_sync.update(changes))
    return {}


@cache
def _preview(present_id: str) -> Path | None:
    # Some mirrors (especially English) kept the catalog but lost the image.
    # Other regional archives sometimes carry the exact same thumbnail.
    data = _PRESENTS[present_id]["data"]
    thumb = data[ASSET_LANG][2]
    if not thumb:
        return None
    for code in dict.fromkeys((ASSET_LANG, *data)):
        if data[code][2] == thumb:
            path = (ROOT_DIR / "dreamworld_assets" / f"{code}.pokemon-gl.com" / "src/swf/customize/assets"
                    / code / "img" / thumb)
            if path.is_file():
                return path
    return None


@customize.get("/customize/preview/<present_id>")
def preview(present_id: str):
    if present_id not in _PRESENTS or not (path := _preview(present_id)):
        abort(404)
    return send_file(path, conditional=True)


@customize.get("/customize/index.html")
def archive_index():
    return redirect(url_for(".index"))


@customize.route("/customize/", methods=["GET", "POST"])
def index():
    category = request.args.get("kind", "cgear")
    if category not in _CATEGORIES:
        abort(404)
    card = current_save()
    member = save_data.read_member(card) if card else {}
    ready = bool(card and member.get("rom_id") and member.get("langcode"))
    items = present_list({})[category + "_list"] if ready else []
    if request.method == "POST":
        token = session.get("customize_csrf")
        if (not ready or request.form.get("card") != card or not token or
                not secrets.compare_digest(token.encode(), request.form.get("csrf", "").encode())):
            abort(403)
        choice = request.form.get("choice")
        if choice == "none":
            save_data.change_game_sync(lambda sync: sync.update({_CATEGORIES[category]: None}))
        elif any(item["present_id"] == choice for item in items):
            present_dldata_update({category + "_id": choice})
        else:
            abort(400)
        flash(_UI["saved"], "customize")
        return redirect(url_for(".index", kind=category), code=303)

    if ready and "customize_csrf" not in session:
        session["customize_csrf"] = secrets.token_urlsafe()
    for item in items:
        item["preview"] = bool(_preview(item["present_id"]))
    return render_template("customize.html", t=_UI, guide=load_json_data("distribution_ui")[LANG],
                           lang=LANG, asset_lang=ASSET_LANG, card=card, ready=ready, category=category,
                           items=items, categories=_CATEGORIES, selected=any(i["is_select"] == "1" for i in items))
