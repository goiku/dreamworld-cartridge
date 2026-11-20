"""pdw.home.*: the player's house and island (pdw_home.swf, pdw_room.swf)."""
import json
import time
from datetime import datetime
from random import choice

from api import native_islands
from api.pdw_dreamland import _require_playing
from api.routes import Query, endpoint, query_int
from game_sync_server.entralinked.utility.db_manager import db
from utils import managers, offline_islands, pokemon, save_data, text, visits
from utils.constants import PlayerStatus
from utils.decor import arranged_decor
from utils.models import Member, SleepingPokemon

STARTER_BERRY_IDS = range(184, 201)  # Occa through Chilan, the damage-reducing Berries
STARTER_BERRY_COUNT = 5


def _page(items: list, query: Query, default: int) -> list:
    offset = max(0, query_int(query, "offset", 0))
    count = max(0, query_int(query, "rowcount", default))
    return items[offset:offset + count]


@endpoint("pdw.home.footprint_list")
def footprint_list(query: Query) -> dict:
    """Return real visitors with their Pokémon and activities for each visit day."""
    island = save_data.require_gscd()
    records = [(row["updated_at"], False, row) for row in visits.footprints(island)]
    received = offline_islands.received_footprints(island) if native_islands.resident() == island else []
    for event in received:
        try:
            when = datetime.fromtimestamp(event["visited_at"], save_data.JST).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OverflowError, OSError):
            # A peer can supply a UTC date beyond the representable last day in Japan.
            when = "9999-12-31 23:59:59"
        records.append((when, True, event))
    records.sort(key=lambda entry: entry[0], reverse=True)
    listed = []
    for when, remote, row in _page(records, query, 12):
        if remote:
            friend = offline_islands.get_friend(island, row["guest_island"])
            member_id = offline_islands.native_member_id(island, row["guest_island"])
            # A signed footprint records species and visitor name at the time of the visit.
            # The latest sleeper can differ even when its species happens to match.
            species = row["pokemon_no"] or 0
            species_name = text.lookup_str("pokemon", species) if species else ""
            listed.append({
                **native_islands.entry(friend, member_id),
                "pgl_name": row["name"], "visitor_member_savedata_id": member_id,
                "pokemon_no": species, "pokemon_name": species_name, "pokemon_nickname": species_name,
                "form_no": 0, "sex_id": 2, "updated_at": when[:16],
                "water_flag": 0, "exchange_flag": 0, "friend_type": "0",
            })
            continue
        guest = save_data.read_member(row["guest"])
        pkmn = _island_pokemon(pokemon.localized_sleeper(json.loads(row["pokemon"])))
        if not pkmn:
            continue
        status = visits.relationship(island, row["guest"])
        listed.append({
            **_map_entry(guest, status), **pkmn,
            "visitor_member_savedata_id": guest["member_savedata_id"],
            "sex_id": pkmn["sex"], "updated_at": row["updated_at"][:16],
            "water_flag": row["watered"], "exchange_flag": row["traded"],
            "friend_type": "1" if status == visits.PalStatus.INVITED_YOU else "0",
        })
    return {"cnt": len(records), "list": listed}


def _island_pokemon(pkmn: SleepingPokemon) -> dict | None:
    """A tucked-in Pokémon."""
    if not pkmn:
        return None
    return {
        **pkmn,
        "pokemon_name": text.lookup_str("pokemon", pkmn["pokemon_no"]),
        "type1":        text.lookup_str("type", pkmn["type1"]),
        "type2":        text.lookup_str("type", pkmn["type2"]),
        "personality":  text.lookup_str("nature", pkmn["personality"]),
        "ball_name":    text.lookup_str("ball", pkmn["ball_name"]),
        "shiny":        pokemon.shows_shiny(pkmn.get("is_shiny", False)),
    }


@endpoint("pdw.home.my_island")
def my_island(_query: Query) -> dict:
    """Return the player's island with their house, furniture, and the tucked-in Pokémon."""
    member = save_data.read_member()
    native_islands.leave(save_data.require_gscd())
    return {
        "pokemon":                _island_pokemon(pokemon.get_sleeper()),
        "island_id":              member["island_id"],
        "point":                  member["point"],
        "trial_flag":             member["trial_flag"],
        "arranged_interior_list": arranged_decor(),
        "requested_flag":         visits.has_invitations(save_data.require_gscd()),
        "shelf_id":               member["shelf_id"],
        "item_deleted_flag":      member.get("item_deleted_flag", 0),
    }


def _map_entry(member: Member, status: visits.PalStatus) -> dict:
    return {
        "pgl_name": member["pgl_name"], "member_id": member["member_id"],
        "member_savedata_id": member["member_savedata_id"], "island_id": member["island_id"],
        "country_id": member.get("country_id"), "friend_status": int(status),
        "is_ds": 0, "is_gts": 0, "is_pdw": int(status == visits.PalStatus.FRIEND),
    }


def _island_area(gscd: str) -> dict:
    friends, strangers = [], []
    for member in visits.neighbors(gscd, include_awake_pals=True):
        other = member.get("gscd")
        if not other:
            continue
        status = visits.relationship(gscd, other)
        if status == visits.PalStatus.FRIEND:
            friends.append(_map_entry(member, status))
        else:
            strangers.append(_map_entry(member, status))
    if gscd == native_islands.resident():
        friends.extend(native_islands.map_friends())
    return {
        "island_id": save_data.read_member(gscd)["island_id"],
        "friend_list": friends,
        "neighbor": choice(strangers) if strangers and gscd == save_data.require_gscd() else None,
    }


