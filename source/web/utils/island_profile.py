"""Turn a signed island's public fields into localized, read-only display rows."""

import json
from datetime import UTC, datetime
from functools import cache

from config import LANGUAGE_NAMES, ROOT_DIR
from utils.gen5_names import display_nickname
from utils.language import LANGCODES

_CATALOG = {
    "rom_id": "game",
    "island_id": "decor",
    "shelf_id": "decor",
    "wateringpot_id": "decor",
    "pokemon_no": "pokemon",
    "ball_name": "ball",
    "personality": "nature",
    "type1": "type",
    "type2": "type",
    "favorite_medal": "medal",
    "move": "move",
    "loblolly_decor": "loblolly",
}
_FIELDS = (
    "pgl_name",
    "player_name",
    "rom_id",
    "langcode",
    "trainer_gender",
    "avator_id",
    "player_badge_num",
    "point",
    "experiment_point",
    "hours_played",
    "minutes_played",
    "sleep_pokemon_count",
    "send_pokemon_count",
    "member_created_at",
    "board_count",
    "sleeping_flag",
    "play_status",
    "levels_gained",
    "pending_partner_count",
    "pending_item_stacks",
    "loblolly_decor",
)
_SLEEPER = (
    "pokemon_no",
    "pokemon_nickname",
    "level",
    "form_no",
    "type1",
    "type2",
    "sex",
    "personality",
    "ball_name",
    "is_shiny",
)
_STATES = ("awake", "play_ready", "dreaming", "wake_ready")


@cache
def _names(lang: str, table: str) -> list[str]:
    return (ROOT_DIR / "raw_text" / lang / (table + ".txt")).read_text(encoding="utf-8").splitlines()


def _name(lang: str, table: str, number: int) -> str:
    names = _names(lang, table)
    return names[number] if 0 <= number < len(names) and names[number] else f"#{number}"


@cache
def _areas() -> dict:
    return json.loads((ROOT_DIR / "json_data/island_adventure.json").read_text(encoding="utf-8"))


def groups(content: dict, lang: str, labels: dict) -> list[tuple[str, list[tuple[str, str]]]]:
    if lang not in LANGUAGE_NAMES:
        raise ValueError("Unknown island language")

    def display(key: str, value) -> str:
        if key in _CATALOG:
            return _name(lang, _CATALOG[key], value)
        if key == "langcode":
            return LANGUAGE_NAMES.get(LANGCODES.get(value, ""), f"#{value}")
        if key in ("trainer_gender", "sex") and value < 3:
            return ("♂", "♀", labels["genderless"])[value]
        if key in ("is_shiny", "sleeping_flag", "selected"):
            return labels["yes" if value else "no"]
        if key == "play_status" and value < len(_STATES):
            return labels[_STATES[value]]
        if key in ("planted_at", "watered_at"):
            return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%d %H:%M UTC")
        return str(value)

    def fields(source: dict, keys: tuple[str, ...]) -> list[tuple[str, str]]:
        return [(labels[k], display(k, source[k])) for k in keys if source.get(k) not in (None, "")]

    profile = fields(content["profile"], _FIELDS)
    home = fields(content["island"], ("island_id", "shelf_id", "wateringpot_id"))
    home.append((labels["route_theme"], _areas()[lang]["areas"][content["theme"] - 3]))
    raw = content["sleeper"]
    name = display_nickname(raw.get("pokemon_nickname"), verified=raw.get("nickname_verified") is True)
    sleeper = fields({**raw, "pokemon_nickname": name}, _SLEEPER)

    decor = []
    for obj in content["decor"]:
        position = f"({obj['x']}, {obj['y']})" if "x" in obj else labels["stored"]
        decor.append((_name(lang, "decor", obj["interior_id"]), position))
    garden = []
    for plot in content["garden"]:
        parts = [_name(lang, "item", plot["pokeitem_id"]) if "pokeitem_id" in plot else labels["empty_plot"]]
        if "kinomi_state" in plot:
            parts.append(f"{labels['growth']} {plot['kinomi_state']}/4")
        if "dirt_hp" in plot:
            parts.append(f"{labels['moisture']} {plot['dirt_hp']}%")
        parts.extend(f"{label} {value}" for label, value in fields(plot, ("planted_at", "watered_at")))
        garden.append((f"({plot['x']}, {plot['y']})", " · ".join(parts)))
    shelf = [
        (
            _name(lang, "item", obj["item_id"]),
            f"({obj['x']}, {obj['y']})" if "x" in obj and "y" in obj else labels["shelf"],
        )
        for obj in content["shelf"]
    ]
    chest = [(_name(lang, "item", obj["pokeitem_id"]), f"×{obj['item_cnt']}") for obj in content["chest"]]
    board = []
    for friend in content["board"]:
        details = fields(friend, ("form_no", "move", "met_at", "sent_at", "selected"))
        board.append((_name(lang, "pokemon", friend["pokemon_no"]), " · ".join(f"{key} {val}" for key, val in details)))
    medals = [(_name(lang, "medal", medal), f"#{medal}") for medal in content["medals"]]
    medals.extend(fields(content, ("favorite_medal",)))
    sections = (
        ("profile", profile),
        ("room", home),
        ("sleeper", sleeper),
        ("decor", decor),
        ("garden", garden),
        ("shelf", shelf),
        ("chest", chest),
        ("board", board),
        ("medals", medals),
    )
    return [(labels[key], values) for key, values in sections if values]
