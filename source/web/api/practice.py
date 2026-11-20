"""Public arcade. Only local movie and translation files are accessed by these routes."""

import base64
import hashlib
import re
import struct
import zlib
from functools import cache

from flask import Blueprint, Response, abort, render_template, request, send_file

from config import ASSET_LANG, LANG, ROOT_DIR
from utils.assets import SHARED_DIR
from utils.data import load_json_data
from utils.text import lookup_str

practice = Blueprint(
    "practice", __name__, template_folder="../templates", static_folder="../static", static_url_path="/practice/assets"
)
GAME_COUNT = 12


@cache
def labels() -> dict:
    return load_json_data("practice")[LANG]


@practice.get("/practice/")
@practice.get("/practice/<int:number>/")
def arcade(number=None) -> str:
    if number is not None and not 1 <= number <= GAME_COUNT:
        abort(404)
    return render_template(
        "practice.html",
        t=labels(),
        number=number,
        lang=LANG,
        movie_lang=ASSET_LANG,
        buddy=lookup_str("pokemon", 494) if number == 6 else labels()["buddy"],
    )


def _tag(code, data) -> bytes:
    size = len(data)
    header = struct.pack("<H", (code << 6) | min(63, size))
    return header + (struct.pack("<I", size) if size >= 63 else b"") + data


@cache
def _practice_movie() -> bytes:
    # Keep the original game classes and library symbols, including Pokémon Seek's
    # nine courses. Replace only the root timeline with the practice controller.
    source = (SHARED_DIR / "src/swf/pdw/assets/pdw_island.swf").read_bytes()
    raw = zlib.decompress(source[8:]) if source[:3] == b"CWS" else source[8:]
    start = (5 + 4 * (raw[0] >> 3) + 7) // 8 + 4
    out = bytearray(raw[: start - 2] + b"\x01\x00")
    offset = start
    while offset < len(raw):
        (word,) = struct.unpack_from("<H", raw, offset)
        offset += 2
        kind, size = divmod(word, 64)
        if size == 63:
            (size,) = struct.unpack_from("<I", raw, offset)
            offset += 4
        body = raw[offset : offset + size]
        offset += size
        if kind == 76:
            (count,) = struct.unpack_from("<H", body)
            entries = []
            pos = 2
            for _ in range(count):
                end = body.index(0, pos + 2) + 1
                if body[pos : pos + 2] != b"\x00\x00":
                    entries.append(body[pos:end])
                pos = end
            body = struct.pack("<H", len(entries)) + b"".join(entries)
        if kind not in {0, 1, 4, 5, 12, 15, 26, 28, 43, 70, 89, 94}:
            out.extend(_tag(kind, body))
    abc = base64.b64decode((ROOT_DIR / "scripts/practice/practice.abc.b64").read_bytes().strip(), validate=True)
    out.extend(_tag(82, b"\x01\x00\x00\x00Practice\x00" + abc))
    out.extend(_tag(76, b"\x01\x00\x00\x00Practice\x00") + _tag(1, b"") + _tag(0, b""))
    return b"CWS" + source[3:4] + struct.pack("<I", len(out) + 8) + zlib.compress(out)


@practice.get("/practice/player.swf")
@practice.get("/practice/pdw/assets/game/player.swf")
def player() -> Response:
    response = Response(_practice_movie(), mimetype="application/x-shockwave-flash")
    response.add_etag()
    return response.make_conditional(request)


@practice.get("/practice/pdw/assets/game/<filename>")
def cafe_component(filename) -> Response:
    directory = SHARED_DIR / "src/swf/pdw/assets/game"
    if filename == "count.swf":
        return send_file(directory / filename)
    match = re.fullmatch(r"game(?:5|11)(pm|p1|ta|fr|cp)\.swf", filename)
    if not match:
        abort(404)
    path = directory / filename
    # Some archive editions place the same empty movie under four aliases.
    # The matching original component movies are also present under their working names.
    aliases = {"pm": "PokecafePokemon.swf", "p1": "p1_.swf", "ta": "tamagedake.swf", "fr": "frametest.swf"}
    if match[1] in aliases and (
        not path.exists()
        or hashlib.sha256(path.read_bytes()).hexdigest()
        == "8a9aeeb3091575e936f2bdff35cef36671791fd6c82a4f87cbbfa99a4e7ef711"
    ):
        path = directory / aliases[match[1]]
    return send_file(path, mimetype="application/x-shockwave-flash")
