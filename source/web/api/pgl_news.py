"""Serve archived Global Link articles alongside the current server's player guide."""
from functools import cache
from pathlib import PurePosixPath

from flask import Blueprint, render_template, session

from api.routes import Query, endpoint
from config import ASSET_LANG, LANG
from utils.assets import resolve_static
from utils.data import load_json_data

news_pages = Blueprint("news_pages", __name__, template_folder="../templates")
# The early Flash client and the later homepage used different category numbers.
HOME_CATEGORY = {1: 9, 2: 10, 3: 8, 4: 12, 5: 12, 6: 11}
ARCHIVE = {
    "zh": ("历年公告", "档案仅保留了这则公告的标题。"),
    "ja": ("過去のお知らせ", "このお知らせは見出しのみ保存されています。"),
    "en": ("Archived announcements", "Only the headline survives in the archive."),
    "fr": ("Annonces archivées", "Seul le titre de cette annonce a été conservé."),
    "de": ("Frühere Mitteilungen", "Von dieser Mitteilung ist nur die Überschrift erhalten."),
    "it": ("Notizie d’archivio", "Di questa notizia è stato conservato solo il titolo."),
    "es": ("Noticias de archivo", "Solo se conserva el título de esta noticia."),
    "ko": ("지난 공지", "이 공지는 제목만 남아 있습니다."),
}


def _available_picture(value: str | None) -> str:
    if not value:
        return ""
    path = PurePosixPath(value)
    if not value.startswith("/") or ".." in path.parts:
        return ""
    resource = f"/src/swf/information/assets/{ASSET_LANG}/img{value}"
    return value if resolve_static(resource) else ""


@cache
def _archive(lang: str, signed_in: bool) -> tuple:
    articles = []
    source_lang = "jp" if lang in ("ja", "zh") else lang
    chinese = load_json_data("news_zh") if lang == "zh" else {}
    for ident, row in load_json_data("news")["news"].items():
        title = (row.get("title") or {}).get(source_lang)
        if not title:
            continue
        metadata = (row.get("api") or {}).get(source_lang, {})
        if str(metadata.get("login_flag", 0)) == "1" and not signed_in:
            continue
        description = (row.get("description") or {}).get(source_lang)
        if lang == "zh":
            title, description = chinese[ident]
        category = int(metadata.get("news_category_id", 0))
        articles.append(dict(news_id=int(ident), news_category_id=HOME_CATEGORY.get(category, 8),
                             archive_category=category, date=row.get("date") or "",
                             title=title, description=description or ARCHIVE[lang][1],
                             new_flag=0, url_flag=0, url="", url_link_type=1,
                             filename=_available_picture(metadata.get("filename")),
                             filename_top=_available_picture(metadata.get("filename_top"))))
    return tuple(sorted(articles, key=lambda item: (item["date"], item["news_id"]), reverse=True))


def _articles() -> list:
    # A permanent local link also works in editions without surviving news articles.
    guide = load_json_data("player_guide")[LANG]
    entry = dict(news_id=1, news_category_id=8, date="", title=guide["title"], new_flag=0,
                 description="", url="/player-guide/", url_flag=1, url_link_type=1,
                 filename="", filename_top="", archive_category=0)
    return [entry, *_archive(LANG, bool(session.get("username")))]


def _window(query: Query, name: str, default: int) -> int:
    try:
        return max(0, int(query.get(name, default)))
    except (ValueError, TypeError):
        return default


@endpoint("pgl.news.news_list")
def news_list(query: Query) -> list:
    start = _window(query, "offset", 0)
    return _articles()[start:start + min(100, _window(query, "rowcount", 10))]


@endpoint("pgl.news.information_list")
def information_list(query: Query) -> dict:
    rows = _articles()
    start = _window(query, "offset", 0)
    selection = rows[start:start + min(100, _window(query, "rowcount", 10))]
    return {"list": [dict(row, news_category_id=row["archive_category"]) for row in selection], "total_count": len(rows)}


@news_pages.get("/information/")
@news_pages.get("/information/index.html")
def archive_page():
    return render_template("news_archive.html", lang=LANG, heading=ARCHIVE[LANG][0],
                           language_label=load_json_data("practice")[LANG]["language_label"], rows=_articles())
