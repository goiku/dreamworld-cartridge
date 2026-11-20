"""Cartridge-scoped promotions and native Generation V Wonder Card deliveries."""
import binascii
import hashlib
import json
import struct
import time
from collections import Counter
from dataclasses import dataclass
from functools import cache
from urllib.parse import quote
from urllib.request import urlopen

from game_sync_server.entralinked.model.player.dream_data import DreamEncounter
from game_sync_server.entralinked.model.save_file import _crypt_array
from game_sync_server.entralinked.utility.db_manager import db
from game_sync_server.entralinked.utility.gsid_utility import gsid_to_gscd
from utils.data import load_json_data

ARCHIVE = "https://raw.githubusercontent.com/projectpokemon/EventsGallery/f1f3095183ee54dca63216164adb1f278714ec55/Released/Gen%205/Wondercards/"
LANGUAGES = {1: ("JPN", "J"), 2: ("ENG", "E"), 3: ("FRE", "F"), 4: ("ITA", "I"),
             5: ("GER", "G"), 7: ("SPA", "S"), 8: ("KOR", "K")}
VERSIONS = {20: 16, 21: 32, 22: 64, 23: 128}
ROM_CODES = {"IRA": 20, "IRB": 21, "IRD": 22, "IRE": 23}

# The original B/W Eeveelution promotion offered one of seven partners.
EEVEES = (134, 135, 136, 196, 197, 470, 471)


@dataclass(frozen=True)
class Gift:
    key: str
    group: str
    name: str
    mask: int
    language: str = ""
    filename: str = ""
    digest: str = ""
    number: int = 0
    species: int = 0
    move: int = 0
    gender: int = 0
    regions: tuple = ()
    full_digest: str = ""
    signature: str = ""


@cache
def catalog():
    gifts = {}
    for mask, species, move, gender, regions in load_json_data("dream_promotions"):
        key = f"d-{mask}-{species}-{move}"
        group = "eevee" if species in EEVEES else f"d-{species}-{move}"
        gifts[key] = Gift(key, group, "", mask, species=species, move=move, gender=gender,
                          regions=tuple(regions))
    for language, filename, digest, mask, full, signature, number in load_json_data("gift_cards"):
        key = f"w-{language}-{digest}"
        gifts[key] = Gift(key, f"card-{number}", filename.split(" - ", 1)[1][:-4],
                          mask, language, filename, digest, number, full_digest=full, signature=signature)
    return gifts


def compatible(gift, rom, lang):
    return bool(gift.mask & VERSIONS.get(rom, 0) and lang in LANGUAGES
                and (not gift.language or gift.language == LANGUAGES[lang][0])
                and (not gift.regions or LANGUAGES[lang][0] in gift.regions))


@cache
def variant_counts(rom, lang):
    return Counter(gift.group for gift in catalog().values() if compatible(gift, rom, lang))


@cache
def variant_signatures(rom, lang):
    result = {}
    for gift in catalog().values():
        if gift.signature and compatible(gift, rom, lang):
            result.setdefault(gift.signature, []).append(gift)
    return result


def schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS distribution_cartridges (
        card TEXT PRIMARY KEY, wfc TEXT NOT NULL, rom INTEGER NOT NULL, lang INTEGER NOT NULL,
        album TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS distribution_orders (
        card TEXT NOT NULL, family TEXT NOT NULL, gift TEXT NOT NULL, status TEXT NOT NULL,
        payload BLOB, PRIMARY KEY(card,family))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS distribution_lists (
        token BLOB PRIMARY KEY, card TEXT NOT NULL, gift TEXT NOT NULL, expires INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS distribution_next (
        card TEXT PRIMARY KEY, gift TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS distribution_variants (
        card TEXT NOT NULL, gift TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY(card,gift))""")


def _card_signature(pgf):
    # The receiver stamps the date and toggles the collected bit after delivery.
    return hashlib.sha256(pgf[:0xac] + pgf[0xb0:0xb4] + bytes([pgf[0xb4] & ~2]) + pgf[0xb5:204]).hexdigest()


def cartridge_album(raw, signatures=None):
    start, size = 0x1C800, 0xA94
    block = raw[start:start + size]
    if (len(raw) < start + size + 4 or not any(block)
            or binascii.crc_hqx(block, 0xffff) != int.from_bytes(raw[start + size + 2:start + size + 4], "little")):
        return None
    data = bytearray(block[:-4])
    _crypt_array(data, int.from_bytes(block[-4:], "little"))
    records = {str(i): "received" for i in range(2048) if data[i//8] & (1 << (i%8))}
    for offset in range(0x100, len(data), 204):
        number = struct.unpack_from("<H", data, offset + 0xb0)[0]
        kind = data[offset + 0xb3]
        if kind in (1, 2, 3) and 0 < number < 2048:
            records[str(number)] = "collected" if data[offset + 0xb4] & 2 else "at_center"
            if signatures is not None:
                signature = _card_signature(bytes(data[offset:offset+204]))
                signatures[signature] = records[str(number)]
    return records


def merge_album(conn, card, evidence, signatures=None):
    if evidence is None:
        return
    old = conn.execute("SELECT album,rom,lang FROM distribution_cartridges WHERE card=?", (card,)).fetchone()
    history = json.loads(old["album"]) if old and old["album"] else {}
    for number, state in evidence.items():
        # A previously seen, now discarded card still counts as received.
        if history.get(number) != "collected":
            history[number] = state
    for number in history.keys() - evidence.keys():
        if history[number] == "at_center":
            history[number] = "received"
    conn.execute("UPDATE distribution_cartridges SET album=? WHERE card=?", (json.dumps(history), card))
    if old and signatures is not None:
        known = variant_signatures(old["rom"], old["lang"])
        conn.execute("UPDATE distribution_variants SET status='received' WHERE card=? AND status='at_center'", (card,))
        for signature, phase in signatures.items():
            matches = known.get(signature, ())
            if len(matches) == 1:
                conn.execute("""INSERT INTO distribution_variants VALUES(?,?,?) ON CONFLICT(card,gift) DO UPDATE
                             SET status=excluded.status WHERE distribution_variants.status<>'collected'""",
                             (card, matches[0].key, phase))
    conn.executemany("""UPDATE distribution_orders SET status='delivered',payload=NULL
                         WHERE card=? AND family=?""", ((card, "card-" + n) for n in history))


def observe_upload(conn, card, wfc, trainer, raw):
    if (not trainer.game_sync_id or gsid_to_gscd(trainer.game_sync_id) != card
            or trainer.game not in VERSIONS or trainer.language not in LANGUAGES):
        return
    schema(conn)
    conn.execute("""INSERT INTO distribution_cartridges(card,wfc,rom,lang) VALUES(?,?,?,?)
                 ON CONFLICT(card) DO UPDATE SET wfc=excluded.wfc,rom=excluded.rom,lang=excluded.lang""",
                 (card, wfc, trainer.game, trainer.language))
    signatures = {}
    merge_album(conn, card, cartridge_album(raw, signatures), signatures)


def state(conn, card):
    schema(conn)
    identity = conn.execute("SELECT * FROM distribution_cartridges WHERE card=?", (card,)).fetchone()
    orders = {row["family"]: row for row in conn.execute(
        "SELECT family,gift,status FROM distribution_orders WHERE card=?", (card,))}
    album = json.loads(identity["album"]) if identity and identity["album"] is not None else None
    if album is not None:
        album.update(conn.execute("SELECT gift,status FROM distribution_variants WHERE card=?", (card,)))
    return identity, orders, album


def status(gift, orders, album):
    order = orders.get(gift.group)
    if gift.number and album is not None and (receipt := album.get(str(gift.number))):
        return album.get(gift.key, receipt)
    if order:
        return order["status"] if order["gift"] == gift.key else "alternative"
    if gift.number and album is None:
        return "unknown"
    return "available"


def card_binary(gift, lang):
    if gift.full_digest:
        filename = quote(gift.filename[:-4] + ".wc5full", safe="")
        url = ARCHIVE.replace("/Wondercards/", "/Wondercard%20Fulls/") + filename
        with urlopen(url, timeout=8) as response:
            full = response.read(721)
        if (len(full) != 720 or hashlib.sha1(b"blob 720\0" + full).hexdigest() != gift.full_digest
                or int.from_bytes(full[0xb0:0xb2], "little") != gift.number):
            raise ValueError("Invalid archived distribution")
        if (full[-5] == lang and full[0xce] == gift.mask and not full[0xb4] & 2
                and binascii.crc_hqx(full[:-2], 0xffff) == int.from_bytes(full[-2:], "little")):
            return full
    url = ARCHIVE + gift.language + "/" + quote(gift.filename, safe="")
    with urlopen(url, timeout=8) as response:
        raw = response.read(205)
    if (len(raw) != 204 or hashlib.sha1(b"blob 204\0" + raw).hexdigest() != gift.digest
            or int.from_bytes(raw[0xb0:0xb2], "little") != gift.number or raw[0xb3] not in (1, 2, 3)):
        raise ValueError("Invalid archived gift")
    data = bytearray(720)
    data[:204] = raw
    data[0xac:0xb0] = bytes(4)
    data[0xb4] &= ~2
    data[0xce] = gift.mask
    data[0xd0:-6] = b"\xff" * (len(data) - 6 - 0xd0)
    data[0xd0:0xd0+72] = raw[0x60:0x60+72]
    data[0xd0+72:0xd0+74] = b"\xff\xff"
    data[-5] = lang
    struct.pack_into("<H", data, 718, binascii.crc_hqx(data[:-2], 0xffff))
    return bytes(data)


def queue(card, gift, rom, lang):
    def allowed(conn):
        identity, orders, album = state(conn, card)
        if not compatible(gift, rom, lang):
            return "incompatible"
        if gift.number:
            if not identity or (identity["rom"], identity["lang"]) != (rom, lang):
                return "sync"
            if conn.execute("SELECT count(*) FROM distribution_cartridges WHERE wfc=? AND rom=? AND lang=?",
                            (identity["wfc"], rom, lang)).fetchone()[0] != 1:
                return "ambiguous"
        current = status(gift, orders, album)
        if current != "available" and not (gift.number and current == "unknown"):
            return current
        return None
    with db.transaction() as conn:
        if reason := allowed(conn):
            return reason
    # Do not hold a database write lock during a possible network fetch.
    payload = card_binary(gift, lang) if gift.number else None
    with db.transaction() as conn:
        if reason := allowed(conn):
            return reason
        conn.execute("INSERT INTO distribution_orders VALUES(?,?,?,'queued',?)",
                     (card, gift.group, gift.key, payload))
        if gift.number:
            conn.execute("INSERT OR REPLACE INTO distribution_next VALUES(?,?)", (card, gift.key))
    return "queued"


def prioritize(card, gift):
    with db.transaction() as conn:
        schema(conn)
        row = conn.execute("""SELECT 1 FROM distribution_orders WHERE card=? AND gift=?
                           AND status IN ('queued','sent') AND payload IS NOT NULL""", (card, gift.key)).fetchone()
        if row:
            conn.execute("UPDATE distribution_orders SET status='queued' WHERE card=? AND gift=?", (card, gift.key))
            conn.execute("INSERT OR REPLACE INTO distribution_next VALUES(?,?)", (card, gift.key))
    return "queued" if row else "incompatible"


def add_to_wake(conn, player, capacity):
    schema(conn)
    selected = []
    for row in conn.execute("""SELECT gift FROM distribution_orders WHERE card=? AND status='queued'
                              AND payload IS NULL ORDER BY rowid""", (player.gscd,)):
        if len(player.encounters) >= capacity:
            break
        gift = catalog().get(row["gift"])
        if gift and gift.species and compatible(gift, player.rom_id, player.langcode):
            player.encounters.append(DreamEncounter(gift.species, gift.move, 0, gift.gender, 0))
            selected.append(gift.key)
    return selected


def confirm_wake(conn, card, selected):
    schema(conn)
    conn.executemany("UPDATE distribution_orders SET status='delivered' WHERE card=? AND gift=? AND status='queued'",
                     ((card, gift) for gift in selected))


def download(wfc, form):
    """The game requests a single gift at a time. An interrupted contents request is replayable."""
    game = form.get("rhgamecd", "")
    rom = ROM_CODES.get(game[:3])
    language = form.get("attr1", "").removeprefix("MYSTERY_") or game[3:4]
    lang = next((k for k, (_, suffix) in LANGUAGES.items() if suffix == language), None)
    action = form.get("action")
    file = form.get("contents", "")
    token = hashlib.sha256(form["token"].encode("latin-1")).digest()
    with db.transaction() as conn:
        schema(conn)
        if action == "contents":
            selected = conn.execute("""SELECT o.card,o.gift,o.payload,c.rom,c.lang FROM distribution_lists l
                JOIN distribution_orders o ON o.card=l.card AND o.gift=l.gift
                JOIN distribution_cartridges c ON c.card=o.card
                WHERE l.token=? AND l.expires>=? AND c.wfc=? AND o.status IN ('queued','sent')
                AND NOT EXISTS (SELECT 1 FROM distribution_cartridges b WHERE b.wfc=c.wfc AND b.rom=c.rom
                                AND b.lang=c.lang AND b.card<>c.card)""",
                (token, int(time.time()), wfc)).fetchone()
            if (selected and (not game or rom == selected["rom"]) and
                    (not form.get("attr1") or lang == selected["lang"]) and
                    file == "DW" + catalog()[selected["gift"]].digest[:12] + ".bin"):
                conn.execute("UPDATE distribution_orders SET status='sent' WHERE card=? AND gift=?",
                             (selected["card"], selected["gift"]))
                return selected["payload"], 200
            return b"", 404
        identities = conn.execute("SELECT card FROM distribution_cartridges WHERE wfc=? AND rom=? AND lang=?",
                                  (wfc, rom, lang)).fetchall()
        row = None
        if len(identities) == 1:
            row = conn.execute("""SELECT o.gift,o.payload FROM distribution_orders o LEFT JOIN distribution_next n
                               ON n.card=o.card AND n.gift=o.gift WHERE o.card=?
                               AND (o.status='queued' OR (o.status='sent' AND EXISTS
                                   (SELECT 1 FROM distribution_lists l WHERE l.card=o.card AND l.gift=o.gift
                                    AND l.token=? AND l.expires>=?)))
                               AND o.payload IS NOT NULL ORDER BY (n.gift IS NOT NULL) DESC,o.rowid LIMIT 1""",
                               (identities[0]["card"], token, int(time.time()))).fetchone()
        if action == "count":
            return str(int(row is not None)), 200
        if action == "list":
            if not row or form.get("offset", "0") not in ("", "0") or form.get("num") == "0":
                return "\r\n", 200
            gift = catalog()[row["gift"]]
            now = int(time.time())
            conn.execute("DELETE FROM distribution_lists WHERE expires<?", (now,))
            conn.execute("INSERT OR REPLACE INTO distribution_lists VALUES(?,?,?,?)",
                         (token, identities[0]["card"], gift.key, now + 3600))
            return f"DW{gift.digest[:12]}.bin\t\tMYSTERY_{language}\t{gift.mask << 16:x}\t\t720\r\n", 200
    return b"", 400
