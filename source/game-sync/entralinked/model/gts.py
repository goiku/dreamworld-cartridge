"""Generation V Global Trade Station records and durable two-phase exchanges."""
import hashlib
import json
import secrets
import sqlite3
import struct
import time
from datetime import datetime, timezone

from .cartridge_identity import authenticated_profile_key
from .save_file import PERSONAL_DATA, DataReader, Pokemon, _decrypt_pkm
from ..utility.db_manager import DBManager

OK = b"\x01\x00"
UNAVAILABLE = b"\x02\x00"
DEPOSITED = b"\x04\x00"
EMPTY = b"\x05\x00"
INELIGIBLE = b"\x0c\x00"
OCCUPIED = b"\x0e\x00"
RECORD_SIZE = 296
EITHER = 3


def pokemon_core(party: bytes, allow_plain: bool = False) -> tuple[bytes, Pokemon]:
    """Read the boxed part of a party record, retaining the original party for transfer."""
    if len(party) < 136:
        raise ValueError("Incomplete party record")
    raw = party[:136]
    checksum = int.from_bytes(raw[6:8], "little")
    choices = [_decrypt_pkm(raw)]
    if allow_plain:
        choices.append(raw)
    for core in choices:
        if (sum(struct.unpack_from("<64H", core, 8)) & 0xffff) != checksum:
            continue
        pokemon = Pokemon(core)
        if (core[4:6] != bytes(2) or pokemon.form not in PERSONAL_DATA.get(pokemon.natdex, {})
                or pokemon.nature >= 25 or core[0x3b] & 0x40 or sum(core[0x18:0x1e]) > 510):
            continue
        return core, pokemon
    raise ValueError("Invalid or untradeable party record")


def record_is_valid(record: bytes, pokemon: Pokemon) -> bool:
    species, gender, level, wanted, sex, low, high = struct.unpack_from("<HBBHBBB", record, 0xec)
    return (species == pokemon.natdex and gender == pokemon.gender + 1 and level == pokemon.level
            and 1 <= wanted <= 649 and sex in (1, 2, EITHER) and low <= 100
            and high <= 100 and (not high or low <= high))


def satisfies(offered: bytes, wanted: bytes) -> bool:
    species, gender, level = struct.unpack_from("<HBB", offered, 0xec)
    requested, sex, low, high = struct.unpack_from("<HBBB", wanted, 0xf0)
    return species == requested and (sex == EITHER or gender == sex) and low <= level <= (high or 100)


def ds_timestamp() -> bytes:
    now = datetime.now(timezone.utc)
    return struct.pack("<H6B", now.year, now.month, now.day, now.hour, now.minute, now.second, 0)


def journal_summary(record: bytes) -> str:
    _, pokemon = pokemon_core(record)
    return json.dumps({"monsno": pokemon.natdex, "form_no": pokemon.form, "poke_level": pokemon.level,
                       "sex": (0, 1, 9)[pokemon.gender], "country_id": record[0x120]})


def private_summary(record: bytes) -> dict:
    core, mon = pokemon_core(record)
    return {"monsno": mon.natdex, "form_no": mon.form, "poke_level": mon.level, "sex": (0, 1, 9)[mon.gender],
            "country_id": record[0x120], "version": record[0x124], "moves": struct.unpack_from("<4H", core, 0x28),
            "item": struct.unpack_from("<H", core, 0x0a)[0], "trainer": DataReader(record).read_str(0x110, 16)}


def _record_profile(conn: sqlite3.Connection, pid: int, record: bytes) -> bytes | None:
    trainer_id, = struct.unpack_from("<I", record, 0x10c)
    return authenticated_profile_key(conn, pid, trainer_id, record[0x124], record[0x125], record[0x110:0x120])


