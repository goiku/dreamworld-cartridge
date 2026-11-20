"""pdw.dreamland.*: Dream Island visits (pdw_island.swf) and their minigame rewards."""
import hashlib
import logging
from collections.abc import Sequence
from random import choices, sample
from typing import TypeVar

from werkzeug.exceptions import BadRequest, Conflict

from api.routes import Query, endpoint, query_int
from game_sync_server.entralinked.utility.db_manager import db
from utils import managers, pokemon, save_data, text, visits
from utils.berries import is_berry
from utils.constants import PlayerStatus, is_b2w2
from utils.data import load_json_data
from utils.models import Member, PlayerData

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Not post-processing any of the raw data for now.
_DREAMLAND = load_json_data("dream_islands")
# island area id (3-9) -> {"req_points": {"bw", "b2w2"}, "req_badges": {"bw", "b2w2"}}
# (type preferences: _FAVORED_AREA_SHARE)
_UNLOCKS: dict[str, dict[str, dict[str, int]]] = _DREAMLAND["unlocks"]
_SLOTS = {int(object_id): slot for object_id, slot in _DREAMLAND["objects"].items()}
_CONTENTS = {c["object_pokemon_id"]: c for slot in _SLOTS.values() for c in slot["contents"]}

OBJECTS_PER_VISIT = 17
B2W2_AREA_OFFSET = 100  # B2W2 use areas 103-109
MINIGAME_POINTS = 20
SPECIAL_MOVE_COUNT = 4  # waza_count: every live capture says 4

# Minigame rank (1 best - 5 worst) -> % chance of the Pokémon's special move A, B, or C.
# Ranks 2, 3, and 4's odds are estimated. Rank 0 is a failure.
MOVE_CHANCES = {
    0: (0, 0, 0),
    1: (0, 50, 50),
    2: (20, 40, 40),
    3: (40, 32, 28),
    4: (60, 25, 15),
    5: (70, 20, 10),
}

# Tucked-in Pokémon type id -> {area id: share of visits}. A type sends this share of visits to
# its favored area(s) and splits the rest evenly across every other area. A dual type averages
# its two types' tables, and areas the player can't enter yet are skipped.
_FAVORED_AREA_SHARE: dict[int, dict[str, float]] = {
    0:  {"9": 0.50},             # Normal: Dream Park (estimate)
    1:  {"6": 0.50},             # Fighting: Rugged Mountain
    2:  {"5": 0.70},             # Flying: Windswept Sky
    3:  {"3": 0.50},             # Poison: Pleasant Forest
    4:  {"6": 0.35, "8": 0.35},  # Ground: Rugged Mountain, Icy Cave
    5:  {"6": 0.35, "8": 0.35},  # Rock: Rugged Mountain, Icy Cave
    6:  {"3": 0.50},             # Bug: Pleasant Forest
    7:  {"7": 0.70},             # Ghost: Spooky Manor
    8:  {"6": 0.35, "8": 0.40},  # Steel: Rugged Mountain, Icy Cave
    9:  {"6": 0.50},             # Fire: Rugged Mountain
    10: {"4": 0.70},             # Water: Sparkling Sea
    11: {"3": 0.70},             # Grass: Pleasant Forest
    12: {"3": 0.50},             # Electric: Pleasant Forest
    13: {"7": 0.50},             # Psychic: Spooky Manor
    14: {"8": 0.70},             # Ice: Icy Cave
    15: {},                      # Dragon: no preference
    16: {"7": 0.50},             # Dark: Spooky Manor
}


def _weighted_choice(options: Sequence[T], weights: Sequence[float]) -> T:
    return choices(options, weights=weights, k=1)[0]


def _pokemon_fields(content: dict) -> dict:
    """Pokémon-related fields which are sent by both pdw.dreamland.top and game_clear."""
    info = pokemon.info(content["pokemon_no"], content["form_no"])
    return {
        "pokemon_no": content["pokemon_no"],
        "form_no":    content["form_no"],
        "pokename":   text.lookup_str("pokemon", content["pokemon_no"]),
        "sex_id":     content["sex_id"],
        "type1":      text.lookup_str("type", info["type1"]),
        "type2":      text.lookup_str("type", info["type2"]),
        "speabi1":    text.lookup_str("ability", info["speabi1"]),
        "speabi2":    text.lookup_str("ability", info["speabi2"]),
        "speabi3":    text.lookup_str("ability", info["speabi3"]),
    }


