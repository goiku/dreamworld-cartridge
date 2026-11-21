"""Fourth-generation Nintendo WFC distributions, scoped to the WFC user and game."""
import hashlib
import json
import secrets
import struct
import time
from collections import Counter
from functools import cache
from http.client import HTTPException
from urllib.parse import quote
from urllib.request import urlopen

from game_sync_server.entralinked.utility.db_manager import db
from utils.data import load_json_data
from utils import gen4_events as events

ARCHIVE = "https://raw.githubusercontent.com/ubergeek77/dwc_network_server_emulator/68fcdb2989e57a10ec8cf8398ff7506c4c73d390/dlc/"
SIZE = 936
GALLERY = "https://raw.githubusercontent.com/projectpokemon/EventsGallery/f1f3095183ee54dca63216164adb1f278714ec55/Released/Gen%204/Wondercards/"


@cache
def catalog():
    return load_json_data("gen4_wireless_gifts")


def game_code(form):
    for field in ("rhgamecd", "gamecd"):
        code = form.get(field)
        if code in catalog()["games"]:
            return code
    return None


def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS gen4_gift_list (
        ticket BLOB PRIMARY KEY, owner TEXT, game TEXT, gift TEXT, until INTEGER, sent INTEGER DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS gen4_gift_download (
        owner TEXT, game TEXT, gift TEXT, last_sent INTEGER, PRIMARY KEY(owner,game,gift))""")
    conn.execute("CREATE TABLE IF NOT EXISTS gen4_gift_cache (gift TEXT PRIMARY KEY, content BLOB)")
    conn.execute("""CREATE TABLE IF NOT EXISTS g4_receivers (
        owner TEXT, game TEXT, trainer TEXT, album TEXT, PRIMARY KEY(owner,game))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS g4_bind (
        browser TEXT, game TEXT, owner TEXT, PRIMARY KEY(browser,game))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS g4_known (
        browser TEXT, game TEXT, owner TEXT, PRIMARY KEY(browser,game,owner))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS g4_window (
        browser TEXT, game TEXT, until INTEGER, attempts INTEGER, target TEXT, PRIMARY KEY(browser,game))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS g4_pin (
        ticket BLOB PRIMARY KEY, code TEXT UNIQUE, owner TEXT, game TEXT, until INTEGER, used INTEGER DEFAULT 0)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS g4_orders (
        owner TEXT, game TEXT, number INTEGER, gift TEXT, position INTEGER, state TEXT,
        PRIMARY KEY(owner,game,number))""")


def filename(key):
    if key in events.events():
        return "G4" + key[:20] + ".myg"
    return catalog()["files"][key][1]


def pair(conn, browser, game, code, friend_code=""):
    now = int(time.time())
    if not code:
        target = None
        if friend_code:
            digits = friend_code.replace("-","").replace(" ","")
            if not digits.isascii() or not digits.isdigit() or len(digits)!=12:
                return "pair_invalid"
            match = conn.execute("""SELECT DISTINCT u.user_id FROM wfc_users u,json_each(u.profiles) p
                WHERE json_extract(p.value,'$.id')=?""", (int(digits) & 0xffffffff,)).fetchall()
            if len(match)!=1:
                return "pair_invalid"
            target = match[0][0]
        conn.execute("INSERT OR REPLACE INTO g4_window VALUES(?,?,?,0,?)", (browser,game,now+600,target))
        return "pair_ready"
    attempt = conn.execute("""UPDATE g4_window SET attempts=attempts+1
        WHERE browser=? AND game=? AND until>? AND attempts<8""", (browser,game,now))
    pin = conn.execute("""SELECT p.owner FROM g4_pin p JOIN g4_window w ON w.game=p.game
        WHERE w.browser=? AND p.game=? AND p.code=? AND p.until>? AND p.used=0
        AND (w.target IS NULL OR w.target=p.owner)""", (browser,game,code,now)).fetchone()
    if not attempt.rowcount or not pin:
        return "pair_invalid"
    owner = pin["owner"]
    conn.execute("INSERT OR IGNORE INTO g4_receivers(owner,game) VALUES(?,?)", (owner,game))
    conn.execute("INSERT OR REPLACE INTO g4_bind VALUES(?,?,?)", (browser,game,owner))
    conn.execute("INSERT OR IGNORE INTO g4_known VALUES(?,?,?)", (browser,game,owner))
    conn.execute("UPDATE g4_pin SET used=1 WHERE owner=? AND game=?", (owner,game))
    conn.execute("DELETE FROM g4_window WHERE browser=? AND game=?", (browser,game))
    return "paired"


def receiver(conn, browser, game):
    return conn.execute("""SELECT r.* FROM g4_bind b JOIN g4_receivers r USING(owner,game)
        WHERE b.browser=? AND b.game=?""", (browser,game)).fetchone()


def order_state(conn, dev):
    orders = {r["number"]:r for r in conn.execute("""SELECT * FROM g4_orders
        WHERE owner=? AND game=? ORDER BY position,number""", (dev["owner"],dev["game"]))}
    # Preserve sends from the original wireless rotation (including before web pairing).
    legacy = set()
    for (gift,) in conn.execute("SELECT gift FROM gen4_gift_download WHERE owner=? AND game=?", (dev["owner"],dev["game"])):
        if gift in catalog()["files"]:
            legacy.add(int(filename(gift).split("_")[1]))
    return orders, json.loads(dev["album"]) if dev["album"] is not None else None, legacy


def status(key, event, orders, album, legacy):
    number = event["number"]
    if not number:
        return "archive_only"
    if album and str(number) in album:
        return album[str(number)]
    if number in orders:
        return orders[number]["state"] if orders[number]["gift"] == key else "alternative"
    if number in legacy:
        return "sent"
    return "available" if album is not None else "unknown"


def enqueue(conn, dev, action, key=None):
    owner, game = dev["owner"], dev["game"]
    pool = events.selection(game)
    orders, album, legacy = order_state(conn, dev)
    groups = Counter(e["number"] for e in pool.values())
    keys = pool if action == "bulk" else [key]
    if action != "bulk" and key not in pool:
        raise ValueError("Incompatible event")
    count = 0
    for candidate in keys:
        event = pool[candidate]
        number = event["number"]
        old = status(candidate,event,orders,album,legacy)
        if action == "bulk" and events.choose_individually(event,groups):
            continue
        if old in ("available","unknown") or action == "next" and old in ("sent","queued"):
            position = time.time_ns()
            conn.execute("""INSERT INTO g4_orders VALUES(?,?,?,?,?,'queued') ON CONFLICT(owner,game,number)
                DO UPDATE SET position=excluded.position,state='queued',gift=excluded.gift""",
                (owner,game,number,candidate,-position if action=="next" else position))
            count += 1
    return count


def scan(conn, dev, raw):
    trainer, evidence = events.album(raw, dev["game"])
    if dev["trainer"] and dev["trainer"] != trainer:
        raise ValueError("Different save")
    history = json.loads(dev["album"] or "{}")
    for number, state in evidence.items():
        if state == "collected" or history.get(number) not in ("collected","pending_pickup"):
            history[number] = state
    conn.execute("UPDATE g4_receivers SET trainer=?,album=? WHERE owner=? AND game=?",
                 (trainer,json.dumps(history),dev["owner"],dev["game"]))
    conn.executemany("UPDATE g4_orders SET state='received' WHERE owner=? AND game=? AND number=?",
                     ((dev["owner"],dev["game"],number) for number in history))


def _payload(gift):
    with db.transaction() as conn:
        cached = conn.execute("SELECT content FROM gen4_gift_cache WHERE gift=?", (gift,)).fetchone()
    if cached:
        return cached[0]
    event = events.events().get(gift)
    size = 856 if event else SIZE
    url = GALLERY + quote(event["path"]) if event else ARCHIVE + "/".join(catalog()["files"][gift])
    with urlopen(url, timeout=6) as response:
        raw = response.read(size + 1)
    if len(raw) != size or hashlib.sha1(f"blob {size}\0".encode() + raw).hexdigest() != gift:
        raise ValueError("The archived distribution does not match its catalog entry")
    if event:
        raw = events.packet(raw, event)
    with db.transaction() as conn:
        conn.execute("INSERT OR IGNORE INTO gen4_gift_cache VALUES(?,?)", (gift, raw))
    return raw


def download(owner, form, game):
    action = form.get("action")
    ticket = hashlib.sha256(form["token"].encode("latin-1")).digest()
    now = int(time.time())
    with db.transaction() as conn:
        _schema(conn)
        conn.execute("DELETE FROM gen4_gift_list WHERE until<?", (now,))
        conn.execute("DELETE FROM g4_window WHERE until<=?", (now,))
        conn.execute("DELETE FROM g4_pin WHERE ticket NOT IN (SELECT ticket FROM gen4_gift_list)")
        selected = conn.execute(
            "SELECT game,gift FROM gen4_gift_list WHERE ticket=? AND owner=?", (ticket, owner)
        ).fetchone()
        if selected and game and selected["game"] != game:
            return b"", 400
        if action == "contents":
            if not selected:
                return b"", 404
            game, gift = selected
            if form.get("contents") != filename(gift):
                return b"", 404
        elif action in ("list", "count") and game:
            head = conn.execute("""SELECT gift FROM g4_orders WHERE owner=? AND game=? AND state='queued'
                ORDER BY position,number LIMIT 1""", (owner,game)).fetchone()
            managed = conn.execute("SELECT 1 FROM g4_receivers WHERE owner=? AND game=?", (owner,game)).fetchone()
            pairing = conn.execute("""SELECT 1 FROM g4_window WHERE game=? AND attempts<8 AND
                (target=? OR (target IS NULL AND ?=0)) LIMIT 1""", (game,owner,int(bool(managed)))).fetchone()
            available = selected or head or not managed or pairing
            if action == "count":
                return "1" if available else "0", 200
            if not available:
                return "\r\n", 200
            if form.get("offset", "0") not in ("", "0") or form.get("num") == "0":
                return "\r\n", 200
            if selected:
                gift = selected["gift"]
            else:
                sent = dict(conn.execute(
                    "SELECT gift,last_sent FROM gen4_gift_download WHERE owner=? AND game=?", (owner, game)
                ))
                gift = head["gift"] if head and not pairing else min(catalog()["games"][game], key=lambda key: sent.get(key, 0))
                conn.execute("INSERT INTO gen4_gift_list(ticket,owner,game,gift,until) VALUES(?,?,?,?,?)",
                             (ticket, owner, game, gift, now+3600))
                if pairing:
                    while True:
                        code = str(1000000000 + secrets.randbelow(9000000000))
                        if conn.execute("""INSERT OR IGNORE INTO g4_pin(ticket,code,owner,game,until)
                                VALUES(?,?,?,?,?)""", (ticket,code,owner,game,now+600)).rowcount:
                            break
            name = filename(gift)
            return f"{name}\t\t\t\t\t{SIZE}\r\n", 200
        else:
            return b"", 400
    try:
        raw = _payload(gift)
    except (OSError, HTTPException, ValueError):
        return b"", 503
    with db.transaction() as conn:
        pin = conn.execute("SELECT code FROM g4_pin WHERE ticket=?", (ticket,)).fetchone()
        if pin:
            # Platinum previews the outer header and stores the inner card with its archival title.
            digits = [0x121+int(digit) for digit in pin["code"]]
            prefix = struct.pack("<11H", *digits, 1)
            return prefix + raw[:48] + b"\xff\xff" + raw[72:], 200
        first = conn.execute("UPDATE gen4_gift_list SET sent=1 WHERE ticket=? AND sent=0", (ticket,))
        if first.rowcount:
            conn.execute("""INSERT INTO gen4_gift_download VALUES(?,?,?,?) ON CONFLICT(owner,game,gift)
                            DO UPDATE SET last_sent=excluded.last_sent""", (owner, game, gift, time.time_ns()))
            conn.execute("UPDATE g4_orders SET state='sent' WHERE owner=? AND game=? AND gift=? AND state='queued'",
                         (owner,game,gift))
    return raw, 200
