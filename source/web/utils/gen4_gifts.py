"""Fourth-generation Nintendo WFC distributions, scoped to the WFC user and game."""
import hashlib
import time
from functools import cache
from http.client import HTTPException
from urllib.request import urlopen

from game_sync_server.entralinked.utility.db_manager import db
from utils.data import load_json_data

ARCHIVE = "https://raw.githubusercontent.com/ubergeek77/dwc_network_server_emulator/68fcdb2989e57a10ec8cf8398ff7506c4c73d390/dlc/"
SIZE = 936


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


def _payload(gift):
    with db.transaction() as conn:
        cached = conn.execute("SELECT content FROM gen4_gift_cache WHERE gift=?", (gift,)).fetchone()
    if cached:
        return cached[0]
    game, name = catalog()["files"][gift]
    with urlopen(f"{ARCHIVE}{game}/{name}", timeout=5) as response:
        raw = response.read(SIZE + 1)
    if len(raw) != SIZE or hashlib.sha1(b"blob 936\0" + raw).hexdigest() != gift:
        raise ValueError("The archived distribution does not match its catalog entry")
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
        selected = conn.execute(
            "SELECT game,gift FROM gen4_gift_list WHERE ticket=? AND owner=?", (ticket, owner)
        ).fetchone()
        if selected and game and selected["game"] != game:
            return b"", 400
        if action == "contents":
            if not selected:
                return b"", 404
            game, gift = selected
            if form.get("contents") != catalog()["files"][gift][1]:
                return b"", 404
        elif action in ("list", "count") and game:
            if action == "count":
                return "1", 200
            if form.get("offset", "0") not in ("", "0") or form.get("num") == "0":
                return "\r\n", 200
            if selected:
                gift = selected["gift"]
            else:
                sent = dict(conn.execute(
                    "SELECT gift,last_sent FROM gen4_gift_download WHERE owner=? AND game=?", (owner, game)
                ))
                gift = min(catalog()["games"][game], key=lambda key: sent.get(key, 0))
                conn.execute("INSERT INTO gen4_gift_list(ticket,owner,game,gift,until) VALUES(?,?,?,?,?)",
                             (ticket, owner, game, gift, now+3600))
            name = catalog()["files"][gift][1]
            return f"{name}\t\t\t\t\t{SIZE}\r\n", 200
        else:
            return b"", 400
    try:
        raw = _payload(gift)
    except (OSError, HTTPException, ValueError):
        return b"", 503
    with db.transaction() as conn:
        first = conn.execute("UPDATE gen4_gift_list SET sent=1 WHERE ticket=? AND sent=0", (ticket,))
        if first.rowcount:
            conn.execute("""INSERT INTO gen4_gift_download VALUES(?,?,?,?) ON CONFLICT(owner,game,gift)
                            DO UPDATE SET last_sent=excluded.last_sent""", (owner, game, gift, time.time_ns()))
    return raw, 200
