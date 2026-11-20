"""Signed, read-only island postcards and a separate durable footprint mailbox."""
import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from ecdsa import BadSignatureError, Ed25519, MalformedPointError, SigningKey, VerifyingKey

from game_sync_server.entralinked.utility.db_manager import db
from utils.data import load_json_data
from utils.gen5_names import display_nickname
from utils.visit_storage import reserve_member_id

MAX_BYTES = 512 * 1024
SNAPSHOT_FORMAT = "dreamworld.island.v1"
EVENT_FORMAT = "dreamworld.footprint.v1"
_HEX32 = re.compile("[0-9a-f]{32}")
_HEX64 = re.compile("[0-9a-f]{64}")
_HEX128 = re.compile("[0-9a-f]{128}")
MAX_BATCH = 50

_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS offline_island_owners (
        gscd TEXT PRIMARY KEY, seed BLOB NOT NULL, island TEXT NOT NULL UNIQUE,
        digest TEXT, document TEXT)""",
    """CREATE TABLE IF NOT EXISTS offline_island_friends (
        gscd TEXT NOT NULL, island TEXT NOT NULL, version INTEGER NOT NULL,
        updated_at INTEGER NOT NULL, synced_at INTEGER NOT NULL, name TEXT NOT NULL, document TEXT NOT NULL,
        PRIMARY KEY (gscd,island))""",
    """CREATE TABLE IF NOT EXISTS offline_island_map (
        member_savedata_id INTEGER PRIMARY KEY CHECK(member_savedata_id>0),
        gscd TEXT NOT NULL, island TEXT NOT NULL, UNIQUE (gscd,island))""",
    """CREATE TABLE IF NOT EXISTS offline_island_outbox (
        gscd TEXT NOT NULL, dest TEXT NOT NULL, event TEXT NOT NULL, document TEXT NOT NULL,
        delivered INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(gscd,dest,event))""",
    """CREATE TABLE IF NOT EXISTS offline_island_inbox (
        gscd TEXT NOT NULL, source TEXT NOT NULL, event TEXT NOT NULL, visited_at INTEGER NOT NULL,
        name TEXT NOT NULL, pokemon_no INTEGER, document TEXT NOT NULL, PRIMARY KEY(gscd,source,event))""",
)


class IslandError(ValueError):
    """The island file or event cannot be safely used."""


class IslandNotFound(IslandError):
    """This player does not have the requested island."""


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    with db.transaction() as conn:
        for sql in _SCHEMA:
            conn.execute(sql)
        yield conn


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError) as exc:
        raise IslandError("Invalid JSON data.") from exc


def _exact(value: object, fields: set[str]) -> None:
    if not isinstance(value, dict) or set(value) != fields:
        raise IslandError("Invalid island fields.")


def _string(value: object, maximum: int = 120) -> bool:
    return isinstance(value, str) and len(value) <= maximum and (not value or value.replace("　", " ").isprintable())


def _integer(value: object, low: int = 0, high: int = 2**31 - 1) -> bool:
    return type(value) is int and low <= value <= high


# Only fields listed here may enter a postcard. Membership is deliberately not inferred from save keys.
_PROFILE = {
    "pgl_name": str, "player_name": str, "rom_id": int, "langcode": int, "trainer_gender": int,
    "player_badge_num": int, "avator_id": int, "point": int, "experiment_point": int,
    "member_created_at": str, "sleep_pokemon_count": int, "send_pokemon_count": int,
    "sleeping_flag": int, "play_status": int, "hours_played": int, "minutes_played": int, "board_count": int,
    "levels_gained": int, "pending_partner_count": int, "pending_item_stacks": int, "loblolly_decor": int,
}
_ISLAND = {"island_id": int, "shelf_id": int, "wateringpot_id": int}
_SLEEPER = {"pokemon_no": int, "form_no": int, "pokemon_nickname": str, "type1": int, "type2": int,
            "sex": int, "ball_name": int, "personality": int, "level": int, "is_shiny": bool,
            "nickname_verified": bool}
_LISTS: dict[str, tuple[dict[str, type], int, set[str]]] = {
    "decor": ({"interior_id": int, "x": int, "y": int}, 4096, {"interior_id"}),
    "garden": ({"x": int, "y": int, "pokeitem_id": int, "dirt_hp": int, "kinomi_state": int,
                "planted_at": int, "watered_at": int}, 128, {"x", "y"}),
    "shelf": ({"item_id": int, "x": int, "y": int}, 128, {"item_id"}),
    "chest": ({"pokeitem_id": int, "item_cnt": int}, 1024, {"pokeitem_id", "item_cnt"}),
    "board": ({"pokemon_no": int, "form_no": int, "move": int, "met_at": str, "sent_at": str,
               "selected": bool}, 512, {"pokemon_no"}),
}


def _valid_scalar(key: str, value: object, typ: type) -> bool:
    if typ is str:
        return _string(value)
    if typ is int:
        return _integer(value, -4096, 4096) if key in ("x", "y") else _integer(value)
    return type(value) is bool


def _project(data: dict, schema: dict) -> dict:
    # Absent or null values are omitted; old saves do not always have every field.
    return {key: data[key] for key, typ in schema.items() if key in data and _valid_scalar(key, data[key], typ)}


def _record(data: object, schema: dict, required: set[str]) -> None:
    if (not isinstance(data, dict) or not required <= data.keys() <= schema.keys()
            or not all(_valid_scalar(key, value, schema[key]) for key, value in data.items())):
        raise IslandError("Invalid island record.")


def _check_content(content: dict) -> None:
    _exact(content, {"profile", "island", "sleeper", "medals", "favorite_medal", "theme", *_LISTS})
    _record(content["profile"], _PROFILE, {"pgl_name"})
    _record(content["island"], _ISLAND, {"island_id", "shelf_id"})
    _record(content["sleeper"], _SLEEPER, set())
    if content["sleeper"] and not _integer(content["sleeper"].get("pokemon_no"), 1, 649):
        raise IslandError("Invalid sleeping Pokémon.")
    if (not _integer(content["theme"], 3, 9) or not isinstance(content["medals"], list)
            or len(content["medals"]) > 512 or not all(_integer(i, 0, 65535) for i in content["medals"])
            or (content["favorite_medal"] is not None and not _integer(content["favorite_medal"], 0, 65535))):
        raise IslandError("Invalid island theme or medal list.")
    for key, (schema, maximum, required) in _LISTS.items():
        records = content[key]
        if not isinstance(records, list) or len(records) > maximum:
            raise IslandError("Invalid island list.")
        for item in records:
            _record(item, schema, required)
            if key == "decor" and ("x" in item) != ("y" in item):
                raise IslandError("Both decor coordinates are required.")


@lru_cache(maxsize=1)
def _encounter_species() -> dict:
    slots = load_json_data("dream_islands")["objects"].values()
    return {entry["object_pokemon_id"]: entry for slot in slots for entry in slot["contents"] if "pokemon_no" in entry}


def _public_content(row: sqlite3.Row) -> dict:
    data = json.loads(row["player_data"] or "{}") or {}
    member = data.get("member") or {}
    if not member.get("pgl_name"):
        raise IslandError("Finish linking a nickname and cartridge before sharing an island.")
    sync = json.loads(row["game_sync"] or "{}") or {}
    source_sleeper = json.loads(row["sleeping_pokemon"] or "{}") or {}
    nickname = display_nickname(source_sleeper.get("pokemon_nickname"),
                                verified=source_sleeper.get("nickname_verified") is True)
    sleeper = _project({**source_sleeper, "pokemon_nickname": nickname}, _SLEEPER)
    board = []
    history = data.get("dream_board", [])
    for card in history[-_LISTS["board"][1]:]:
        entry = _encounter_species().get(card.get("object_id"))
        if entry:
            board.append(_project({**card, "pokemon_no": entry["pokemon_no"], "form_no": entry["form_no"]},
                                  _LISTS["board"][0]))
    profile = _project({**member, "board_count": len(history)}, _PROFILE)
    for name in ("hours_played", "minutes_played", "levels_gained", "loblolly_decor"):
        if _integer(sync.get(name)):
            profile[name] = sync[name]
    for column, name in (("encounters", "pending_partner_count"), ("items", "pending_item_stacks")):
        if isinstance(sync.get(column), list):
            profile[name] = len(sync[column])
    # The sleeper's primary type supplies a consistent theme, even if the owner is offline.
    terrain = {0: 9, 1: 6, 2: 5, 3: 3, 4: 8, 5: 6, 6: 3, 7: 7, 8: 8,
               9: 6, 10: 4, 11: 3, 12: 9, 13: 7, 14: 8, 15: 5, 16: 7}
    content = {"profile": profile, "island": _project(member, _ISLAND), "sleeper": sleeper,
               "medals": data.get("medals", []), "favorite_medal": data.get("favorite_medal"),
               "theme": terrain.get(sleeper.get("type1", -1), 3), "board": board,
               "decor": [_project(item, _LISTS["decor"][0]) for item in member.get("my_interior_list", [])]}
    for key, column, field in (("garden", "crop_data", "croft_list"), ("shelf", "share_data", "share_list"),
                               ("chest", "chest_data", "list")):
        records = (json.loads(row[column] or "{}") or {}).get(field, [])
        content[key] = [_project(item, _LISTS[key][0]) for item in records]
        if key == "garden":
            for plot, public in zip(records, content[key], strict=True):
                public.update(_project(plot.get("server") or {}, {"planted_at": int, "watered_at": int}))
    _check_content(content)
    return content


def _local_card(conn: sqlite3.Connection, gscd: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM player_saves WHERE gscd=?", (gscd,)).fetchone()
    if not row or not row["player_data"]:
        raise IslandNotFound("This cartridge has no local island.")
    return row


def _owner(conn: sqlite3.Connection, gscd: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM offline_island_owners WHERE gscd=?", (gscd,)).fetchone()
    if row:
        return row
    _local_card(conn, gscd)
    key = SigningKey.generate(curve=Ed25519)
    island = hashlib.sha256(key.verifying_key.to_string()).hexdigest()
    conn.execute("INSERT INTO offline_island_owners(gscd,seed,island) VALUES(?,?,?)", (gscd, key.to_string(), island))
    return conn.execute("SELECT * FROM offline_island_owners WHERE gscd=?", (gscd,)).fetchone()


def _sign(fields: dict, seed: bytes) -> dict:
    key = SigningKey.from_string(seed, curve=Ed25519)
    return {**fields, "signature": key.sign_deterministic(_canonical(fields)).hex()}


def _verify(document: dict, public_key: str) -> None:
    signature = document["signature"]
    if not isinstance(signature, str) or not _HEX128.fullmatch(signature):
        raise IslandError("Invalid signature.")
    try:
        key = VerifyingKey.from_string(bytes.fromhex(public_key), curve=Ed25519)
        key.verify(bytes.fromhex(signature), _canonical({k: v for k, v in document.items() if k != "signature"}))
    except (ValueError, BadSignatureError, MalformedPointError, AssertionError) as exc:
        raise IslandError("The signature does not match the document.") from exc


def export_island(gscd: str) -> dict:
    """Return a stable signed version, incrementing only when a shared field changed."""
    with _transaction() as conn:
        content = _public_content(_local_card(conn, gscd))
        owner = _owner(conn, gscd)
        digest = hashlib.sha256(_canonical(content)).hexdigest()
        if digest == owner["digest"]:
            return json.loads(owner["document"])
        previous = json.loads(owner["document"]) if owner["document"] else {}
        key = SigningKey.from_string(owner["seed"], curve=Ed25519)
        document = _sign({"format": SNAPSHOT_FORMAT, "island_id": owner["island"],
                          "public_key": key.verifying_key.to_string().hex(),
                          "version": previous.get("version", 0) + 1, "updated_at": int(time.time()), "content": content},
                         owner["seed"])
        encoded = _canonical(document)
        if len(encoded) > MAX_BYTES:
            raise IslandError("This island exceeds the snapshot size limit.")
        conn.execute("UPDATE offline_island_owners SET digest=?, document=? WHERE gscd=?", (digest, encoded.decode(), gscd))
        return document


def decode_snapshot(raw: bytes) -> dict:
    """Parse a size-bounded JSON file, rejecting duplicate fields and invalid Unicode."""
    if not raw or len(raw) > MAX_BYTES:
        raise IslandError("Invalid snapshot file size.")

    def no_duplicates(pairs: list) -> dict:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise IslandError("Duplicate JSON field.")
        return result

    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=no_duplicates)
    except (ValueError, RecursionError) as exc:
        raise IslandError("Invalid snapshot JSON.") from exc
    validate_snapshot(doc)
    return doc


def validate_snapshot(doc: dict) -> None:
    _exact(doc, {"format", "public_key", "island_id", "version", "updated_at", "content", "signature"})
    pub = doc["public_key"]
    if (doc["format"] != SNAPSHOT_FORMAT or not isinstance(pub, str) or not _HEX64.fullmatch(pub)
            or hashlib.sha256(bytes.fromhex(pub)).hexdigest() != doc["island_id"]
            or not _integer(doc["version"], 1, 2**53 - 1) or not _integer(doc["updated_at"], 0, 253402300799)
            or len(_canonical(doc)) > MAX_BYTES):
        raise IslandError("Invalid island identity, version or size.")
    _check_content(doc["content"])
    _verify(doc, pub)


def _friend(conn: sqlite3.Connection, gscd: str, island_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM offline_island_friends WHERE gscd=? AND island=?", (gscd, island_id)).fetchone()
    if not row:
        raise IslandNotFound("This island has not been imported for this cartridge.")
    return row


def _insert_member(conn: sqlite3.Connection, gscd: str, island_id: str) -> int:
    member = reserve_member_id(conn)
    conn.execute("INSERT INTO offline_island_map(member_savedata_id,gscd,island) VALUES(?,?,?)", (member, gscd, island_id))
    return member


def native_member_id(gscd: str, island_id: str) -> int:
    """Local numeric identity consumed by the original Dream Pal map and room."""
    with _transaction() as conn:
        row = conn.execute("""SELECT m.member_savedata_id FROM offline_island_friends f
            LEFT JOIN offline_island_map m USING(gscd,island) WHERE f.gscd=? AND f.island=?""",
                           (gscd, island_id)).fetchone()
        if row is None:
            raise IslandNotFound("This island has not been imported for this cartridge.")
        return row[0] if row[0] is not None else _insert_member(conn, gscd, island_id)


def get_native_friend(gscd: str, member_id: int) -> dict | None:
    """Look up the signed island among this visitor's own imported friends."""
    with _transaction() as conn:
        row = conn.execute("""SELECT f.document FROM offline_island_map m
            JOIN offline_island_friends f USING(gscd,island) WHERE m.gscd=? AND m.member_savedata_id=?""",
                           (gscd, member_id)).fetchone()
        return json.loads(row[0]) if row else None


