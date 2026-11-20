"""Pair one owned Game Sync cartridge with an isolated visitor on a second server."""
import hashlib
import json
import re
import secrets
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager

from game_sync_server.entralinked.model.player.player import Player
from game_sync_server.entralinked.utility import gsid_utility
from game_sync_server.entralinked.utility.db_manager import db
from utils.account_manager import accounts
from utils import travel_gifts

GUEST_PREFIX = "~visit~"
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
INVITE_SECONDS = 30 * 60
TICKET_SECONDS = 60
_SECRET = re.compile(r"[A-Za-z0-9_-]{43}")
_REVISION = re.compile(r"[0-9a-f]{64}")
_COLUMNS = ("player_data", "sleeping_pokemon", "game_sync", "crop_data", "chest_data", "share_data")
_PRIVACY = {"everyone", "friends", "nobody", None}
_LOCAL_SYNC = ("upload_digest", "last_wake_id")
_SCHEMA = (
    """CREATE TABLE IF NOT EXISTS visit_invites (
        digest TEXT PRIMARY KEY, expires INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS visit_guests (
        digest TEXT PRIMARY KEY, invitation TEXT NOT NULL UNIQUE, gscd TEXT NOT NULL UNIQUE,
        source_username TEXT NOT NULL, guest_username TEXT NOT NULL UNIQUE)""",
    """CREATE TABLE IF NOT EXISTS visit_tickets (
        digest TEXT PRIMARY KEY, guest_digest TEXT NOT NULL, expires INTEGER NOT NULL)""",
    """CREATE TRIGGER IF NOT EXISTS visit_guest_one_card BEFORE INSERT ON account_gscds
       WHEN EXISTS (SELECT 1 FROM visit_guests WHERE guest_username=NEW.username AND gscd<>NEW.gscd)
       BEGIN SELECT RAISE(IGNORE); END""",
)


class VisitError(Exception):
    """Base class for a failed visit operation."""


class VisitInvalid(VisitError):
    """The supplied data cannot represent a compatible save."""


class VisitAuthError(VisitError):
    """The capability or account does not authorize this operation."""


class VisitConflict(VisitError):
    """Local ownership, an in-flight wake, or the current revision prevents this update."""


@contextmanager
def _transaction() -> Iterator[sqlite3.Connection]:
    accounts.count_accounts()  # Ensure the shared account schema exists before taking the write lock.
    with db.transaction() as conn:
        for statement in _SCHEMA:
            conn.execute(statement)
        yield conn


def _digest(secret: str) -> str:
    if not isinstance(secret, str) or not _SECRET.fullmatch(secret):
        raise VisitAuthError("Invalid capability.")
    return hashlib.sha256(secret.encode("ascii")).hexdigest()


def _canonical(value: object) -> bytes:
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise VisitInvalid("Invalid JSON data.") from exc
    if len(data) > MAX_SNAPSHOT_BYTES:
        raise VisitInvalid("This snapshot is too large.")
    return data


def snapshot_revision(snapshot: dict) -> str:
    """Hash the canonical wire encoding so either peer can verify the received save."""
    return hashlib.sha256(_canonical(snapshot)).hexdigest()


def _result(snapshot: dict) -> dict:
    return {"snapshot": snapshot, "revision": snapshot_revision(snapshot)}


def _valid_card(code: object) -> bool:
    return (isinstance(code, str) and gsid_utility.is_valid_gscd(code)
            and gsid_utility.gsid_to_gscd(gsid_utility.gscd_to_gsid(code)) == code)


def _guest(conn: sqlite3.Connection, digest: str) -> sqlite3.Row:
    row = conn.execute(
        """SELECT v.* FROM visit_guests v JOIN account_gscds l ON l.gscd=v.gscd AND l.username=v.guest_username
           JOIN accounts a ON a.username=v.guest_username WHERE v.digest=?""", (digest,)).fetchone()
    if row is None:
        raise VisitAuthError("Unknown visitor.")
    return row


def _account(conn: sqlite3.Connection, username: str, code: str, *, home: bool) -> sqlite3.Row:
    owner = conn.execute(
        """SELECT a.username,a.activated,a.pgl_privacy,a.dw_privacy FROM accounts a
           JOIN account_gscds l ON l.username=a.username WHERE l.gscd=? AND a.username=? COLLATE NOCASE""",
        (code, username)).fetchone()
    if owner is None or (home and (not owner["activated"] or owner["username"].startswith(GUEST_PREFIX))):
        raise VisitAuthError("Choose a cartridge linked to your activated account.")
    return owner


