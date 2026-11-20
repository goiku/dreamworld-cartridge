"""Use a home Dream World account at a friend's Tailscale host and bring its changes home."""
import argparse
import getpass
import hashlib
import http.client
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import sys
import time
import webbrowser
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from werkzeug.security import check_password_hash

from config import SAVE_DIR, WEB_PORTS
from utils import visit_storage as storage
from utils.account_manager import accounts


class VisitProblem(Exception):
    """An error the player can act on."""


class Offline(VisitProblem):
    """The same request can be retried after the network recovers."""


class Conflict(VisitProblem):
    """Both copies were changed since the last successful synchronization."""


class Peer:
    """Connect directly to the approved numeric Tailscale address, with no redirects or proxy."""

    def __init__(self, address: str, port: int = 8088) -> None:
        self.address, self.port = address, port

    def request(self, action: str, token: str, data: dict | None = None, *, revision: str | None = None,
                method: str | None = None) -> dict | None:
        conn = http.client.HTTPConnection(self.address, self.port, timeout=12)
        headers = {"Host": f"127.0.0.1:{self.port}", "Authorization": f"Bearer {token}"}
        body = None
        if data is not None:
            body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if revision:
            headers["If-None-Match"] = f'"{revision}"'
        try:
            conn.request(method or ("GET" if body is None else "POST"), "/visit-sync/api/" + action,
                         body=body, headers=headers)
            resp = conn.getresponse()
            if resp.status == 304 and action == "snapshot" and revision:
                return None
            if resp.status == 401:
                raise PermissionError("Pairing or invitation not accepted / 配对或邀请码无效")
            if resp.status == 409:
                raise Conflict("Record changed or cannot be imported safely / 记录已改变或暂不能安全导入")
            if resp.status >= 500:
                raise Offline(f"Host temporarily unavailable (HTTP {resp.status})")
            if resp.status != 200 and resp.status != 201:
                raise VisitProblem(f"Host returned HTTP {resp.status}. Check both installations are updated.")
            limit = 2 * 1024 * 1024 + 8192
            payload = resp.read(limit + 1)
            if len(payload) > limit:
                raise VisitProblem("Snapshot exceeds the supported size.")
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise VisitProblem("Invalid response from host.")
            return result
        except (OSError, http.client.HTTPException) as exc:
            if isinstance(exc, PermissionError):
                raise
            raise Offline("Host unreachable / 暂时联系不上房主，等待重连") from exc
        finally:
            conn.close()


