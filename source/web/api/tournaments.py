"""Offer verified Japanese PWT files. The player's save stays inside their browser."""

from flask import Blueprint, Response, abort, render_template

from config import LANG
from utils.pwt_archive import catalog, tournament_file
from utils.data import load_json_data

tournaments = Blueprint(
    "tournaments",
    __name__,
    template_folder="../templates",
    static_folder="../static",
    static_url_path="/campaign/pwt/assets",
)


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
    except (OSError, ValueError):
        abort(503)
    response = Response(raw, mimetype="application/octet-stream")
    response.headers.set("Content-Disposition", "attachment", filename=f"JP-{row['number']}-{sha[:8]}.pwt")
    return response