def _load(conn: sqlite3.Connection, code: str) -> dict:
    row = conn.execute("SELECT * FROM player_saves WHERE gscd=?", (code,)).fetchone()
    if row is None:
        raise VisitConflict("This cartridge has no Game Sync save.")
    save = {key: json.loads(row[key]) if row[key] is not None else None for key in _COLUMNS}
    member = (save.get("player_data") or {}).get("member")
    if not member:
        raise VisitConflict("The cartridge has not finished its first Game Sync.")
    if member.get("wake_download_pending") or (save["game_sync"] or {}).get("pending_wake"):
        raise VisitConflict("Wait for the NDS to finish its current wake download.")
    return save


def _shelf_slots(save: dict) -> list:
    slots = (save["share_data"] or {}).get("share_list", [])
    if not isinstance(slots, list) or not all(isinstance(slot, dict) for slot in slots):
        raise VisitInvalid("Invalid Share Shelf.")
    return slots


def _snapshot(conn: sqlite3.Connection, username: str, owner: sqlite3.Row, code: str) -> dict:
    save = _load(conn, code)
    profile = save["player_data"]
    member = profile["member"]
    member.pop("member_id", None)
    member.pop("member_savedata_id", None)
    profile.pop("token", None)
    if (history := travel_gifts.export(conn, code)) is not None:
        profile["travel_gifts"] = history
    sync = save["game_sync"] or {}
    for key in _LOCAL_SYNC:
        sync.pop(key, None)
    # Shelf trader links use cartridge IDs on the wire. Two hosts can assign the same member number.
    for slot in _shelf_slots(save):
        trader_id = slot.pop("old_member_savedata_id", None)
        if trader_id is not None:
            row = conn.execute(
                "SELECT gscd FROM player_saves WHERE json_extract(player_data,'$.member.member_savedata_id')=?",
                (trader_id,)).fetchone()
            if row:
                slot["old_member_gscd"] = row[0]
    return {"v": 1, "username": username, "gscd": code, "save": save,
            "visibility": {key: owner[key] for key in ("pgl_privacy", "dw_privacy")}}


def _validate(snapshot: dict) -> None:
    if not isinstance(snapshot, dict) or set(snapshot) != {"v", "username", "gscd", "save", "visibility"}:
        raise VisitInvalid("Invalid snapshot format.")
    _canonical(snapshot)
    code = snapshot["gscd"]
    username = snapshot["username"]
    save = snapshot["save"]
    privacy = snapshot["visibility"]
    if (type(snapshot["v"]) is not int or snapshot["v"] != 1 or not _valid_card(code)
            or not isinstance(username, str) or not 1 <= len(username) <= 64 or username.startswith(GUEST_PREFIX)
            or not username.isprintable() or not isinstance(save, dict) or set(save) != set(_COLUMNS)
            or any(value is not None and not isinstance(value, dict) for value in save.values())
            or not isinstance(privacy, dict) or set(privacy) != {"pgl_privacy", "dw_privacy"}
            or any(value is not None and not isinstance(value, str) for value in privacy.values())
            or any(value not in _PRIVACY for value in privacy.values())):
        raise VisitInvalid("Invalid save, visibility, or cartridge identity.")
    profile = save["player_data"] or {}
    member = profile.get("member")
    sync = save["game_sync"] or {}
    if (not isinstance(member, dict) or "token" in profile or "member_id" in member or "member_savedata_id" in member
            or member.get("gscd") != code or member.get("gsid") != gsid_utility.gscd_to_gsid(code)
            or any(key in sync for key in _LOCAL_SYNC)):
        raise VisitInvalid("Invalid cartridge profile.")
    if member.get("wake_download_pending") or "pending_wake" in sync:
        raise VisitConflict("Wait for the NDS to finish its current wake download.")
    for slot in _shelf_slots(save):
        if ("old_member_savedata_id" in slot
                or ("old_member_gscd" in slot and not _valid_card(slot["old_member_gscd"]))):
            raise VisitInvalid("Invalid Share Shelf player reference.")
    try:
        Player.from_saved(code, profile, sync, save["sleeping_pokemon"])
    except (ValueError, TypeError, KeyError) as exc:
        raise VisitInvalid("Invalid Game Sync data.") from exc


def _advance_item_counters(conn: sqlite3.Connection, save: dict) -> None:
    # The browser looks up these IDs within the selected cartridge. Reserve the imported
    # high-water marks so the next local purchase, plot, shelf swap or wish gets a new ID.
    profile = save["player_data"]
    island = profile.get("dream_island", {})
    try:
        groups = (
            ("my_interior_id", "my_interior_id", profile["member"].get("my_interior_list", [])),
            ("my_croft_id", "my_croft_id", (save["crop_data"] or {}).get("croft_list", [])),
            ("material_id", "material_id", _shelf_slots(save)),
            ("dream_encounter_id", "id", profile.get("dream_board", []) + island.get("friends", [])),
        )
        for sequence, key, entries in groups:
            ids = [entry[key] for entry in entries]
            if sequence == "dream_encounter_id" and island.get("wished") is not None:
                ids.append(island["wished"])
            if any(type(value) is not int or not 1 <= value < 2**31 for value in ids):
                raise VisitInvalid("Invalid game object ID.")
            if ids:
                conn.execute("""INSERT INTO id_counters(name,last_id) VALUES (?,?)
                    ON CONFLICT(name) DO UPDATE SET last_id=max(last_id,excluded.last_id)""", (sequence, max(ids)))
    except (TypeError, KeyError, AttributeError) as exc:
        raise VisitInvalid("Invalid game objects.") from exc


