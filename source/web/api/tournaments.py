"""Offer verified Japanese PWT files. The player's save stays inside their browser."""

import hashlib
import tempfile
from functools import cache
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

from flask import Blueprint, Response, abort, render_template

from config import LANG, SAVE_DIR
from utils.data import load_json_data

tournaments = Blueprint(
    "tournaments",
    __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/campaign/pwt/assets",
)
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


@tournaments.get("/campaign/japan/tournaments/")
def index() -> str:
    return render_template(
        "tournaments.html", lang=LANG, t=load_json_data("tournament_ui")[LANG], rows=catalog().values()
    )


@tournaments.get("/campaign/japan/tournaments/<sha>.pwt")
def download(sha) -> Response:
    row = catalog().get(sha) or abort(404)
    try:
        raw = tournament_file(row)
    except (OSError, ValueError, URLError):
        abort(503)
    response = Response(raw, mimetype="application/octet-stream")
    response.headers.set("Content-Disposition", "attachment", filename=f"JP-{row['number']}-{sha[:8]}.pwt")
    return response
