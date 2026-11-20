"""Authenticated, reciprocal exchanges of signed island views and delivery receipts."""

import hashlib
import http.client
import ipaddress
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from tlslite.utils.cipherfactory import createCHACHA20

from config import SAVE_DIR
from utils import offline_islands as islands
from utils import island_actions as actions
from utils.web_network import PRIVATE_LANS

PORT = 8094
TAILNET = ipaddress.IPv4Network("100.64.0.0/10")
LIMIT = 800 * 1024
SECRET = re.compile(r"[0-9a-f]{64}")
INTERVAL = 30


class PeerError(ValueError):
    """A pairing or exchange could not be completed safely."""


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    SAVE_DIR.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(SAVE_DIR / "island-peers.sqlite3", timeout=10)) as db:
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE IF NOT EXISTS invites(id TEXT PRIMARY KEY, secret TEXT, card TEXT, until INTEGER, used TEXT);
            CREATE TABLE IF NOT EXISTS links(id TEXT PRIMARY KEY, secret TEXT, card TEXT, island TEXT,
                address TEXT, heard INTEGER DEFAULT 0, attempted INTEGER DEFAULT 0, sent INTEGER DEFAULT 0,
                UNIQUE(card,island));
            CREATE TABLE IF NOT EXISTS joining(id TEXT PRIMARY KEY, card TEXT, address TEXT, secret TEXT);
            CREATE TABLE IF NOT EXISTS listeners(address TEXT PRIMARY KEY, interface TEXT, checked INTEGER);
            CREATE TABLE IF NOT EXISTS receipts(link TEXT, event TEXT, PRIMARY KEY(link,event));
            CREATE TABLE IF NOT EXISTS offline(link TEXT PRIMARY KEY);
        """)
        with db:
            yield db


def identifier(secret: str) -> str:
    if not isinstance(secret, str) or not SECRET.fullmatch(secret):
        raise PeerError("invalid_code")
    return hashlib.sha256(bytes.fromhex(secret)).hexdigest()


def now() -> int:
    return int(time.time())


def interfaces() -> list[str]:
    """Advertise only the launcher's verified physical adapter and the VPN client's own IP."""
    networks = []
    state = os.environ.get("DW_WEB_LAN_STATE")
    try:
        lan = Path(state).read_text("ascii").strip() if state else os.environ.get("DW_WEB_LAN")
        if lan:
            iface = ipaddress.IPv4Interface(lan)
            if any(iface.network.subnet_of(net) for net in PRIVATE_LANS):
                networks.append(str(iface))
    except (ValueError, OSError):
        pass
    exe = shutil.which("tailscale")
    if not exe and os.name == "nt":
        path = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
        if path.is_file():
            exe = str(path)
    if exe:
        try:
            result = subprocess.run(
                [exe, "ip", "-4"],
                check=True,
                capture_output=True,
                timeout=4,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            ip = ipaddress.IPv4Address(result.stdout.decode("ascii").strip())
            if ip in TAILNET:
                networks.insert(0, f"{ip}/10")
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
    return networks


def advertise(listeners: list[str]) -> None:
    with database() as db:
        db.execute("DELETE FROM listeners")
        db.executemany("INSERT INTO listeners VALUES(?,?,?)", [(net.split("/")[0], net, now()) for net in listeners])


def available() -> list[str]:
    with database() as db:
        return [r[0] for r in db.execute("SELECT interface FROM listeners WHERE checked>?", (now() - 60,))]


def source_address(address: str) -> str:
    dest = ipaddress.IPv4Address(address)
    adapters = [ipaddress.IPv4Interface(value) for value in available()]
    if dest not in {i.ip for i in adapters}:
        for iface in adapters:
            if dest in iface.network and dest not in (iface.network.network_address, iface.network.broadcast_address):
                return str(iface.ip)
    raise PeerError("unreachable_private_network")


def invite(card: str) -> dict:
    adapters = available()
    if not adapters:
        raise PeerError("no_private_listener")
    # Ensure an authenticated owner actually has a shareable island.
    islands.export_island(card)
    secret = secrets.token_hex(32)
    expiry = now() + 1800
    with database() as db:
        db.execute("DELETE FROM invites WHERE until<=?", (now(),))
        db.execute("INSERT INTO invites VALUES(?,?,?,?,NULL)", (identifier(secret), secret, card, expiry))
    addresses = [iface.split("/")[0] for iface in adapters]
    return {"expires": expiry, "codes": [{"address": ip, "code": f"DWI1/{ip}/{secret}"} for ip in addresses]}


def seal(secret: str, data: dict, context: bytes) -> bytes:
    # Both directions and both operations use distinct associated data. A reply
    # is bound to its unique request nonce, even if a LAN address was reassigned.
    nonce = secrets.token_bytes(12)
    plain = json.dumps(data, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()
    if len(plain) + 28 > LIMIT:
        raise PeerError("message_too_large")
    cipher = createCHACHA20(bytearray.fromhex(secret))
    return nonce + bytes(cipher.seal(bytearray(nonce), bytearray(plain), bytearray(context)))


def unseal(secret: str, raw: bytes, context: bytes) -> dict:
    if not 28 <= len(raw) <= LIMIT:
        raise PeerError("invalid_message")
    plain = createCHACHA20(bytearray.fromhex(secret)).open(bytearray(raw[:12]), bytearray(raw[12:]), bytearray(context))
    if plain is None:
        raise PeerError("invalid_message")
    try:
        result = json.loads(plain)
    except (ValueError, RecursionError) as exc:
        raise PeerError("invalid_message") from exc
    if not isinstance(result, dict):
        raise PeerError("invalid_message")
    return result


def send(address: str, action: str, secret: str, data: dict) -> dict:
    ip = source_address(address)
    tag = b"island-v1/" + action.encode("ascii")
    raw = seal(secret, data, tag)
    conn = http.client.HTTPConnection(address, PORT, timeout=8, source_address=(ip, 0))
    try:
        conn.request(
            "POST",
            "/v1/" + action,
            raw,
            {"Content-Type": "application/octet-stream", "X-Island-Key": identifier(secret)},
        )
        resp = conn.getresponse()
        if resp.status != 200:
            raise PeerError("pairing_rejected" if resp.status < 500 else "offline")
        return unseal(secret, resp.read(LIMIT + 1), tag + b"/reply/" + raw[:12])
    except (OSError, http.client.HTTPException) as exc:
        raise PeerError("offline") from exc
    finally:
        conn.close()


def join(card: str, code: str) -> dict:
    try:
        prefix, address, invite_secret = code.strip().split("/")
        if prefix != "DWI1":
            raise ValueError
        invitation = identifier(invite_secret)
        source_address(address)
    except (AttributeError, ValueError) as exc:
        raise PeerError("invalid_or_unreachable_code") from exc
    doc = islands.export_island(card)
    with database() as db:
        db.execute("INSERT OR IGNORE INTO joining VALUES(?,?,?,?)", (invitation, card, address, secrets.token_hex(32)))
        row = db.execute("SELECT * FROM joining WHERE id=?", (invitation,)).fetchone()
        if (row["card"], row["address"]) != (card, address):
            raise PeerError("invitation_already_claimed")
    key = row["secret"]
    answer = send(address, "pair", invite_secret, {"snapshot": doc, "key": key})
    remote = answer.get("snapshot")
    if not isinstance(remote, dict):
        raise PeerError("invalid_message")
    islands.validate_snapshot(remote)
    if doc["island_id"] == remote["island_id"]:
        raise PeerError("own_island")
    with database() as db:
        add_link(db, card, remote["island_id"], address, key)
    cached = islands.import_island(card, remote)
    with database() as db:
        db.execute("UPDATE links SET heard=? WHERE id=?", (now(), identifier(key)))
    return {"island_id": cached["island_id"], "last_sync": now(), "online": True}


def add_link(db, card: str, island: str, address: str, key: str) -> None:
    digest = identifier(key)
    db.execute(
        "INSERT OR IGNORE INTO links(id,secret,card,island,address) VALUES(?,?,?,?,?)",
        (digest, key, card, island, address),
    )
    row = db.execute("SELECT card,island FROM links WHERE id=?", (digest,)).fetchone()
    if not row or tuple(row) != (card, island):
        raise PeerError("already_paired")


def receive_pair(address: str, invitation: str, msg: dict) -> dict:
    doc, key = msg.get("snapshot"), msg.get("key")
    if not isinstance(doc, dict) or not isinstance(key, str):
        raise PeerError("invalid_message")
    digest = identifier(key)
    islands.validate_snapshot(doc)
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM invites WHERE id=? AND until>?", (invitation, now())).fetchone()
        if not row or row["used"] not in (None, digest):
            raise PeerError("invitation_used")
        card = row["card"]
        local = islands.export_island(card)
        if local["island_id"] == doc["island_id"]:
            raise PeerError("own_island")
        if row["used"] and not db.execute("SELECT 1 FROM links WHERE id=?", (digest,)).fetchone():
            raise PeerError("invitation_used")
        add_link(db, card, doc["island_id"], address, key)
        db.execute("UPDATE invites SET used=? WHERE id=?", (digest, invitation))
    islands.import_island(card, doc)
    return {"snapshot": local}


def link_rows(card: str | None = None) -> list[sqlite3.Row]:
    with database() as db:
        if card is None:
            return list(db.execute("SELECT * FROM links ORDER BY attempted,id"))
        return list(
            db.execute(
                "SELECT l.*, (o.link IS NULL) AS reachable FROM links l "
                "LEFT JOIN offline o ON o.link=l.id WHERE l.card=?",
                (card,),
            )
        )


def lookup(card: str, island: str) -> sqlite3.Row:
    with database() as db:
        row = db.execute("SELECT * FROM links WHERE card=? AND island=?", (card, island)).fetchone()
        if not row:
            raise PeerError("not_paired")
        return row


def forget(card: str, island: str) -> None:
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        if actions.pending(card,island):
            raise PeerError("pending_actions")
        actions.clear_capability(card,island)
        db.execute(
            "DELETE FROM receipts WHERE link IN (SELECT id FROM links WHERE card=? AND island=?)", (card, island)
        )
        db.execute("DELETE FROM offline WHERE link IN (SELECT id FROM links WHERE card=? AND island=?)", (card, island))
        db.execute("DELETE FROM links WHERE card=? AND island=?", (card, island))


def request_interaction(card, island, version, kind, slot, payment):
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        if not db.execute("SELECT 1 FROM links WHERE card=? AND island=?", (card,island)).fetchone():
            raise PeerError("not_paired")
        actions.request_action(card,island,version,kind,slot,payment)


def _known(card: str, island: str) -> int:
    try:
        return islands.get_friend(card, island)["version"]
    except islands.IslandNotFound:
        return 0


def _import(card: str, island: str, doc) -> None:
    if doc is not None:
        islands.validate_snapshot(doc)
        if doc["island_id"] != island:
            raise PeerError("island_changed")
        islands.import_island(card, doc)


def _batch(msg: dict, field: str) -> list:
    batch = msg.get(field)
    if not isinstance(batch, list) or len(batch) > 50:
        raise PeerError("invalid_batch")
    return batch


def sync(link: sqlite3.Row) -> None:
    card, island = link["card"], link["island"]
    with database() as db:
        db.execute("UPDATE links SET attempted=? WHERE id=?", (now(), link["id"]))
        receipts = [
            r[0] for r in db.execute("SELECT event FROM receipts WHERE link=? ORDER BY rowid LIMIT 50", (link["id"],))
        ]
    doc = islands.export_island(card)
    pending = islands.pending_footprints(card, island)
    activity = actions.pending(card,island)
    msg = {
        "actions": activity,
        "since": _known(card, island),
        "version": doc["version"],
        "events": pending,
        "ack": receipts,
        "snapshot": doc if link["sent"] != doc["version"] else None,
    }
    try:
        reply = send(link["address"], "sync", link["secret"], msg)
        if reply.get("need_snapshot"):
            msg["snapshot"] = doc
            reply = send(link["address"], "sync", link["secret"], msg)
    except PeerError:
        with database() as db:
            db.execute("INSERT OR IGNORE INTO offline VALUES(?)", (link["id"],))
        raise
    _import(card, island, reply.get("snapshot"))
    if "action_results" in reply:
        actions.settle(card,island,activity,reply["action_results"])
    else:
        actions.clear_capability(card,island)
    ids = _batch(reply, "ack")
    if any(i not in [event["event_id"] for event in pending] for i in ids):
        raise PeerError("invalid_receipt")
    islands.acknowledge_footprints(card, island, ids)
    delivered = islands.receive_footprints(card, island, _batch(reply, "events"))
    with database() as db:
        db.execute("DELETE FROM offline WHERE link=?", (link["id"],))
        db.executemany("DELETE FROM receipts WHERE link=? AND event=?", ((link["id"], event) for event in receipts))
        db.executemany("INSERT OR IGNORE INTO receipts VALUES(?,?)", ((link["id"], event) for event in delivered))
        db.execute("UPDATE links SET sent=max(sent,?),heard=? WHERE id=?", (doc["version"], now(), link["id"]))


def receive_sync(key_id: str, msg: dict) -> dict:
    with database() as db:
        link = db.execute("SELECT * FROM links WHERE id=?", (key_id,)).fetchone()
    if link is None:
        raise PeerError("not_paired")
    card, island = link["card"], link["island"]
    if any(type(msg.get(k)) is not int or msg[k] < 0 for k in ("version", "since")):
        raise PeerError("invalid_version")
    _import(card, island, msg.get("snapshot"))
    if _known(card, island) < msg["version"]:
        return {"need_snapshot": True}
    islands.acknowledge_footprints(card, island, _batch(msg, "ack"))
    ids = islands.receive_footprints(card, island, _batch(msg, "events"))
    extra = {"action_results": actions.receive(card,island,msg["actions"])} if "actions" in msg else {}
    doc = islands.export_island(card)
    return {
        **extra,
        "ack": ids,
        "events": islands.pending_footprints(card, island),
        "snapshot": doc if msg["since"] != doc["version"] else None,
    }


def dispatch(address: str, action: str, key_id: str, raw: bytes) -> bytes:
    source_address(address)
    if not SECRET.fullmatch(key_id) or action not in ("pair", "sync"):
        raise PeerError("unknown_peer")
    with database() as db:
        if action == "pair":
            row = db.execute("SELECT secret FROM invites WHERE id=? AND until>?", (key_id, now())).fetchone()
        else:
            row = db.execute("SELECT secret FROM links WHERE id=?", (key_id,)).fetchone()
    if not row:
        raise PeerError("unknown_peer")
    tag = b"island-v1/" + action.encode("ascii")
    msg = unseal(row[0], raw, tag)
    result = receive_pair(address, key_id, msg) if action == "pair" else receive_sync(key_id, msg)
    return seal(row[0], result, tag + b"/reply/" + raw[:12])