def _area_weights(type_ids: Sequence[int | None], area_ids: Sequence[str]) -> dict[str, float]:
    """Chance of each area (summing to 1) for a tucked-in Pokémon of these types. See _FAVORED_AREA_SHARE."""
    types = list(dict.fromkeys(t for t in type_ids if t is not None)) or [15]
    weights = dict.fromkeys(area_ids, 0.0)
    for type_id in types:
        favored = {a: share for a, share in _FAVORED_AREA_SHARE[type_id].items() if a in weights}
        rest = (1 - sum(favored.values())) / (len(area_ids) - len(favored))
        for area_id in area_ids:
            weights[area_id] += favored.get(area_id, rest) / len(types)
    return weights


def accessible_areas(player: Member, game_key: str) -> list[str]:
    points, badges = player["experiment_point"], player["player_badge_num"] or 0
    return [area for area, req in _UNLOCKS.items()
            if points >= req["req_points"][game_key] and badges >= req["req_badges"][game_key]]


def _pick_area(player: Member, game_key: str) -> str:
    """Return a random area ID (3-9) from the ones accessible to the player.

    The pick is weighted by the tucked-in Pokémon's types.
    """
    island_areas = list(_UNLOCKS)
    weights = _area_weights([player["type1"], player["type2"]], island_areas)
    areas = accessible_areas(player, game_key)
    return _weighted_choice(areas, [weights[area_id] for area_id in areas])


def _object_entry(object_id: int, slot: dict, world_id: int) -> dict:
    """Build an encounter object, which is either a Pokémon with a mini-game or an item."""
    content = _weighted_choice(slot["contents"], [c["weight"] for c in slot["contents"]])
    entry = {
        "object_id":         object_id,
        "otoken":            save_data.generate_otoken(world_id),
        "public_date_from":  None,
        "public_date_to":    None,
        "object_category":   slot["object_category"],
        "minigame_id":       slot["minigame_id"],
        "kinomi_id":         0,
        "kinomi_count":      0,
        "pokeitem_id":       0,
        "object_pokemon_id": content["object_pokemon_id"],
    }
    if "pokemon_no" in content:
        entry["pokemon"] = {**_pokemon_fields(content), "action_type": content["action_type"]}
    return entry


def _minigame_rank(otoken: str, object_pokemon_id: str, result: str) -> int | None:
    """Return the mini-game rank that `result` encodes, or None if it matches none.

    pdw_island.swf sends result = md5(str(rank) + otoken + object_pokemon_id).
    """
    for rank in MOVE_CHANCES:
        if hashlib.md5(f"{rank}{otoken}{object_pokemon_id}".encode()).hexdigest() == result:
            return rank
    return None


def _special_move(content: dict, rank: int | None) -> int | None:
    """Pick special move A, B, or C by MOVE_CHANCES for the rank.

    An unknown rank counts as rank 0. Return None if no move has a chance.
    """
    chances = MOVE_CHANCES[0 if rank is None else rank]
    possible = [(move, chance) for move, chance in zip(content["special_moves"], chances, strict=False)
                if move is not None and chance > 0]
    if not possible:
        return None
    moves, weights = zip(*possible, strict=True)
    return _weighted_choice(moves, weights)


@endpoint("pdw.dreamland.top")
def top(_query: Query) -> dict:
    """Build a Dream Island visit.

    The island is picked by the player's Dream Points, badges, and Pokémon types. Each island
    has a fixed set of object slots, unlocked by Dream Points (base pool plus expansions).
    A visit shows OBJECTS_PER_VISIT of the unlocked slots at random.
    """
    with db.transaction():
        data = save_data.read_player_data()
        player = data.get("member", {})
        _require_playing(player)
        state = _island_state(data)
        if state["wished"] is not None:
            raise Conflict("A wish has already been made during this sleep.")
        area_id, objects = _new_visit(player)
        state["visit"] = {str(o["object_pokemon_id"]): {"token": o["otoken"], "slot": o["object_id"]}
                          for o in objects}
        _save_island(state)
    return {"dreamland_area_id": area_id, "object_list": objects}


def _new_visit(player: Member) -> tuple[int, list[dict]]:
    b2w2 = is_b2w2(player["rom_id"])
    points = player["experiment_point"]

    area_id = _pick_area(player, "b2w2" if b2w2 else "bw")
    if b2w2:
        area_id = str(int(area_id) + B2W2_AREA_OFFSET)

    unlocked = [object_id for object_id in _DREAMLAND["areas"][area_id]
                if _SLOTS[object_id]["min_points"] <= points]
    visit = sample(unlocked, min(OBJECTS_PER_VISIT, len(unlocked)))

    object_list = [_object_entry(object_id, _SLOTS[object_id], player["world_id"]) for object_id in visit]
    return int(area_id), object_list


def _island_state(player_data: PlayerData) -> dict:
    """A tuck-in can include several trips to the island, followed by one wish."""
    tuck = player_data["member"]["sleep_pokemon_count"]
    state = player_data.get("dream_island", {})
    if state.get("tuck") != tuck:
        return {"tuck": tuck, "visit": {}, "friends": [], "wished": None}
    return state


