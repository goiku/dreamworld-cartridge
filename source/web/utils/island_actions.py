"""Two paired islands exchange requests over their existing authenticated link.

The visitor reserves payment when submitting. Only an owner acknowledgement credits
the replacement or refunds the reservation. Lost replies can be requested again.
"""

import hashlib
import json

from game_sync_server.entralinked.utility.db_manager import db
from utils import managers, save_data, visits
from utils import offline_islands as islands


def schema(conn) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS island_reserved_water (
        card TEXT, island TEXT, id TEXT, day TEXT NOT NULL, PRIMARY KEY(card,island,id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS island_action_peers (
        card TEXT, island TEXT, PRIMARY KEY(card,island))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS island_actions (
        card TEXT, island TEXT, id TEXT, request TEXT NOT NULL, status TEXT NOT NULL,
        PRIMARY KEY(card,island,id))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS island_action_results (
        card TEXT, island TEXT, id TEXT, request TEXT NOT NULL, accepted INTEGER NOT NULL,
        PRIMARY KEY(card,island,id))""")


def compatible(card, island) -> bool:
    with db.transaction() as conn:
        schema(conn)
        return bool(
            conn.execute("SELECT 1 FROM island_action_peers WHERE card=? AND island=?", (card, island)).fetchone()
        )


def clear_capability(card, island) -> None:
    with db.transaction() as conn:
        schema(conn)
        conn.execute("DELETE FROM island_action_peers WHERE card=? AND island=?", (card, island))


def pending(card, island) -> list[dict]:
    with db.transaction() as conn:
        schema(conn)
        return [
            json.loads(row[0])
            for row in conn.execute(
                "SELECT request FROM island_actions WHERE card=? AND island=? AND status='pending' ORDER BY rowid LIMIT 30",
                (card, island),
            )
        ]


def history(card, island) -> list[dict]:
    with db.transaction() as conn:
        schema(conn)
        return [
            dict(json.loads(req), status=status)
            for req, status in conn.execute(
                "SELECT request,status FROM island_actions WHERE card=? AND island=? ORDER BY rowid DESC LIMIT 12",
                (card, island),
            )
        ]


def pending_action_counts(card: str) -> dict[str, dict[str, int]]:
    with db.transaction() as conn:
        schema(conn)
        counts = {}
        for island, kind, count in conn.execute(
            """SELECT island,json_extract(request,'$.kind'),COUNT(*) FROM island_actions
               WHERE card=? AND status='pending' GROUP BY island,json_extract(request,'$.kind')""", (card,)
        ):
            counts.setdefault(island, {})[kind] = count
        return counts


def _identity(island, version, kind, slot) -> str:
    raw = f"{island}/{version}/{kind}/{slot}".encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def request_action(card, island, version, kind, slot, payment=None) -> None:
    if kind not in ("water", "trade") or type(slot) is not int or slot < 0:
        raise ValueError("Invalid action.")
    with db.transaction() as conn:
        if not compatible(card, island):
            raise ValueError("Pairing required.")
        doc = islands.get_friend(card, island)
        if doc["version"] != version:
            raise ValueError("The island changed.")
        items = doc["content"]["garden" if kind == "water" else "shelf"]
        if slot >= len(items):
            raise ValueError("Slot changed.")
        ident = _identity(island, version, kind, slot)
        if conn.execute(
            "SELECT 1 FROM island_actions WHERE card=? AND island=? AND id=?", (card, island, ident)
        ).fetchone():
            return
        target = items[slot]
        if kind == "trade":
            if (
                type(payment) is not int
                or str(payment) not in managers.ITEM_INFO
                or str(target["item_id"]) not in managers.ITEM_INFO
                or payment == target["item_id"]
            ):
                raise ValueError("Choose a different item.")
            managers.get_chest(card).remove_item(payment, 1)
        else:
            if (
                not target.get("planted_at")
                or target.get("dirt_hp", 0) >= managers.CropManager.FULL_DIRT_HP
                or target.get("kinomi_state", 0) >= managers.CropManager.GROWTH_STAGES
            ):
                raise ValueError("This plant does not need water.")
            visits.use_friend_watering(card)
            conn.execute(
                "INSERT INTO island_reserved_water VALUES(?,?,?,?)", (card, island, ident, save_data.today_jst_str())
            )
        request = {
            "id": ident,
            "version": version,
            "kind": kind,
            "slot": slot,
            "payment": payment,
            "expected": target.get("item_id") if kind == "trade" else target["planted_at"],
        }
        conn.execute(
            "INSERT INTO island_actions VALUES(?,?,?,?,'pending')",
            (card, island, ident, json.dumps(request, sort_keys=True)),
        )


def _apply(conn, card, source, req) -> bool:
    doc = islands.export_island(card)
    kind, slot = req["kind"], req["slot"]
    if req["id"] != _identity(doc["island_id"], req["version"], kind, slot):
        return False

    def targets(version) -> list:
        row = conn.execute(
            "SELECT targets FROM offline_island_targets WHERE card=? AND version=?", (card, version)
        ).fetchone()
        return json.loads(row[0])[kind] if row else []

    old, current = targets(req["version"]), targets(doc["version"])
    if slot >= len(old) or old[slot] not in current:
        return False
    slot = current.index(old[slot])
    if kind == "water":
        plot_list = doc["content"]["garden"]
        if slot >= len(plot_list) or plot_list[slot].get("planted_at") != req["expected"]:
            return False
        record = plot_list[slot]
        for plot in managers.get_crops(card).data["croft_list"]:
            if (plot["x"], plot["y"]) == (record["x"], record["y"]) and plot.get("server", {}).get("planted_at") == req[
                "expected"
            ]:
                return managers.get_crops(card).water_plot(plot["my_croft_id"])
        return False
    shelf = managers.get_shelf(card)
    slots = shelf.data["share_list"]
    if (
        slot >= len(slots)
        or str(req["expected"]) not in managers.ITEM_INFO
        or slots[slot]["item_id"] != req["expected"]
        or req["payment"] == req["expected"]
    ):
        return False
    profile = islands.get_friend(card, source)["content"]["profile"]
    shelf.swap_from_island(slots[slot]["material_id"], req["payment"], profile["pgl_name"])
    return True


def receive(card, island, batch) -> dict[str, bool]:
    if not isinstance(batch, list) or len(batch) > 30:
        raise ValueError("Invalid interaction batch.")
    with db.transaction() as conn:
        schema(conn)
        conn.execute("INSERT OR IGNORE INTO island_action_peers VALUES(?,?)", (card, island))
        results = {}
        for req in batch:
            if (
                not isinstance(req, dict)
                or set(req) != {"kind", "id", "version", "slot", "payment", "expected"}
                or req["kind"] not in ("water", "trade")
                or not isinstance(req["id"], str)
                or not islands._HEX64.fullmatch(req["id"])
                or not islands._integer(req["slot"], 0, 127)
                or not islands._integer(req["version"], 1)
                or not islands._integer(req["expected"])
                or (
                    req["kind"] == "trade"
                    and (type(req["payment"]) is not int or str(req["payment"]) not in managers.ITEM_INFO)
                )
                or (req["kind"] == "water" and req["payment"] is not None)
            ):
                raise ValueError("Invalid interaction.")
            ident = req["id"]
            saved = conn.execute(
                "SELECT request,accepted FROM island_action_results WHERE card=? AND island=? AND id=?",
                (card, island, ident),
            ).fetchone()
            encoded = json.dumps(req, sort_keys=True)
            if saved:
                if saved[0] != encoded:
                    raise ValueError("Conflicting repeat.")
                results[ident] = bool(saved[1])
            else:
                accepted = _apply(conn, card, island, req)
                conn.execute(
                    "INSERT INTO island_action_results VALUES(?,?,?,?,?)", (card, island, ident, encoded, int(accepted))
                )
                results[ident] = accepted
        return results


def settle(card, island, batch, results) -> None:
    if (
        not isinstance(results, dict)
        or set(results) != {req["id"] for req in batch}
        or any(type(v) is not bool for v in results.values())
    ):
        raise ValueError("Invalid interaction acknowledgement.")
    with db.transaction() as conn:
        schema(conn)
        conn.execute("INSERT OR IGNORE INTO island_action_peers VALUES(?,?)", (card, island))
        for ident, accepted in results.items():
            row = conn.execute(
                "SELECT request FROM island_actions WHERE card=? AND island=? AND id=? AND status='pending'",
                (card, island, ident),
            ).fetchone()
            if not row:
                continue
            req = json.loads(row[0])
            if req["kind"] == "trade":
                managers.get_chest(card).add_item(req["expected"] if accepted else req["payment"], 1)
            elif accepted:
                save_data.award_points(10, card)
            if req["kind"] == "water":
                held = conn.execute(
                    "SELECT day FROM island_reserved_water WHERE card=? AND island=? AND id=?", (card, island, ident)
                ).fetchone()
                if not accepted and held and held[0] == save_data.today_jst_str():

                    def refund(member, day=held[0]) -> None:
                        if member.get("friend_waterings_date") == day:
                            member["friend_waterings_left"] = min(
                                visits.FRIEND_WATERINGS_PER_DAY, member["friend_waterings_left"] + 1
                            )

                    save_data.change_member(refund, card)
                conn.execute(
                    "DELETE FROM island_reserved_water WHERE card=? AND island=? AND id=?", (card, island, ident)
                )
            conn.execute(
                "UPDATE island_actions SET status=? WHERE card=? AND island=? AND id=?",
                ("accepted" if accepted else "declined", card, island, ident),
            )