def import_island(gscd: str, document: dict) -> dict:
    """Never replace a played-on save. A stale postcard returns the newest cached copy."""
    validate_snapshot(document)
    island = document["island_id"]
    with _transaction() as conn:
        if _owner(conn, gscd)["island"] == island:
            raise IslandError("Choose a friend's island.")
        row = conn.execute("SELECT version,document FROM offline_island_friends WHERE gscd=? AND island=?",
                           (gscd, island)).fetchone()
        if row and row["version"] > document["version"]:
            return json.loads(row["document"])
        encoded = _canonical(document).decode()
        if row and row["version"] == document["version"] and row["document"] != encoded:
            raise IslandError("Conflicting contents for an existing island version.")
        now = int(time.time())
        conn.execute("""INSERT INTO offline_island_friends VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(gscd,island) DO UPDATE SET version=excluded.version,updated_at=excluded.updated_at,
            synced_at=excluded.synced_at,name=excluded.name,document=excluded.document""",
                     (gscd, island, document["version"], document["updated_at"], now,
                      document["content"]["profile"]["pgl_name"], encoded))
        if not row:
            _insert_member(conn, gscd, island)
    return document


def list_friends(gscd: str) -> list[dict]:
    with _transaction() as conn:
        missing = conn.execute("""SELECT f.island FROM offline_island_friends f
            LEFT JOIN offline_island_map m USING(gscd,island) WHERE f.gscd=? AND m.member_savedata_id IS NULL""",
                               (gscd,)).fetchall()
        for row in missing:
            _insert_member(conn, gscd, row[0])
        return [dict(row) for row in conn.execute(
            "SELECT island AS island_id,version,updated_at,synced_at,name,member_savedata_id,"
            "json_extract(document,'$.content.island.island_id') AS house FROM offline_island_friends "
            "JOIN offline_island_map USING(gscd,island) "
            "WHERE gscd=? ORDER BY name COLLATE NOCASE,island", (gscd,))]