def reserve_member_id(conn: sqlite3.Connection) -> int:
    """Advance the database-wide member_id sequence beyond any player in an older import."""
    highest = conn.execute("""SELECT max(max(coalesce(json_extract(player_data,'$.member.member_savedata_id'),0),
        coalesce(json_extract(player_data,'$.member.member_id'),0))) FROM player_saves""").fetchone()[0] or 0
    return conn.execute("""INSERT INTO id_counters(name,last_id) VALUES ('member_id',?)
        ON CONFLICT(name) DO UPDATE SET last_id=max(last_id+1,excluded.last_id) RETURNING last_id""",
                        (highest + 1,)).fetchone()[0]


def _write(conn: sqlite3.Connection, snapshot: dict, current: dict | None) -> None:
    code = snapshot["gscd"]
    save = json.loads(_canonical(snapshot["save"]))
    profile = save["player_data"]
    member = profile["member"]
    if current is None:
        member["member_id"] = member["member_savedata_id"] = reserve_member_id(conn)
        profile["token"] = None
    else:
        local = current["player_data"]
        member.update({key: local["member"][key] for key in ("member_id", "member_savedata_id")})
        if "token" in local:
            profile["token"] = local["token"]
        for key in _LOCAL_SYNC:
            if key in (current["game_sync"] or {}):
                if save["game_sync"] is None:
                    save["game_sync"] = {}
                save["game_sync"][key] = current["game_sync"][key]
    for slot in _shelf_slots(save):
        trader = slot.get("old_member_gscd")
        if trader == code:
            slot["old_member_savedata_id"] = member["member_savedata_id"]
        else:
            row = conn.execute("SELECT json_extract(player_data,'$.member.member_savedata_id') FROM player_saves "
                               "WHERE gscd=?", (trader,)).fetchone()
            slot["old_member_savedata_id"] = row[0] if row else None
    if "travel_gifts" in profile:
        try:
            travel_gifts.restore(conn, code, profile.pop("travel_gifts"), member.get("rom_id"), member.get("langcode"))
        except (ValueError, TypeError) as exc:
            raise VisitInvalid("Invalid distribution history.") from exc
    _advance_item_counters(conn, save)
    values = [json.dumps(save[key], ensure_ascii=False) if save[key] is not None else None for key in _COLUMNS]
    conn.execute("""INSERT INTO player_saves
        (gscd,player_data,sleeping_pokemon,game_sync,crop_data,chest_data,share_data) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(gscd) DO UPDATE SET player_data=excluded.player_data,sleeping_pokemon=excluded.sleeping_pokemon,
        game_sync=excluded.game_sync,crop_data=excluded.crop_data,chest_data=excluded.chest_data,
        share_data=excluded.share_data""", (code, *values))


def export_local(username: str, gscd: str) -> dict:
    with _transaction() as conn:
        owner = _account(conn, username, gscd, home=True)
        return _result(_snapshot(conn, owner["username"], owner, gscd))


def _replace(conn: sqlite3.Connection, username: str, owner: sqlite3.Row, code: str,
             expected_revision: str, snapshot: dict, *, home: bool) -> dict:
    _validate(snapshot)
    if (snapshot["username"], snapshot["gscd"]) != (username, code):
        raise VisitConflict("This pairing belongs to another cartridge.")
    if not isinstance(expected_revision, str) or not _REVISION.fullmatch(expected_revision):
        raise VisitInvalid("Invalid revision.")
    current = _result(_snapshot(conn, username, owner, code))
    desired = _result(snapshot)
    if current["revision"] == desired["revision"]:
        return current
    if expected_revision != current["revision"]:
        raise VisitConflict("Both copies changed. Neither copy was overwritten.")
    if ("travel_gifts" in current["snapshot"]["save"]["player_data"]
            and "travel_gifts" not in snapshot["save"]["player_data"]):
        raise VisitConflict("Update both servers before syncing distribution history.")
    if home and snapshot["visibility"] != current["snapshot"]["visibility"]:
        raise VisitConflict("Account-wide privacy is managed on the home server.")
    _write(conn, snapshot, _load(conn, code))
    if not home:
        privacy = snapshot["visibility"]
        conn.execute("UPDATE accounts SET pgl_privacy=?,dw_privacy=? WHERE username=?",
                     (privacy["pgl_privacy"], privacy["dw_privacy"], owner["username"]))
    return desired


