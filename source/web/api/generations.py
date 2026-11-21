"""Shared entry point for the Nintendo DS games and the Gen IV wireless catalog."""
from flask import Blueprint, redirect, render_template, request

from config import LANG, LANGUAGE_NAMES
from utils import gen4_gifts, text
from utils.data import load_json_data

generations = Blueprint("generations", __name__, template_folder="../templates", static_folder="../static",
                        static_url_path="/generation-assets")
_labels = load_json_data("generation_portal")
GAME_CODES = ("ADA", "APA", "CPU", "IPK", "IPG")
LANG_CODES = {"ja": "J", "en": "E", "fr": "F", "it": "I", "de": "D", "es": "S", "ko": "K"}
_ITEMS = {"OaksLetter": 452, "MemberCard": 454, "SecretKey": 467, "EnigmaStone": 536}
_POKEMON = {"10AnnivMew": 151, "AshPikachu": 25, "GooneScizor": 212, "Jirachi_NightSky": 385,
            "NZ_Jirachi": 385, "NZ_Manaphy": 490, "ShinyEntei": 244, "ShinyPichu": 172,
            "ShinyRaikou": 243, "ShinySuicune": 245}


def _card_title(filename, labels):
    _, number, _, event = filename[:-4].split("_", 3)
    if event in _ITEMS:
        name = text.lookup_str("item", _ITEMS[event], language=LANG)
    elif event in _POKEMON:
        name = text.lookup_str("pokemon", _POKEMON[event], language=LANG)
    else:
        name = labels[event]
    return number, name


def page(four=False):
    t = _labels[LANG]
    version = request.args.get("game", "CPU")
    language = request.args.get("language", LANG if LANG in LANG_CODES else "ja")
    code = (version if version in GAME_CODES else "CPU") + LANG_CODES.get(language, "J")
    archive = gen4_gifts.catalog()
    cards = [archive["files"][key][1] for key in archive["games"][code]] if four else []
    return render_template("generations.html", four=four, t=t, lang=LANG, names=LANGUAGE_NAMES, code=code,
                           friends=load_json_data("offline_islands_ui")[LANG]["friends"],
                           arcade=load_json_data("practice")[LANG]["title"],
                           versions=dict(zip(GAME_CODES, t["versions"])), languages=LANG_CODES,
                           cards=[_card_title(name, t) for name in cards])


@generations.get("/gen4/")
def gen4():
    return page(True)


@generations.get("/gen5/")
def gen5():
    # The archive uses root-relative and document-relative links on the same page.
    return redirect("/index.html")
