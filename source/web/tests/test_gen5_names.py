import json
from dataclasses import asdict

import pytest

from config import ROOT_DIR
from game_sync_server.entralinked.model.save_file import Pokemon
from game_sync_server.entralinked.network.http.pgl_handler import _pkmn_info
from utils import pokemon
from utils.gen5_names import display_nickname
from utils.island_profile import groups


@pytest.mark.parametrize(
    ("source", "display"), [
        ("ゆめ☆", "ゆめ☆"), ("夢の森", "夢の森"), ("피카츄", "피카츄"), ("Étoile", "Étoile"),
        ("E\u0301toile", "Étoile"), ("Señor♂", "Señor♂"), ("A⑭⑮", "A♂♀"), ("♀★♥", "♀★♥"),
        ("A?", "A?"), ("?", "?"), ("???", None), ("汉A", None), ("N龙", None), ("A\uE08E", None),
        ("A\uFFFD", None), ("A\u202E", None), ("A\x00B", None), ("\ud800", None),
        ("🚀", None), (None, None), ("  ", None),
    ],
)
def test_faithful_glyphs_or_no_nickname(source, display):
    assert display_nickname(source) == display


def upload(nickname):
    data = bytearray(136)
    data[0x08:0x0A] = (173).to_bytes(2, "little")
    for offset, value in ((0x48, nickname), (0x68, "Owner")):
        field = value.encode("utf-16le") + b"\xff\xff"
        data[offset:offset + len(field)] = field
    return asdict(_pkmn_info(Pokemon(bytes(data))))


def test_new_upload_distinguishes_replacement_from_real_question_marks(monkeypatch):
    monkeypatch.setattr(pokemon.text, "lookup_str", lambda _table, _number: "皮宝宝")
    unknown = upload("A\uE000B")
    literal = upload("???")
    assert literal["nickname_verified"] and unknown["nickname_verified"]
    assert literal["pokemon_nickname"] == "???"
    assert unknown["pokemon_nickname"] == ""
    assert unknown["oyaname"] == literal["oyaname"] == "Owner"
    assert pokemon.localized_sleeper(unknown)["pokemon_nickname"] == "皮宝宝"
    assert unknown["pokemon_nickname"] == ""
    assert pokemon.localized_sleeper(literal)["pokemon_nickname"] == "???"
    assert pokemon.localized_sleeper({"pokemon_no": 173, "pokemon_nickname": "???"})["pokemon_nickname"] == "皮宝宝"


def test_old_snapshot_uses_viewers_species_name_and_preserves_signed_fields():
    content = {
        "profile": {"pgl_name": "Iris", "langcode": 1}, "island": {"island_id": 201, "shelf_id": 301},
        "theme": 7, "sleeper": {"pokemon_no": 173, "pokemon_nickname": "A汉"},
        "decor": [], "garden": [], "shelf": [], "chest": [], "board": [], "medals": [], "favorite_medal": None,
    }
    doc = json.loads((ROOT_DIR / "json_data/offline_islands_ui.json").read_text(encoding="utf8"))
    for lang, species in (("zh", "皮宝宝"), ("ja", "ピィ"), ("en", "Cleffa")):
        labels = doc[lang]
        sleeper = dict(dict(groups(content, lang, labels))[labels["sleeper"]])
        assert sleeper[labels["pokemon_no"]] == species
        assert labels["pokemon_nickname"] not in sleeper
    assert content["sleeper"]["pokemon_nickname"] == "A汉"