def get_friend(gscd: str, island_id: str) -> dict:
    with _transaction() as conn:
        return json.loads(_friend(conn, gscd, island_id)["document"])


def record_footprint(gscd: str, island_id: str, event_id: str) -> dict:
    """A visitor-generated action ID makes posting one visit retryable even after delivery."""
    if not isinstance(event_id, str) or not _HEX32.fullmatch(event_id):
        raise IslandError("Invalid visit ID.")
    with _transaction() as conn:
        _friend(conn, gscd, island_id)
        existing = conn.execute("SELECT document FROM offline_island_outbox WHERE gscd=? AND dest=? AND event=?",
                                (gscd, island_id, event_id)).fetchone()
        if existing:
            return json.loads(existing["document"])
        owner = _owner(conn, gscd)
        row = _local_card(conn, gscd)
        profile = json.loads(row["player_data"])["member"]
        event = _sign({"format": EVENT_FORMAT, "event_id": event_id, "guest_island": owner["island"], "dest": island_id,
                       "visited_at": int(time.time()), "name": profile["pgl_name"],
                       "pokemon_no": (json.loads(row["sleeping_pokemon"] or "{}") or {}).get("pokemon_no")}, owner["seed"])
        conn.execute("INSERT INTO offline_island_outbox(gscd,dest,event,document) VALUES(?,?,?,?)",
                     (gscd, island_id, event_id, _canonical(event).decode()))
        return event


