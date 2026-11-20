"""Read verified Japanese tournament archives for the browser and the DS."""
import hashlib
import tempfile
from base64 import b64encode
from binascii import crc_hqx
from functools import cache
from pathlib import Path
from struct import pack
from urllib.parse import quote
from urllib.request import urlopen


from config import SAVE_DIR
from utils.data import load_json_data

ARCHIVE = (
    "https://raw.githubusercontent.com/projectpokemon/EventsGallery/"
    "f1f3095183ee54dca63216164adb1f278714ec55/Released/Gen%205/World%20Tournaments/JPN/"
)


@cache
def catalog() -> dict:
    return {row["sha"]: row for row in load_json_data("japanese_tournaments")}


def _valid(data, sha) -> bool:
    return len(data) == 4884 and hashlib.sha1(b"blob 4884\0" + data).hexdigest() == sha


def tournament_file(row) -> bytes:
    sha = row["sha"]
    path = SAVE_DIR / "tournament-cache" / (sha + ".pwt")
    if path.is_file():
        with path.open("rb") as source:
            data = source.read(4885)
        if _valid(data, sha):
            return data
    with urlopen(ARCHIVE + quote(row["file"]), timeout=8) as source:
        data = source.read(4885)
    if not _valid(data, sha):
        raise ValueError("Archive verification failed.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=path.parent) as folder:
        temporary = Path(folder) / path.name
        temporary.write_bytes(data)
        temporary.replace(path)
    return data


WBT_NAME = "PWT_J.bin"
RECORD_SIZE = 0x1214


def current_events():
    # The archive also holds the superseded Junior Division distribution.
    return [row for row in catalog().values() if "(Bug)" not in row["file"]]


def wireless_download(form):
    """Nintendo DLS WBT catalogue, including its UTF-16LE label and bundle CRC."""
    action = form.get("action")
    target = form.get("rhgamecd")
    allowed = target in (None, "", "IREJ", "IRDJ") and form.get("attr1", "") in ("", "WBT_J")
    if action == "count":
        return str(int(allowed)), 200
    if action == "list":
        if not allowed or form.get("offset", "0") not in ("0", "") or form.get("num") == "0":
            return "\r\n", 200
        title = b64encode("ダウンロードトーナメント".encode("utf-16le")).decode().translate(str.maketrans("=+/", "*.-"))
        size = RECORD_SIZE * len(current_events()) + 4
        return f"{WBT_NAME}\t{title}\tWBT_J\t\t\t{size}\r\n", 200
    if action != "contents":
        return b"", 400
    if not allowed or form.get("contents") != WBT_NAME:
        return b"", 404
    try:
        records = b"".join(tournament_file(row)[:RECORD_SIZE] for row in current_events())
    except (OSError, ValueError):
        return b"", 503
    return records + pack("<I", crc_hqx(records, 0xFFFF)), 200