def apply_local(username: str, gscd: str, expected_revision: str, snapshot: dict) -> dict:
    with _transaction() as conn:
        owner = _account(conn, username, gscd, home=True)
        return _replace(conn, owner["username"], owner, gscd, expected_revision, snapshot, home=True)


def create_invite() -> str:
    secret = secrets.token_urlsafe(32)
    with _transaction() as conn:
        now = int(time.time())
        conn.execute("DELETE FROM visit_invites WHERE expires<=?", (now,))
        conn.execute("INSERT INTO visit_invites VALUES (?,?)", (_digest(secret), now + INVITE_SECONDS))
    return secret


def _read_guest(conn: sqlite3.Connection, guest: sqlite3.Row) -> dict:
    owner = _account(conn, guest["guest_username"], guest["gscd"], home=False)
    return _result(_snapshot(conn, guest["source_username"], owner, guest["gscd"]))


def redeem(invite: str, snapshot: dict, token: str) -> dict:
    invitation, digest = _digest(invite), _digest(token)
    if invitation == digest:
        raise VisitInvalid("Generate a separate pairing token.")
    with _transaction() as conn:
        previous = conn.execute("SELECT * FROM visit_guests WHERE invitation=?", (invitation,)).fetchone()
        if previous:
            if previous["digest"] != digest:
                raise VisitAuthError("Invitation already used.")
            _validate(snapshot)
            if (snapshot["username"], snapshot["gscd"]) != (previous["source_username"], previous["gscd"]):
                raise VisitConflict("This pairing belongs to another cartridge.")
            return {"token": token, **_read_guest(conn, _guest(conn, digest))}
        used = conn.execute("DELETE FROM visit_invites WHERE digest=? AND expires>?", (invitation, int(time.time())))
        if not used.rowcount:
            raise VisitAuthError("Invalid or expired invitation.")
        _validate(snapshot)
        code = snapshot["gscd"]
        if conn.execute("SELECT 1 FROM player_saves WHERE gscd=? UNION ALL SELECT 1 FROM account_gscds WHERE gscd=?",
                        (code, code)).fetchone():
            raise VisitConflict("The receiving server already has this cartridge.")
        if conn.execute("SELECT 1 FROM visit_guests WHERE digest=?", (digest,)).fetchone():
            raise VisitConflict("Pairing token is already in use.")
        alias = GUEST_PREFIX + secrets.token_hex(12)
        if conn.execute("SELECT 1 FROM accounts WHERE username=? COLLATE NOCASE", (alias,)).fetchone():
            raise VisitConflict("Guest name collision. Try again.")
        privacy = snapshot["visibility"]
        conn.execute("""INSERT INTO accounts(username,password_hash,email,registered,active_gscd,pgl_privacy,dw_privacy)
            VALUES (?,'!','',1,?,?,?)""", (alias, code, privacy["pgl_privacy"], privacy["dw_privacy"]))
        conn.execute("INSERT INTO account_gscds(gscd,username) VALUES (?,?)", (code, alias))
        conn.execute("INSERT INTO visit_guests VALUES (?,?,?,?,?)", (digest, invitation, code, snapshot["username"], alias))
        _write(conn, snapshot, None)
        return {"token": token, **_read_guest(conn, _guest(conn, digest))}


def read_snapshot(token: str) -> dict:
    with _transaction() as conn:
        return _read_guest(conn, _guest(conn, _digest(token)))


def replace_snapshot(token: str, revision: str, snapshot: dict) -> dict:
    with _transaction() as conn:
        guest = _guest(conn, _digest(token))
        owner = _account(conn, guest["guest_username"], guest["gscd"], home=False)
        return _replace(conn, guest["source_username"], owner, guest["gscd"], revision, snapshot, home=False)


def create_ticket(token: str) -> str:
    digest = _digest(token)
    secret = secrets.token_urlsafe(32)
    with _transaction() as conn:
        _guest(conn, digest)
        now = int(time.time())
        conn.execute("DELETE FROM visit_tickets WHERE expires<=?", (now,))
        conn.execute("INSERT INTO visit_tickets VALUES (?,?,?)", (_digest(secret), digest, now + TICKET_SECONDS))
    return secret


def consume_ticket(ticket: str) -> tuple[str, str, str]:
    with _transaction() as conn:
        row = conn.execute("DELETE FROM visit_tickets WHERE digest=? AND expires>? RETURNING guest_digest",
                           (_digest(ticket), int(time.time()))).fetchone()
        if row is None:
            raise VisitAuthError("Invalid or expired browser ticket.")
        guest = _guest(conn, row[0])
        return guest["guest_username"], guest["gscd"], guest["source_username"]
