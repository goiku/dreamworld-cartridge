import json

import pytest

from config import LANGUAGE_NAMES, ROOT_DIR
from utils.island_profile import groups


@pytest.fixture
def content():
    return {
        "profile": {
            "pgl_name": "Iris", "rom_id": 21, "langcode": 1, "sleeping_flag": 1, "play_status": 2,
            "levels_gained": 0, "pending_partner_count": 1, "pending_item_stacks": 2, "loblolly_decor": 1,
        },
        "island": {"island_id": 201, "shelf_id": 301, "wateringpot_id": 1},
        "theme": 8,
        "sleeper": {"pokemon_no": 173, "sex": 2, "level": 19, "personality": 0, "is_shiny": False},
        "garden": [{"x": 0, "y": 0, "pokeitem_id": 149, "dirt_hp": 66, "kinomi_state": 3,
                    "planted_at": 60, "watered_at": 120}, {"x": 1, "y": 0}],
        "decor": [{"interior_id": 201}, {"interior_id": 301, "x": 0, "y": 14}],
        "shelf": [{"item_id": 149, "x": 0, "y": 1}],
        "chest": [{"pokeitem_id": 149, "item_cnt": 7}],
        "board": [{"pokemon_no": 173, "form_no": 0, "move": 1, "met_at": "2020-01-01",
                   "sent_at": "2020-01-02", "selected": True}],
        "medals": [1, 2], "favorite_medal": 1,
    }


@pytest.mark.parametrize("lang", LANGUAGE_NAMES)
def test_snapshot_records_use_the_visitors_language(lang, content):
    labels = json.loads((ROOT_DIR / "json_data/offline_islands_ui.json").read_text(encoding="utf8"))[lang]
    rows = {title: dict(pairs) for title, pairs in groups(content, lang, labels)}

    def raw(table, index):
        return (ROOT_DIR / "raw_text" / lang / (table + ".txt")).read_text(encoding="utf8").splitlines()[index]

    profile = rows[labels["profile"]]
    assert profile[labels["rom_id"]] == raw("game", 21)
    assert profile[labels["langcode"]] == "日本語"
    assert profile[labels["loblolly_decor"]] == raw("loblolly", 1)
    assert profile[labels["levels_gained"]] == "0"
    assert profile[labels["pending_partner_count"]] == "1"
    assert profile[labels["pending_item_stacks"]] == "2"
    assert profile[labels["play_status"]] == labels["dreaming"]
    assert rows[labels["room"]][labels["wateringpot_id"]] == raw("decor", 1)
    assert rows[labels["sleeper"]][labels["pokemon_no"]] == raw("pokemon", 173)
    assert rows[labels["sleeper"]][labels["sex"]] == labels["genderless"]
    assert rows[labels["sleeper"]][labels["is_shiny"]] == labels["no"]
    assert labels["move"] not in rows[labels["sleeper"]]
    assert rows[labels["garden"]]["(1, 0)"] == labels["empty_plot"]
    cultivated = rows[labels["garden"]]["(0, 0)"]
    assert all(text in cultivated for text in (raw("item", 149), "66%", "3/4", "00:01 UTC", "00:02 UTC"))
    assert rows[labels["chest"]][raw("item", 149)] == "×7"
    assert rows[labels["shelf"]][raw("item", 149)] == "(0, 1)"
    assert labels["stored"] in rows[labels["decor"]].values()
    friend = rows[labels["board"]][raw("pokemon", 173)]
    assert all(text in friend for text in (raw("move", 1), "2020-01-01", "2020-01-02", labels["yes"]))
    assert rows[labels["medals"]][labels["favorite_medal"]] == raw("medal", 1)


def test_old_snapshot_with_missing_values_and_unknown_item(content):
    labels = json.loads((ROOT_DIR / "json_data/offline_islands_ui.json").read_text(encoding="utf8"))["ja"]
    content.update(sleeper={}, board=[], medals=[], favorite_medal=None, chest=[{"pokeitem_id": 9000, "item_cnt": 2}])
    content["profile"]["player_name"] = ""
    rows = dict(groups(content, "ja", labels))
    assert labels["medals"] not in rows
    assert labels["sleeper"] not in rows
    assert labels["board"] not in rows
    assert labels["player_name"] not in dict(rows[labels["profile"]])
    assert rows[labels["chest"]] == [("#9000", "×2")]
