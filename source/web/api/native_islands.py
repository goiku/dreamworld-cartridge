"""Adapt a shared Dream Pal to the original Dream World map, island and room scenes."""
import re
import secrets

from flask import session

from api.pgl_pals import current_save
from game_sync_server.entralinked.utility.db_manager import db
from utils import offline_islands as islands
from utils import pokemon, text, visits
from utils.decor import CATALOG, arranged_entry
from utils.gen5_names import display_nickname
from utils.messages import message


def resident() -> str | None:
    return None if session.get("visit_guest") else current_save()


def read_only(field: str) -> dict:
    detail = message("read_only_island")
    return {"error": {"code": 400, "details": {field: detail, "message": detail, "keys": [field]}}}


def summary(name: str, house: int, member_id: int) -> dict:
    return {"pgl_name": name, "member_id": member_id, "member_savedata_id": member_id,
            "island_id": house, "country_id": 1, "friend_status": int(visits.PalStatus.FRIEND),
            "is_ds": 0, "is_gts": 0, "is_pdw": 1}


def entry(doc: dict, member_id: int) -> dict:
    content = doc["content"]
    return summary(content["profile"]["pgl_name"], content["island"]["island_id"], member_id)


def map_friends() -> list[dict]:
    card = resident()
    return [summary(row["name"], row["house"], row["member_savedata_id"])
            for row in islands.list_friends(card)] if card else []


def resolve(member_id: int) -> dict | None:
    card = resident()
    return islands.get_native_friend(card, member_id) if card else None


def sleeper(doc: dict) -> dict | None:
    shared = doc["content"]["sleeper"]
    if not shared:
        return None
    species = text.lookup_str("pokemon", shared["pokemon_no"]) or ""
    return {**shared, "pokemon_name": species, "pokemon_nickname": display_nickname(shared.get("pokemon_nickname"),
            verified=shared.get("nickname_verified") is True) or species, "form_no": shared.get("form_no", 0),
            "sex": shared.get("sex", 2), "type1": text.lookup_str("type", shared.get("type1")),
            "type2": text.lookup_str("type", shared.get("type2")), "oyaname": doc["content"]["profile"].get("player_name", ""),
            "personality": text.lookup_str("nature", shared.get("personality")),
            "ball_name": text.lookup_str("ball", shared.get("ball_name")),
            "shiny": pokemon.shows_shiny(shared.get("is_shiny", False))}


def layout(doc: dict) -> list[dict]:
    return [arranged_entry({"my_interior_id": i, "interior_id": obj["interior_id"], "x": obj["x"], "y": obj["y"]})
            for i, obj in enumerate(doc["content"]["decor"], 1) if "x" in obj and obj["interior_id"] in CATALOG]


_PRESENCE = """CREATE TABLE IF NOT EXISTS offline_island_scene (
    card TEXT NOT NULL, browser TEXT NOT NULL, island TEXT NOT NULL, event TEXT NOT NULL, arrived INTEGER NOT NULL,
    PRIMARY KEY(card,browser))"""


def _browser() -> str:
    return session.setdefault("island_browser", secrets.token_hex(16))


def start_browser() -> None:
    # Establish the browser ID before the movie starts its parallel scene requests.
    if session.get("username"):
        _browser()


def prepare(card: str, island: str, event_id: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", event_id):
        raise islands.IslandError("Invalid visit ID.")
    with db.transaction() as conn:
        conn.execute(_PRESENCE)
        conn.execute("INSERT OR REPLACE INTO offline_island_scene VALUES(?,?,?,?,0)", (card, _browser(), island, event_id))


def arrive(card: str, island: str) -> int:
    with db.transaction() as conn:
        conn.execute(_PRESENCE)
        browser = _browser()
        row = conn.execute("SELECT event FROM offline_island_scene WHERE card=? AND browser=? AND island=?",
                           (card, browser, island)).fetchone()
        event = row["event"] if row else secrets.token_hex(16)
        islands.record_footprint(card, island, event)
        conn.execute("INSERT OR REPLACE INTO offline_island_scene VALUES(?,?,?,?,1)", (card, browser, island, event))
        return conn.execute("SELECT COUNT(*) FROM offline_island_outbox WHERE gscd=? AND dest=?", (card, island)).fetchone()[0]


def leave(card: str) -> None:
    if "island_browser" not in session:
        return
    with db.transaction() as conn:
        conn.execute(_PRESENCE)
        conn.execute("DELETE FROM offline_island_scene WHERE card=? AND browser=? AND arrived=1",
                     (card, session["island_browser"]))
