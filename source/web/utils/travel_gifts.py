"""Portable promotion orders. Only the cartridge's home database holds its WFC identity."""

import base64
import binascii
import hashlib
import json

from utils import distributions as gifts


def export(conn, card) -> dict | None:
    ident, _, album = gifts.state(conn, card)
    orders = []
    for key, phase, payload, gender in conn.execute(
        """
        SELECT o.gift,o.status,o.payload,d.gender FROM distribution_orders o
        LEFT JOIN distribution_dream_options d USING(card,gift) WHERE o.card=? ORDER BY o.rowid""",
        (card,),
    ):
        orders.append([key, phase, base64.b64encode(payload).decode() if payload else None, gender])
    priority = conn.execute("SELECT gift FROM distribution_next WHERE card=?", (card,)).fetchone()
    if not ident and not orders:
        return None
    return {"identified": bool(ident), "album": album, "orders": orders, "next": priority[0] if priority else None}


def _validated(data, rom, lang) -> tuple[dict, dict, dict]:
    if (
        not isinstance(data, dict)
        or set(data) != {"identified", "album", "orders", "next"}
        or type(data["identified"]) is not bool
        or not isinstance(data["orders"], list)
        or len(data["orders"]) > len(gifts.catalog())
    ):
        raise ValueError("Invalid distribution history.")
    album = data["album"]
    copies = {}
    variants = {}
    if album is not None:
        if not data["identified"] or not isinstance(album, dict) or len(album) > 2048 + len(gifts.catalog()):
            raise ValueError("Invalid card album.")
        for key, phase in album.items():
            if phase not in ("received", "collected", "at_center"):
                raise ValueError("Invalid card receipt.")
            if (
                isinstance(key, str)
                and key.isascii()
                and key.isdigit()
                and len(key) <= 4
                and str(int(key)) == key
                and int(key) < 2048
            ):
                copies[key] = phase
            elif (gift := gifts.catalog().get(key)) and gift.number and gifts.compatible(gift, rom, lang):
                variants[key] = phase
            else:
                raise ValueError("Unknown receipt.")
    orders = {}
    for row in data["orders"]:
        if not isinstance(row, list) or len(row) != 4 or not isinstance(row[0], str):
            raise ValueError("Invalid gift order.")
        key, phase, encoded, gender = row
        gift = gifts.catalog().get(key)
        if not gift or not gifts.compatible(gift, rom, lang) or gift.group in orders:
            raise ValueError("Incompatible gift order.")
        if (
            phase not in ("queued", "sent", "delivered", "in_chest")
            or (phase == "sent" and not gift.number)
            or (phase == "in_chest" and gift.event != "berries")
        ):
            raise ValueError("Invalid gift status.")
        if gender is not None and (gift.event != "cafe" or type(gender) is not int or gender not in (0, 1)):
            raise ValueError("Invalid gift choice.")
        payload = None
        if gift.number and phase in ("queued", "sent"):
            if not data["identified"] or not isinstance(encoded, str) or len(encoded) != 960:
                raise ValueError("Missing Wonder Card.")
            payload = base64.b64decode(encoded, validate=True)
            exact = hashlib.sha1(b"blob 720\0" + payload).hexdigest() == gift.full_digest
            if (
                len(payload) != 720
                or payload[0xCE] != gift.mask
                or payload[-5] != lang
                or int.from_bytes(payload[0xB0:0xB2], "little") != gift.number
                or payload[0xB4] & 2
                or binascii.crc_hqx(payload[:-2], 0xFFFF) != int.from_bytes(payload[-2:], "little")
                or gifts._card_signature(payload[:204]) != gift.signature
                or (not exact and gifts.pack_card(payload[:204], gift, lang) != payload)
            ):
                raise ValueError("Wonder Card does not match the archive.")
        elif encoded is not None:
            raise ValueError("Unexpected Wonder Card.")
        orders[gift.group] = (key, phase, payload, gender)
    priority = data["next"]
    # The native delivery table may still point to a completed order.
    if priority is not None and (
        not isinstance(priority, str)
        or not any(o[0] == priority and gifts.catalog()[priority].number for o in orders.values())
    ):
        raise ValueError("Invalid next Wonder Card.")
    return copies, variants, orders


def restore(conn, card, data, rom, lang) -> None:
    copies, variants, orders = _validated(data, rom, lang)
    gifts.schema(conn)
    local = conn.execute("SELECT rom,lang,album FROM distribution_cartridges WHERE card=?", (card,)).fetchone()
    if local and (local["rom"], local["lang"]) != (rom, lang):
        raise ValueError("Cartridge edition changed.")
    if local:
        # A visiting web server cannot certify the physical album or rewind a delivery.
        _, old_orders, old_album = gifts.state(conn, card)
        if data["album"] != old_album or not data["identified"]:
            raise ValueError("Cartridge receipts changed at home.")
        for family, old in old_orders.items():
            if family not in orders or orders[family][0] != old["gift"]:
                raise ValueError("A recorded claim would disappear.")
            if old["status"] in ("in_chest", "delivered") and orders[family][1] != old["status"]:
                raise ValueError("A completed claim would change.")
        for family, (_, phase, _, _) in orders.items():
            old = old_orders.get(family)
            if phase in ("sent", "delivered") and (not old or old["status"] != phase):
                raise ValueError("Only the cartridge can acknowledge delivery.")
    else:
        conn.execute("DELETE FROM distribution_visit_album WHERE card=?", (card,))
        if data["identified"]:
            conn.execute(
                "INSERT INTO distribution_visit_album VALUES(?,?,?,?)",
                (card, rom, lang, json.dumps(copies) if data["album"] is not None else None),
            )
        conn.execute("DELETE FROM distribution_variants WHERE card=?", (card,))
        conn.executemany("INSERT INTO distribution_variants VALUES(?,?,?)", ((card, k, v) for k, v in variants.items()))
    for table in ("distribution_orders", "distribution_dream_options", "distribution_next"):
        conn.execute(f"DELETE FROM {table} WHERE card=?", (card,))
    for family, (key, phase, payload, gender) in orders.items():
        conn.execute("INSERT INTO distribution_orders VALUES(?,?,?,?,?)", (card, family, key, phase, payload))
        if gender is not None:
            conn.execute("INSERT INTO distribution_dream_options VALUES(?,?,?)", (card, key, gender))
    if data["next"] is not None:
        conn.execute("INSERT INTO distribution_next VALUES(?,?)", (card, data["next"]))
