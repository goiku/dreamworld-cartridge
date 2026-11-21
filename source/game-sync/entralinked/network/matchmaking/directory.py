"""Short-lived records for Generation IV and V room discovery and NAT negotiation."""
import ast
import operator
import re
from dataclasses import dataclass, field
from threading import RLock
from time import monotonic

Endpoint = tuple[str, int]
GAME = "syachi2ds"
GAME_KEY = b"tXH2sN"
GAME_KEYS = {GAME: GAME_KEY, "pokemondpds": b"1vTlwb", "pokemonplatds": b"IIup73"}


@dataclass
class Room:
    address: Endpoint
    session: bytes
    challenge: bytes
    fields: dict[str, str]
    profile: int | None
    registered: bool = False
    touched: float = field(default_factory=monotonic)
    outstanding: dict[bytes, bytes] = field(default_factory=dict)


@dataclass
class Negotiator:
    profile: int
    game_port: Endpoint | None = None
    control_port: Endpoint | None = None
    acknowledged: bool = False


@dataclass
class Pairing:
    peers: dict[int, Negotiator] = field(default_factory=dict)
    touched: float = field(default_factory=monotonic)
    last_sent: float = 0.0
    version: int = 4
    game: str = GAME


class MatchDirectory:
    def __init__(self):
        self.lock = RLock()
        self.rooms: dict[Endpoint, Room] = {}
        self.pairings: dict[bytes, Pairing] = {}
        # A listener on the correct interface must issue each UDP reply.
        self.qr_sockets = {}
        self.nat_sockets = {}

    def expire(self):
        now = monotonic()
        for records, lifetime in ((self.rooms, 180), (self.pairings, 90)):
            for key in [key for key, record in records.items() if now - record.touched > lifetime]:
                del records[key]
        self.qr_sockets = {k: s for k, s in self.qr_sockets.items() if k in self.rooms}
        controls = {p.control_port for pair in self.pairings.values() for p in pair.peers.values()}
        self.nat_sockets = {k: s for k, s in self.nat_sockets.items() if k in controls}


_COMPARISON = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
               ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge}


def room_filter(source):
    """Parse GameSpy's room comparisons without executing the text as code."""
    if not source.strip():
        return lambda _: True
    if len(source) > 768:
        return lambda _: False
    source = re.sub(r"\b(and|or)\b", lambda m: m[0].lower(), source, flags=re.I)
    source = re.sub(r"(?<![!<>=])=(?!=)", "==", source).replace("<>", "!=")
    expr = ast.parse(source.strip(), mode="eval").body
    if sum(1 for _ in ast.walk(expr)) > 128:
        raise ValueError("Room search expression is too long")

    def evaluate(node, fields):
        if isinstance(node, ast.Constant) and type(node.value) in (int, str):
            return node.value
        if isinstance(node, ast.Name):
            value = fields.get(node.id, "")
            return int(value) if re.fullmatch(r"-?[0-9]{1,18}", value) else value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -int(evaluate(node.operand, fields))
        if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _COMPARISON:
            return _COMPARISON[type(node.ops[0])](evaluate(node.left, fields), evaluate(node.comparators[0], fields))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitAnd):
            return int(evaluate(node.left, fields)) & int(evaluate(node.right, fields))
        if isinstance(node, ast.BoolOp):
            values = (evaluate(item, fields) for item in node.values)
            return all(values) if isinstance(node.op, ast.And) else any(values)
        raise ValueError("Unsupported room search")

    def matches(fields):
        try:
            return bool(evaluate(expr, fields))
        except (ValueError, TypeError):
            return False
    return matches
