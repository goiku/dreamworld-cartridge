"""Locally cached, hash-verified Gen V Wonder Cards for Japanese cartridges."""
import hashlib
import os
import tempfile
from functools import lru_cache
from urllib.request import urlopen

from config import SAVE_DIR
from utils.data import load_json_data

PACK_URL = ("https://raw.githubusercontent.com/kwsch/PKHeX/6c9583883c7551ac74a4b74180cead249d4277b8/"
            "PKHeX.Core/Resources/legality/mgdb/pgf.pkl")
PACK_SHA256 = "c22fee868cf6a39dacb3aeec8cd8b8d906f3370f34f9d1a8071d8372fae14e9b"
PACK_SIZE = 145345
CACHE = SAVE_DIR / "distribution-cache" / (PACK_SHA256 + ".bin")


def verify(data):
    if len(data) != PACK_SIZE or hashlib.sha256(data).hexdigest() != PACK_SHA256:
        raise ValueError("The supplied archive does not match the pinned release.")
    expected = {row[2]: row for row in load_json_data("gift_cards") if row[0] == "JPN"}
    cards = {}
    count = len(data) // 205
    for i, restriction in enumerate(data[count * 204:]):
        if restriction >> 4 != 1:
            continue
        raw = data[i*204:(i+1)*204]
        digest = hashlib.sha1(b"blob 204\0" + raw).hexdigest()
        row = expected.get(digest)
        if not row or (restriction & 15) << 4 != row[3] or int.from_bytes(raw[176:178], "little") != row[6]:
            raise ValueError("A Japanese card does not match the original-card index.")
        subject = int.from_bytes(raw[26:28] if raw[179] == 1 else raw[:2], "little")
        signature = hashlib.sha256(raw[:172] + raw[176:180] + bytes([raw[180] & ~2]) + raw[181:]).hexdigest()
        title = raw[96:168].decode("utf-16-le").split("\uffff")[0].split("\0")[0]
        if row[5] != signature or row[7:] != [subject, raw[179], raw[180] & 1, title]:
            raise ValueError("Card metadata differs from the archived card.")
        cards[digest] = raw
    if len(cards) != 472 or cards.keys() != expected.keys():
        raise ValueError("The Japanese catalogue is incomplete.")
    return cards


def install(data):
    count = len(verify(data))
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=CACHE.parent, delete=False) as output:
        tmp = output.name
    try:
        with open(tmp, "wb") as output:
            output.write(data)
        os.replace(tmp, CACHE)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return count


@lru_cache(maxsize=1)
def _read(path, modified):
    with path.open("rb") as archive:
        return verify(archive.read(PACK_SIZE + 1))


def lookup(digest):
    try:
        return _read(CACHE, CACHE.stat().st_mtime_ns).get(digest)
    except FileNotFoundError:
        return None


def ensure_installed():
    """For a bulk claim, obtain the small verified pack once on a fresh server."""
    try:
        _read(CACHE, CACHE.stat().st_mtime_ns)
    except (FileNotFoundError, ValueError):
        with urlopen(PACK_URL, timeout=8) as source:
            install(source.read(PACK_SIZE + 1))