@endpoint("pdw.home.friend_list")
def friend_list(query: Query) -> dict:
    return _pal_list(query, save_data.require_gscd())


@endpoint("pdw.home.friend_friend_list")
def friend_friend_list(query: Query) -> dict:
    member_id = int(query["friend_member_savedata_id"])
    if native_islands.resolve(member_id):
        friends = [_map_entry(save_data.read_member(), visits.PalStatus.FRIEND)]
        return {"cnt": 1, "list": _page(friends, query, 11)}
    return _pal_list(query, visits.find_player(member_id))


def _pal_list(query: Query, gscd: str) -> dict:
    listed = _island_area(gscd)["friend_list"]
    sort = query_int(query, "sort", 1)
    if sort == 3:
        listed.sort(key=lambda pal: text.lookup_str("country", pal["country_id"]) or "")
    elif sort == 2:
        listed.sort(key=lambda pal: pal["pgl_name"].casefold())
    else:
        latest = visits.last_visits(gscd)
        listed.sort(key=lambda pal: latest.get(pal["member_savedata_id"], ""), reverse=True)
    return {"cnt": len(listed), "list": _page(listed, query, 11)}


@endpoint("pdw.home.my_island_area")
def my_island_area(_query: Query) -> dict:
    """Return the map around the player's own island."""
    return _island_area(save_data.require_gscd())


@endpoint("pdw.home.friend_island_area")
def friend_island_area(query: Query) -> dict:
    """Return the map around another player's island, which the player is visiting."""
    member_id = int(query["friend_member_savedata_id"])
    doc = native_islands.resolve(member_id)
    if doc:
        return {"island_id": doc["content"]["island"]["island_id"], "neighbor": None,
                "friend_list": [_map_entry(save_data.read_member(), visits.PalStatus.FRIEND)]}
    return _island_area(visits.find_player(member_id))


@endpoint("pdw.home.friend_island")
def friend_island(query: Query) -> dict:
    """Return another player's island."""
    member_id = int(query["friend_member_savedata_id"])
    doc = native_islands.resolve(member_id)
    if doc:
        content = doc["content"]
        return {**native_islands.entry(doc, member_id), "visit_count": native_islands.arrive(save_data.require_gscd(), doc["island_id"]),
                "shared_island_id": doc["island_id"], "shared_version": doc["version"], "shared_updated_at": doc["updated_at"],
                "pokemon": _island_pokemon(pokemon.get_sleeper()), "friend_pokemon": native_islands.sleeper(doc),
                "point": content["profile"].get("point", 0), "trial_flag": 0, "requested_flag": False,
                "arranged_interior_list": native_islands.layout(doc), "shelf_id": content["island"]["shelf_id"]}
    friend = visits.find_player(member_id)
    member = save_data.read_member(friend)
    me = save_data.require_gscd()
    visits.record_visit(friend)
    return {
        **_map_entry(member, visits.relationship(me, friend)),
        "visit_count":            visits.visit_count(friend, me),
        "pokemon":                _island_pokemon(pokemon.get_sleeper()),
        "friend_pokemon":         _island_pokemon(pokemon.get_sleeper(friend)),
        "island_id":              member["island_id"],
        "point":                  member["point"],
        "trial_flag":             member["trial_flag"],
        "arranged_interior_list": arranged_decor(friend),
        "requested_flag":         False,
        "shelf_id":               member["shelf_id"],
    }


@endpoint("pdw.home.pdw_end")
def pdw_end(_query: Query) -> dict:
    """End the Dream World session so the Pokémon can be woken."""
    save_data.set_play_status(PlayerStatus.WAKE_READY)
    return {}


@endpoint("pdw.home.pdw_start", methods=("POST",))
def pdw_start(_query: Query) -> dict:
    """Start a Dream World session and award Fennel's gift on the first visit."""
    gscd = save_data.require_gscd()
    timestamp = int(time.time())
    with db.transaction():
        member = save_data.read_member(gscd)
        _require_playing(member)
        update: Member = {"pokemon_name": text.lookup_str("pokemon", member["pokemon_no"])}
        if member.get("first_flag") == 0:
            managers.get_chest(gscd).add_item(choice(STARTER_BERRY_IDS), STARTER_BERRY_COUNT)
            update["first_flag"] = 1
        save_data.record_session_start(timestamp, gscd)
        save_data.update_member(update, gscd)

    return {"started_at": timestamp}


@endpoint("pdw.home.pdw_timecheck", methods=("POST",))
def pdw_timecheck(_query: Query) -> dict:
    """Save how long is left before the next session can start."""
    save_data.update_member({"nextstart_remaintime": save_data.get_nextstart_remaintime()})
    return {}


@endpoint("pdw.home.item_deleted_check", methods=("POST",))
def item_deleted_check(_query: Query) -> dict:
    """Shown once after Berries are converted to Dream Points (see pgl_top._check_item_deletion)."""
    exchange_point = save_data.read_member().get("item_deleted_point", 0)
    save_data.update_member({"item_deleted_flag": 0, "item_deleted_point": 0})
    return {"exchange_point": exchange_point}