class GlobalTradeStation:
    record_size = RECORD_SIZE
    max_species = 649
    country_offset = 0x120
    traded_offset = 0x123
    search_prefix = OK
    listing_profile = staticmethod(_record_profile)

    def __init__(self, db: DBManager) -> None:
        self.db = db

    def remember_profile(self, pid: int, data: bytes) -> None:
        with self.db.transaction() as conn:
            authenticated_profile_key(conn, pid, struct.unpack_from("<I", data, 4)[0],
                                      data[0], data[1], data[8:24])

    def validation_ticket(self, pid: int, core: bytes) -> bytes:
        ticket = secrets.token_bytes(128)
        now = int(time.time())
        with self.db.transaction() as conn:
            conn.execute("DELETE FROM gts_validation WHERE expires < ?", (now,))
            conn.execute("INSERT INTO gts_validation(ticket, pid, pokemon, expires) VALUES (?, ?, ?, ?)",
                         (hashlib.sha256(ticket).digest(), pid, hashlib.sha256(core).digest(), now + 1800))
        return ticket

    def dispatch(self, action: str, pid: int, data: bytes) -> bytes:
        if action == "info":
            return OK
        with self.db.transaction() as conn:
            slot = conn.execute("SELECT * FROM gts_slots WHERE owner=?", (pid,)).fetchone()
            if action == "result":
                if slot is None or slot["state"] == "draft":
                    return EMPTY
                return slot["record"] if slot["state"] == "received" else DEPOSITED
            if action == "get":
                if slot is None or slot["state"] == "draft":
                    return EMPTY
                return slot["record"]
            if action in ("return", "delete"):
                return self._remove(conn, pid, action, slot)
            if action == "search":
                return self._search(conn, pid, data)
            if action in ("post", "exchange"):
                return self._offer(conn, pid, action, data, slot)
            if action in ("post_finish", "exchange_finish") and len(data) == 8:
                return self._finish(conn, pid, action, slot)
            raise ValueError("Unexpected GTS request")

    @staticmethod
    def _remember(conn: sqlite3.Connection, pid: int, action: str) -> None:
        conn.execute("INSERT INTO gts_last(owner,action) VALUES(?,?) ON CONFLICT(owner) "
                     "DO UPDATE SET action=excluded.action", (pid, action))

    @staticmethod
    def _already(conn: sqlite3.Connection, pid: int, action: str) -> bool:
        return conn.execute("SELECT 1 FROM gts_last WHERE owner=? AND action=?", (pid, action)).fetchone() is not None

    def _remove(self, conn: sqlite3.Connection, pid: int, action: str, slot: sqlite3.Row | None) -> bytes:
        if slot is None and self._already(conn, pid, action):
            return OK
        expected = "listed" if action == "return" else "received"
        if slot is None or slot["state"] != expected:
            return UNAVAILABLE if action == "return" else EMPTY
        conn.execute("DELETE FROM gts_listing_identity WHERE slot=?", (slot["id"],))
        conn.execute("DELETE FROM gts_slots WHERE owner=?", (pid,))
        self._remember(conn, pid, action)
        return OK

    def _search(self, conn: sqlite3.Connection, pid: int, data: bytes) -> bytes:
        if len(data) not in (7, 8):
            raise ValueError("Invalid search length")
        species, sex, low, high, _, count = struct.unpack_from("<HBBBBB", data)
        if not 1 <= species <= self.max_species or sex not in (1, 2, EITHER):
            raise ValueError("Invalid search criteria")
        country = data[7] if len(data) == 8 else 0
        rows = conn.execute("""SELECT id,record FROM gts_slots WHERE state='listed' AND owner<>?
            AND species=? AND (?=3 OR gender=?) AND level BETWEEN ? AND ?
            AND (?=0 OR country=?) ORDER BY id DESC LIMIT ?""",
            (pid, species, sex, sex, low, high or 100, country, country, min(count, 7))).fetchall()
        conn.execute("DELETE FROM gts_seen WHERE viewer=?", (pid,))
        conn.executemany("INSERT INTO gts_seen(viewer,slot) VALUES(?,?)", ((pid, row["id"]) for row in rows))
        return self.search_prefix + b"".join(row["record"] for row in rows)

    def _validated_record(self, conn, pid, action, data):
        if len(data) != 432:
            raise ValueError("Invalid offer length")
        record = data[:RECORD_SIZE]
        try:
            core, pokemon = pokemon_core(record)
        except ValueError:
            return None
        receipt = conn.execute("SELECT 1 FROM gts_validation WHERE ticket=? AND pid=? AND pokemon=? AND expires>=?",
            (hashlib.sha256(data[300:428]).digest(), pid, hashlib.sha256(core).digest(), int(time.time()))).fetchone()
        if not receipt or not record_is_valid(record, pokemon):
            return None
        return record

    def _offer(self, conn: sqlite3.Connection, pid: int, action: str, data: bytes, slot: sqlite3.Row | None) -> bytes:
        record = self._validated_record(conn, pid, action, data)
        if record is None:
            return INELIGIBLE
        record_key = hashlib.sha256(record).digest()
        if action == "post":
            if slot is not None:
                return OK if slot["state"] == "draft" and slot["origin"] == record_key else OCCUPIED
            listing = bytearray(record)
            listing[0xf8:0x108] = ds_timestamp() + bytes(8)
            struct.pack_into("<I", listing, 0x108, pid)
            listing[self.traded_offset] = 0
            created = conn.execute("""INSERT INTO gts_slots(owner,state,record,origin,species,gender,level,country)
                VALUES (?,'draft',?,?,?,?,?,?)""",
                (pid, listing, record_key, int.from_bytes(record[0xec:0xee], "little"),
                 record[0xee], record[0xef], record[self.country_offset]))
            key = self.listing_profile(conn, pid, listing)
            if key:
                conn.execute("INSERT INTO gts_listing_identity(slot,identity) VALUES(?,?)", (created.lastrowid, key))
            self._remember(conn, pid, action)
            return OK
        target, = struct.unpack_from("<I", data, self.record_size)
        if target == pid:
            return UNAVAILABLE
        listing = conn.execute("SELECT * FROM gts_slots WHERE owner=?", (target,)).fetchone()
        if listing is None:
            return UNAVAILABLE
        if listing["state"] == "reserved" and listing["partner"] == pid and listing["partner_key"] == record_key:
            return listing["record"]
        if listing["state"] != "listed":
            return UNAVAILABLE
        if not conn.execute("SELECT 1 FROM gts_seen WHERE viewer=? AND slot=?", (pid, listing["id"])).fetchone():
            return UNAVAILABLE
        if not satisfies(record, listing["record"]) or not satisfies(listing["record"], record):
            return INELIGIBLE
        if conn.execute("SELECT 1 FROM gts_slots WHERE partner=? AND state='reserved'", (pid,)).fetchone():
            return UNAVAILABLE
        conn.execute("UPDATE gts_slots SET state='reserved',partner=?,partner_key=?,incoming=? WHERE id=?",
                     (pid, record_key, record, listing["id"]))
        self._remember(conn, pid, action)
        return listing["record"]

    def _finish(self, conn: sqlite3.Connection, pid: int, action: str, slot: sqlite3.Row | None) -> bytes:
        if self._already(conn, pid, action):
            return OK
        if action == "post_finish":
            if slot is None or slot["state"] != "draft":
                return UNAVAILABLE
            conn.execute("UPDATE gts_slots SET state='listed' WHERE owner=?", (pid,))
        else:
            held = conn.execute("SELECT * FROM gts_slots WHERE partner=? AND state='reserved'", (pid,)).fetchone()
            if held is None:
                return UNAVAILABLE
            previous = held["record"]
            incoming = held["incoming"]
            depositor = held["owner"]
            self._log_trade(conn, depositor, pid, previous, incoming)
            arrival = bytearray(held["incoming"])
            arrival[0xec:0xf5] = previous[0xec:0xf5]
            arrival[0xf8:0x100] = previous[0xf8:0x100]
            arrival[0x100:0x108] = ds_timestamp()
            arrival[0x108:0x10c] = previous[0x108:0x10c]
            arrival[self.traded_offset] = 1
            conn.execute("""UPDATE gts_slots SET state='received',record=?,partner=NULL,
                incoming=NULL,partner_key=NULL WHERE id=?""", (arrival, held["id"]))
        self._remember(conn, pid, action)
        return OK

    def _log_trade(self, conn, depositor, pid, previous, incoming):
        journal = conn.execute("INSERT INTO gts_journal(side_a,side_b) VALUES(?,?)",
                               (journal_summary(previous), journal_summary(incoming)))
        conn.execute("""INSERT INTO gts_profile_events(trade_id,pid_a,pid_b,key_a,key_b,
                        details_a,details_b,traded_at) VALUES(?,?,?,?,?,?,?,?)""",
                     (journal.lastrowid, depositor, pid, _record_profile(conn, depositor, previous),
                      _record_profile(conn, pid, incoming), json.dumps(private_summary(previous)),
                      json.dumps(private_summary(incoming)), int(time.time())))