def _save_island(state: dict) -> None:
    db.update(save_data.require_gscd(), "player_data", lambda data: data.update(dream_island=state))


def _require_playing(member: Member) -> None:
    if (not member.get("sleeping_flag") or member.get("wake_download_pending") or member.get("is_downloaded")
            or member.get("play_status") not in (PlayerStatus.PLAY_READY, PlayerStatus.DREAMING)):
        raise Conflict("This Pokémon is no longer playing in the Dream World.")


def _friend_card(friend: dict) -> dict:
    content = _CONTENTS[friend["object_id"]]
    return {**_pokemon_fields(content), "get_pokemon_id": friend["id"],
            "updated_at": friend.get("sent_at") or friend["met_at"],
            "waza_name_disp": text.lookup_str("move", friend["move"]), "waza_count": SPECIAL_MOVE_COUNT,
            "is_selected": int(friend.get("selected", False))}


def recent_dream_friends(gscd: str | None = None) -> list[dict]:
    """The latest partners added to the Friend Board, as shown on the PGL profile."""
    recent = save_data.read_player_data(gscd).get("dream_board", [])[-5:]
    return [{key: _CONTENTS[f["object_id"]][key] for key in ("pokemon_no", "form_no")} for f in reversed(recent)]


@endpoint("pdw.dreamland.tree_top")
def tree_top(_query: Query) -> dict:
    """Visitors at the tree and Pokémon befriended by this player in this sleep."""
    data = save_data.read_player_data()
    _require_playing(data.get("member", {}))
    state = _island_state(data)
    pokemon_list = []
    for visitor in visits.neighbors():
        visitor_data = save_data.read_player_data(visitor["gscd"])
        if _island_state(visitor_data)["wished"] is None:
            continue
        pkmn = pokemon.get_sleeper(visitor["gscd"])
        if not pkmn:
            continue
        pokemon_list.append({
            "pokemon_no":         pkmn["pokemon_no"],
            "form_no":            pkmn["form_no"],
            "pgl_name":           visitor["pgl_name"],
            "member_savedata_id": visitor["member_savedata_id"],
            "nickname":           pkmn["pokemon_nickname"],
            "pokename":           text.lookup_str("pokemon", pkmn["pokemon_no"]),
            "oyaname":            pkmn["oyaname"],
            "level":              pkmn["level"],
            "type1":              text.lookup_str("type", pkmn["type1"]),
            "type2":              text.lookup_str("type", pkmn["type2"]),
            "sex_id":             pkmn["sex"],
            "pokekaku":           text.lookup_str("nature", pkmn["personality"]),
            "pokeplace":          "",
            "ball_name":          text.lookup_str("ball", pkmn["ball_name"]),
        })
    return {"pokemon_list": pokemon_list[:10], "encount_list": [_friend_card(f) for f in state["friends"]]}


@endpoint("pdw.dreamland.game_clear", methods=("POST",))
def game_clear(query: Query) -> dict:
    """Process item rewards now, otherwise send the Pokémon reward data forward.

    The query holds `object_pokemon_id` (which content slot it was), `pokeitem_id`, and
    `result`. `pokeitem_id` is always 0 unless minigame 2 (Ice Cream Scoop) was played.
    Then it is the item id of the Berry that was used up. `result` is an MD5 of the game
    result (0 failure/abort, 1-5 success), the token, and object_pokemon_id.

    The special move (waza_name_disp) depends on the minigame rank read from result (see
    _special_move and MOVE_CHANCES). Return the reward, which is a Pokémon or an item.
    """
    logger.debug("game_clear %s", query)

    key = query.get("object_pokemon_id", "")
    with db.transaction():
        player = save_data.read_player_data()
        _require_playing(player.get("member", {}))
        state = _island_state(player)
        event = state["visit"].get(key)
        if event is None or state["wished"] is not None:
            raise Conflict("This island encounter is no longer active.")
        rank = _minigame_rank(event["token"], key, query.get("result", ""))
        if rank is None:
            raise BadRequest("Unknown minigame result.")
        content = _CONTENTS[int(key)]
        if "rank" not in event:
            event["rank"] = rank
            if "pokemon_no" in content:
                berry = query_int(query, "pokeitem_id", 0)
                if berry:
                    if _SLOTS[event["slot"]]["minigame_id"] != 2 or not is_berry(berry):
                        raise BadRequest("Invalid Ice Cream Scoop Berry.")
                    chest = managers.get_chest()
                    if not chest.fetch_item_by_id(berry):
                        raise Conflict("This Berry is no longer in the chest.")
                    chest.remove_item(berry, 1)
                event["move"] = _special_move(content, rank)
                if rank > 0:
                    save_data.award_points(MINIGAME_POINTS)
                    state["friends"].append({"id": db.next_id("dream_encounter_id")[0],
                                             "object_id": int(key), "move": event["move"],
                                             "met_at": save_data.now_jst_str()[:16]})
            elif rank == 1:
                managers.get_chest().add_item(content["item_id"], 1)
            else:
                raise BadRequest("Invalid item collection result.")
            _save_island(state)
        elif event["rank"] != rank:
            raise Conflict("This encounter already has a result.")

    reward: dict[str, dict | None] = {"pokemon": None, "item": None, "interior": None, "present": None}
    if "pokemon_no" in content:
        reward["pokemon"] = {**_pokemon_fields(content), "waza_name_disp": text.lookup_str("move", event["move"]),
                             "waza_count": SPECIAL_MOVE_COUNT}
    else:
        item_id = content["item_id"]
        reward["item"] = {"pokeitem_id": item_id, "pokeitem": text.lookup_str("item", item_id), "poke_item_num": 1}
    return reward