class LinkStore:
    """Private, per-home metadata. Bind each secret to a host, home account and cartridge."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "visit-links.sqlite3", timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS links (
            host TEXT, username TEXT, card TEXT, token TEXT NOT NULL, base TEXT NOT NULL,
            paired INTEGER NOT NULL, PRIMARY KEY(host,username,card))""")

    def lookup(self, key: tuple[str, str, str]) -> sqlite3.Row:
        row = self.db.execute("SELECT * FROM links WHERE host=? AND username=? AND card=?", key).fetchone()
        if row is None:
            raise VisitProblem("No saved pairing for this host and cartridge.")
        return row

    def prepare(self, key: tuple[str, str, str], base: str) -> sqlite3.Row:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO links VALUES (?,?,?,?,?,0)",
                            (*key, secrets.token_urlsafe(32), base))
        return self.lookup(key)

    def mark(self, key: tuple[str, str, str], revision: str) -> None:
        with self.db:
            self.db.execute("UPDATE links SET base=?,paired=1 WHERE host=? AND username=? AND card=?",
                            (revision, *key))

    def preserve(self, key: tuple[str, str, str], home: dict, host: dict) -> Path:
        # Conflict resolution is explicit; retain both complete player snapshots locally before either write.
        path = self.directory / ("visit-conflict-" + secrets.token_hex(8) + ".json")
        with path.open("x", encoding="utf-8") as f:
            json.dump({"host_address": key[0], "home": home, "host": host}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        return path


@contextmanager
def card_lock(directory: Path, username: str, card: str) -> Iterator[None]:
    name = hashlib.sha256((username + "\0" + card).encode()).hexdigest()
    with (Path(directory) / ("visit-" + name + ".lock")).open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise VisitProblem("This cartridge already has a sync window open / 这张卡已有同步窗口") from exc
        yield


def checked_snapshot(result: dict | None) -> dict:
    if (not isinstance(result, dict) or not isinstance(result.get("snapshot"), dict)
            or storage.snapshot_revision(result["snapshot"]) != result.get("revision")):
        raise VisitProblem("Host returned an invalid player record.")
    return result


def sync_once(peer: Peer, links: LinkStore, key: tuple[str, str, str], *, resolve: str | None = None) -> str:
    _, username, card = key
    link = links.lookup(key)
    token, base = link["token"], link["base"]
    home = storage.export_local(username, card)
    fetched = peer.request("snapshot", token, revision=base)
    remote = checked_snapshot(fetched) if fetched is not None else None
    remote_rev = remote["revision"] if remote is not None else base
    local_rev = home["revision"]
    if local_rev == remote_rev:
        if base != local_rev or not link["paired"]:
            links.mark(key, local_rev)
        return "current"
    if remote_rev != base and local_rev != base:
        if resolve is None:
            raise Conflict("Both copies changed / 两边都有新进度，本次同步已暂停")
        assert remote is not None
        path = links.preserve(key, home, remote)
        print(f"Both snapshots saved / 两份记录已备份：{path}", flush=True)
    if local_rev == base or (remote_rev != base and resolve == "host"):
        assert remote is not None
        updated = storage.apply_local(username, card, local_rev, remote["snapshot"])
        if updated["revision"] != remote_rev:
            raise VisitProblem("Home did not confirm the expected revision.")
        direction = "home"
    else:
        updated = checked_snapshot(peer.request("snapshot", token, {"revision": remote_rev, "snapshot": home["snapshot"]},
                                                method="PUT"))
        if updated["revision"] != local_rev:
            raise VisitProblem("Host did not confirm the expected revision.")
        direction = "host"
    links.mark(key, updated["revision"])
    return direction


def pair(peer: Peer, links: LinkStore, key: tuple[str, str, str], get_invite: Callable[[], str]) -> None:
    local = storage.export_local(key[1], key[2])
    link = links.prepare(key, local["revision"])
    if link["paired"]:
        return
    try:
        # Recover a completed redemption even when the network lost its reply.
        checked_snapshot(peer.request("snapshot", link["token"]))
    except PermissionError:
        invite = get_invite().strip()
        if not invite:
            raise VisitProblem("An invitation from the current host is required.") from None
        # If the home save changed after an earlier failed attempt, checkpoint the revision
        # actually offered. A committed redemption was already discovered by the GET above.
        with links.db:
            links.db.execute("UPDATE links SET base=? WHERE host=? AND username=? AND card=? AND paired=0",
                             (local["revision"], *key))
        checked_snapshot(peer.request("redeem", invite, {"token": link["token"], "snapshot": local["snapshot"]}))


def run(args: argparse.Namespace) -> None:
    address = ipaddress.IPv4Address(args.host or input("Host Tailscale IP / 房主的 Tailscale 地址：").strip())
    if address not in ipaddress.IPv4Network("100.64.0.0/10"):
        raise VisitProblem("Enter the host PC's Tailscale IPv4 address (100.64–100.127).")
    name = args.user or input("Home username / 自己本地的账号：").strip()
    account = accounts.get_account_by_username(name)
    password = getpass.getpass("Home password (local check only) / 本地账号密码：")
    if (not account or not account["activated"] or account["username"].startswith(storage.GUEST_PREFIX)
            or not check_password_hash(account["password_hash"], password)):
        raise VisitProblem("Home account or password not accepted / 本地账号或密码有误，或账号尚未激活")
    username = account["username"]
    card = args.card or account["active_gscd"]
    if not card or accounts.get_gscd_owner(card) != username:
        raise VisitProblem("Link your own cartridge on your home server first / 请先在自己服绑定卡带")
    key = (str(address), username, card)
    peer = Peer(str(address), WEB_PORTS[args.lang])
    links = LinkStore(SAVE_DIR)
    try:
        with card_lock(SAVE_DIR, username, card):
            pair(peer, links, key, lambda: getpass.getpass("Host invite / 房主给的一次性邀请码："))
            result = sync_once(peer, links, key, resolve=args.resolve)
            print(f"Synced / 已同步 ({result})", flush=True)
            if args.once:
                return
            ticket = peer.request("ticket", links.lookup(key)["token"], {})
            code = ticket.get("ticket", "") if ticket else ""
            if not isinstance(code, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{22,128}", code):
                raise VisitProblem("Invalid sign-in ticket.")
            url = f"http://127.0.0.1:{WEB_PORTS[args.lang]}/visit-sync/login#{code}"
            if not webbrowser.open(url):
                print(f"Open privately on this PC / 请在本机浏览器打开：{url}")
            print("Keep this window open. Finish the Dream World visit and close the game tab before Ctrl+C.\n"
                  "游玩时保持窗口打开；在网页结束梦世界并关闭游戏标签页，再按 Ctrl+C 完成最后一次同步。", flush=True)
            try:
                disconnected = False
                while True:
                    time.sleep(12)
                    try:
                        direction = sync_once(peer, links, key)
                        if disconnected or direction != "current":
                            print(f"Synced / 已同步 ({direction})", flush=True)
                        disconnected = False
                    except Offline as exc:
                        if not disconnected:
                            print(exc, flush=True)
                        disconnected = True
            except KeyboardInterrupt:
                sync_once(peer, links, key)
                print("Final sync complete / 最终同步已完成。", flush=True)
    finally:
        links.db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", help="Tailscale IPv4 of the friend hosting this visit")
    parser.add_argument("--user", help="Your own home account")
    parser.add_argument("--card", help="One of your linked Game Sync IDs (default: active cartridge)")
    parser.add_argument("--lang", choices=WEB_PORTS, default="zh", help="Language of the visiting browser")
    parser.add_argument("--once", action="store_true", help="Synchronize once without opening the browser")
    parser.add_argument("--resolve", choices=("home", "host"),
                        help="If both changed, back up both and keep the chosen copy (with --once only)")
    args = parser.parse_args()
    if args.resolve and not args.once:
        parser.error("--resolve requires --once")
    try:
        run(args)
    except (VisitProblem, storage.VisitError, PermissionError, ValueError, sqlite3.Error, OSError,
            KeyboardInterrupt, EOFError) as exc:
        parser.exit(1, f"Sync stopped / 同步已停止。{exc}\nReconnect and run again before playing locally.\n")


if __name__ == "__main__":
    main()
