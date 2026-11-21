"""Retail Generation V GTS transport, backed by this private server's WFC identities."""
import base64
from dataclasses import dataclass
import hashlib
import secrets
import string
import struct
import threading
import time

from flask import Blueprint, Response, abort, request

from ...context import Context
from ...model.gen4_gts import Gen4TradeStation
from ...model.gts import GlobalTradeStation, pokemon_core
from ...paths import SAVE_DIR
from ...utility.db_manager import DBManager, db

GAME_ID = b"HZEdGCzcGGLvguqUEKQN"
GEN4_GAME_ID = b"sAdeqWo3voLeC5r16DYv"
WORLD_ACTIONS = frozenset({
    "info", "result", "get", "delete", "return", "post", "post_finish",
    "search", "exchange", "exchange_finish",
})


@dataclass
class Challenge:
    deadline: float
    pid: int
    path: str
    peer: str
    request_digest: bytes | None = None
    reply: bytes | None = None


def _binary(data: bytes) -> Response:
    return Response(data, content_type="application/octet-stream", headers={"Cache-Control": "no-store"})


def _request_body(raw: bytes, pid: int, fourth: bool) -> bytes:
    if len(raw) < (8 if fourth else 12):
        raise ValueError("Incomplete GTS request")
    check, = struct.unpack_from(">I", raw)
    if fourth:
        total = check ^ 0x4a3b2c1d
        state = ((total & 0xffff) << 16) | (total & 0xffff)
        decoded = bytearray(raw[4:])
        for i in range(len(decoded)):
            state = (state * 0x45 + 0x1111) & 0x7fffffff
            decoded[i] ^= (state >> 16) & 255
        if total != sum(decoded) or int.from_bytes(decoded[:4], "little") != pid:
            raise ValueError("Invalid Generation IV envelope")
        return bytes(decoded[4:])
    encoded_pid, length = struct.unpack_from("<II", raw, 4)
    if check != (sum(raw[4:]) ^ 0x2db842b2) or pid != encoded_pid or length != len(raw) - 12:
        raise ValueError("Invalid Generation V envelope")
    return raw[12:]


class GtsHandler:
    def __init__(self, context: Context) -> None:
        self.users = context.user_manager
        self.station = GlobalTradeStation(db)
        self.gen4 = Gen4TradeStation(DBManager(SAVE_DIR / "gen4-gts.sqlite3"))
        self.challenges: dict[str, Challenge] = {}
        self.lock = threading.Lock()

    def blueprint(self) -> Blueprint:
        api = Blueprint("gts", __name__)
        api.add_url_rule("/syachi2ds/web/worldexchange/<action>.asp", view_func=self.gamestats, methods=["GET", "POST"])
        api.add_url_rule("/syachi2ds/web/common/setProfile.asp", view_func=self.gamestats,
                         defaults={"action": "setProfile"}, methods=["GET", "POST"])
        api.add_url_rule("/pokemon/validate", view_func=self.validate, methods=["POST"])
        api.add_url_rule("/pokemondpds/worldexchange/<action>.asp", view_func=self.gamestats,
                         defaults={"fourth": True}, methods=["GET", "POST"])
        api.add_url_rule("/pokemondpds/common/setProfile.asp", view_func=self.gamestats,
                         defaults={"action": "setProfile", "fourth": True}, methods=["GET", "POST"])
        return api

    def validate(self) -> Response:
        """Issue an opaque receipt valid only for this console and this Pokémon on our GTS."""
        pid = self.users.gts_peer_profile(request.remote_addr)
        if pid is None:
            abort(403)
        raw = request.get_data()
        token, separator, body = raw.partition(b"\0")
        if not separator or len(token) > 256 or len(body) != 222 or body[:2] != b"\0\1":
            abort(400)
        try:
            ticket = token.decode("ascii")
        except UnicodeDecodeError:
            abort(400)
        session = self.users.get_service_session(ticket, "gamespy") or self.users.get_service_session(ticket, "external")
        if session is None or not any(profile.id == pid for profile in session.user.profiles.values()):
            abort(403)
        try:
            core, _ = pokemon_core(body[2:], allow_plain=True)
        except ValueError:
            return _binary(b"\1\0\0\0\x3c" + bytes(128))
        return _binary(bytes(5) + self.station.validation_ticket(pid, core))

    def gamestats(self, action: str, fourth: bool = False) -> Response:
        if action != "setProfile" and action not in WORLD_ACTIONS:
            abort(404)
        form = request.form if request.method == "POST" else request.args
        pid = form.get("pid", type=int)
        peer = request.remote_addr
        if pid is None or not 0 <= pid < 2**31:
            abort(400)
        if peer is None or self.users.gts_peer_profile(peer) != pid:
            abort(403)
        key, encoded = form.get("hash"), form.get("data")
        game_id = GEN4_GAME_ID if fourth else GAME_ID
        station = self.gen4 if fourth else self.station
        with self.lock:
            now = time.monotonic()
            if key is None and encoded is None:
                self.challenges = {k: value for k, value in self.challenges.items() if value.deadline > now}
                token = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32)).encode("ascii")
                self.challenges[hashlib.sha1(game_id + token).hexdigest()] = Challenge(now + 600, pid, request.path, peer)
                return _binary(token)
            challenge = self.challenges.get(key or "")
            if (not challenge or challenge.pid != pid or challenge.path != request.path
                    or challenge.peer != peer or challenge.deadline <= now or not encoded or len(encoded) > 65536):
                abort(400)
            try:
                raw = base64.b64decode(encoded, altchars=b"-_", validate=True)
                payload = _request_body(raw, pid, fourth)
                digest = hashlib.sha256(raw).digest()
                if challenge.reply is not None:
                    if challenge.request_digest != digest:
                        abort(400)
                    return _binary(challenge.reply)
                if action == "setProfile":
                    if len(payload) != 100:
                        abort(400)
                    if not fourth:
                        self.station.remember_profile(pid, payload)
                    body = bytes(8)
                else:
                    body = station.dispatch(action, pid, payload)
            except ValueError:
                abort(400)
            checksum = b"" if fourth else hashlib.sha1(GAME_ID + base64.urlsafe_b64encode(body) + GAME_ID).hexdigest().encode("ascii")
            challenge.request_digest = digest
            challenge.reply = body + checksum
            return _binary(challenge.reply)