def _ds_encounter(friend: dict) -> dict:
    content = _CONTENTS[friend["object_id"]]
    return {"species": content["pokemon_no"], "form": content["form_no"], "move": friend["move"] or 0,
            "gender": 2 if content["sex_id"] == 9 else content["sex_id"], "animation": content["action_type"]}


@endpoint("pdw.dreamland.tree_offer", methods=("POST",))
def tree_offer(query: Query) -> dict:
    """Trade one owned Berry for one of this sleeper's befriended Pokémon."""
    friend_id = query_int(query, "get_pokemon_id", 0)
    berry = query_int(query, "pokeitem_id", 0)
    if not is_berry(berry):
        raise BadRequest("A Berry is required to make a wish.")
    gscd = save_data.require_gscd()
    with db.transaction():
        player = save_data.read_player_data(gscd)
        _require_playing(player["member"])
        state = _island_state(player)
        if state["wished"] == friend_id:
            return {}
        if state["wished"] is not None:
            raise Conflict("This sleeper has already made a wish.")
        friend = next((f for f in state["friends"] if f["id"] == friend_id), None)
        if friend is None:
            raise BadRequest("Choose a Pokémon you befriended during this sleep.")
        chest = managers.get_chest()
        if not chest.fetch_item_by_id(berry):
            raise Conflict("This Berry is no longer in the Treasure Chest.")
        chest.remove_item(berry, 1)
        queue = save_data.read_game_sync().get("encounters", [])
        friend = dict(friend, selected=len(queue) < 10, sent_at=None)
        if friend["selected"]:
            save_data.change_game_sync(lambda sync: sync.setdefault("encounters", []).append(_ds_encounter(friend)))
        state.update(wished=friend_id, friends=[], visit={})

        def record(data: dict) -> None:
            data["dream_island"] = state
            data.setdefault("dream_board", []).append(friend)
        db.update(gscd, "player_data", record)
    return {}


@endpoint("pdw.home.board_pokemon_list")
def board_pokemon_list(query: Query) -> dict:
    sent = query_int(query, "status_type", 1) == 2
    offset = max(0, query_int(query, "offset", 0))
    count = max(0, query_int(query, "rowcount", 50))
    board = [f for f in reversed(save_data.read_player_data().get("dream_board", [])) if bool(f["sent_at"]) == sent]
    return {"total_count": len(board), "pokemon_list": [_friend_card(f) for f in board[offset:offset + count]]}


@endpoint("pdw.home.board_pokemon_selects", methods=("POST",))
def board_pokemon_selects(query: Query) -> dict:
    """Replace the board's part of the next delivery, preserving other gifts."""
    selected = {int(v) for k, v in query.items() if k.startswith("get_pokemon_id[") and v}
    gscd = save_data.require_gscd()
    with db.transaction():
        player = save_data.read_player_data(gscd)
        _require_playing(player["member"])
        board = player.get("dream_board", [])
        pending = [f for f in board if not f["sent_at"]]
        if not selected.issubset(f["id"] for f in pending):
            raise BadRequest("Choose Pokémon on your Friend Board.")
        queue = list(save_data.read_game_sync().get("encounters", []))
        for friend in pending:
            encounter = _ds_encounter(friend)
            if friend["selected"] and encounter in queue:
                queue.remove(encounter)
            friend["selected"] = friend["id"] in selected
        queue.extend(_ds_encounter(f) for f in pending if f["selected"])
        if len(queue) > 10:
            raise BadRequest("The Entralink can receive ten Pokémon at once.")
        save_data.change_game_sync(lambda sync: sync.update({"encounters": queue}))
        db.update(gscd, "player_data", lambda data: data.update(dream_board=board))
    return {}