def pending_footprints(gscd: str, dest_island: str, limit: int = MAX_BATCH) -> list[dict]:
    with _transaction() as conn:
        rows = conn.execute("SELECT document FROM offline_island_outbox WHERE gscd=? AND dest=? AND delivered=0 "
                            "ORDER BY rowid LIMIT ?", (gscd, dest_island, max(0, min(limit, MAX_BATCH))))
        return [json.loads(row[0]) for row in rows]


def _ids(ids: object) -> None:
    if not isinstance(ids, list) or len(ids) > MAX_BATCH or any(
        not isinstance(ident, str) or not _HEX32.fullmatch(ident) for ident in ids
    ):
        raise IslandError("Invalid footprint acknowledgement.")


def acknowledge_footprints(gscd: str, dest_island: str, ids: list[str]) -> None:
    _ids(ids)
    with _transaction() as conn:
        conn.executemany("UPDATE offline_island_outbox SET delivered=1 WHERE gscd=? AND dest=? AND event=?",
                         ((gscd, dest_island, event_id) for event_id in ids))


def receive_footprints(gscd: str, source_island: str, events: list) -> list[str]:
    if not isinstance(events, list) or len(events) > MAX_BATCH:
        raise IslandError("Invalid footprint batch size.")
    if not events:
        return []
    with _transaction() as conn:
        dest = _owner(conn, gscd)["island"]
        pub = json.loads(_friend(conn, gscd, source_island)["document"])["public_key"]
        ids = []
        for ev in events:
            _exact(ev, {"format", "event_id", "guest_island", "dest", "visited_at", "name", "pokemon_no", "signature"})
            if (ev["format"] != EVENT_FORMAT or ev["guest_island"] != source_island or ev["dest"] != dest
                    or not _string(ev["name"]) or not _integer(ev["visited_at"], 0, 253402300799)
                    or (ev["pokemon_no"] is not None and not _integer(ev["pokemon_no"], 1, 649))):
                raise IslandError("Invalid visitor identity or footprint.")
            _ids([ev["event_id"]])
            _verify(ev, pub)
            encoded = _canonical(ev).decode()
            inserted = conn.execute("INSERT OR IGNORE INTO offline_island_inbox VALUES(?,?,?,?,?,?,?)",
                                    (gscd, source_island, ev["event_id"], ev["visited_at"], ev["name"],
                                     ev["pokemon_no"], encoded))
            if not inserted.rowcount:
                existing = conn.execute("SELECT document FROM offline_island_inbox WHERE gscd=? AND source=? AND event=?",
                                        (gscd, source_island, ev["event_id"])).fetchone()
                if existing[0] != encoded:
                    raise IslandError("Conflicting footprint with the same ID.")
            ids.append(ev["event_id"])
        return ids


def received_footprints(gscd: str) -> list[dict]:
    with _transaction() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT event AS event_id, visited_at,source AS guest_island,name,pokemon_no FROM offline_island_inbox "
            "WHERE gscd=? ORDER BY visited_at DESC,rowid DESC LIMIT 300", (gscd,))]
