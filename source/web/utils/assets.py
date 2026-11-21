"""Serves and patches the mirrored site files in dreamworld_assets/."""
import mimetypes
import os
import re
from pathlib import Path

from flask import Response, current_app

from config import ASSET_LANG, LANG, ROOT_DIR, SUPPORTED_LANGUAGES
from utils.patching import apply_substitutions

ASSETS_DIR = ROOT_DIR / "dreamworld_assets"
SITE_DIR   = ASSETS_DIR / f"{LANG}.pokemon-gl.com"
BASE_DIR   = ASSETS_DIR / f"{ASSET_LANG}.pokemon-gl.com"
SITE_DIRS  = (SITE_DIR, BASE_DIR) if SITE_DIR != BASE_DIR else (SITE_DIR,)
SHARED_DIR = ASSETS_DIR / "shared.pokemon-gl.com"
RUFFLE_SCRIPT = SHARED_DIR / "_ruffle" / "ruffle.js"
HOST_MIRRORS = ("assets.pokemon.com", "www.pokemon.com")
_LANG_SEGMENT = re.compile(rf"/({'|'.join(SUPPORTED_LANGUAGES)})/")
_GAME_ASSETS = "src/swf/pdw/assets/game/"
# Archive variants reference these resources from alternate locations.
_GAME_ALIASES = {
    **{f"game{game}/bgm_{area}.swf": f"game1/bgm_{area}.swf"
       for game in (7, 9) for area in ("forest", "sea", "sky")},
    **{f"{kind}_{lang}.xml": f"game9/{kind}_{lang}.xml"
       for lang in SUPPORTED_LANGUAGES for kind in ("strings", "format")},
}

# Text files get apply_substitutions before serving. Binary assets (images, fonts, etc.)
# are served as-is.
PATCHABLE_EXTENSIONS = {".js", ".html", ".css"}


def read_and_patch(file_path: Path) -> bytes:
    """Return the file's contents, with the text patches applied if it's a patchable type."""
    data = file_path.read_bytes()
    if LANG == "zh" and file_path.name in ("areas.js", "pokemons.js") and file_path.parent == SHARED_DIR / "report/assets/js":
        from utils.zh_web_data import localize_report_catalog
        data = localize_report_catalog(data, file_path.name)

    if not data and file_path.name == "tutorial_format.xml":
        # Six languages ship a blank sheet and use the client's default styles.
        data = b"<data/>"
    if file_path.parent.name == "spxml" and file_path.suffix == ".xml":
        # Some archived special-island maps joined the width and height attributes.
        data = re.sub(rb'(\bwidth="\d+")height=', rb'\1 height=', data)
        # The movie trailer streamed from a retired remote RTMP host. The client
        # omits its optional theater button when the trailer is absent from the map.
        data = re.sub(rb'<movieplayer\b[^>]*>.*?</movieplayer>', b'', data, flags=re.DOTALL)
        data = re.sub(rb'<ballon type="moviepanel"[^>]*/>', b'', data)
        # The Movie board can close normally without the retired external detail page.
        data = data.replace(b'url="http://ja.pokemon-gl.com/about/sp/movie2011/index.html"', b'url=""')
    if file_path.name == "sp_setting.xml":
        # The local country list represents Japan as 0; the archived web host used a special ID.
        data = data.replace(b"</country>", b"<target>0</target></country>")
    if file_path.suffix.lower() == ".html" and LANG == "zh":
        from utils.zh_web import localize_html
        data = localize_html(data)
    if file_path.suffix.lower() == ".html" and b'id="select-language"' in data:
        def language_links(match: re.Match) -> bytes:
            menu = re.sub(rb"""href=["'](?:https?:/)?/([a-z]{2})\.pokemon-gl\.com/?["']""",
                          rb'href="/languages/\1/"', match[0])
            if "简体中文".encode() not in menu:
                menu = menu[:-5] + '<li><a href="/languages/zh/">简体中文</a></li></ul>'.encode()
            return menu
        data = re.sub(rb'<ul\s+id="select-language"[^>]*>[\s\S]*?</ul>', language_links, data, count=1)
    if file_path.suffix.lower() in PATCHABLE_EXTENSIONS:
        data = apply_substitutions(data, file_path.name)
    if file_path.suffix.lower() == ".html" and RUFFLE_SCRIPT.is_file():
        data = re.sub(
            rb"<head(?:\s[^>]*)?>",
            lambda match: match[0] + b'<script src="/_ruffle/ruffle.js"></script>',
            data,
            count=1,
            flags=re.IGNORECASE,
        )

    return data


def serve_file(file_path: Path) -> Response:
    """Return a response with the patched file and a content type guessed from its name."""
    content_type, _ = mimetypes.guess_type(file_path)
    data = read_and_patch(file_path)
    if content_type == "image/jpeg" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        # Two Italian tutorial pictures have .jpg names and PNG contents.
        content_type = "image/png"
    return Response(data, content_type=content_type or "application/octet-stream")


def not_found(path: str) -> Response:
    """Log and return a 404 response."""
    current_app.logger.info("404 %s", path)
    return Response("Error: Not found", status=404, content_type="text/html")


def path_inside(base: Path, relative: str) -> Path | None:
    """Return base / relative, or None if that would escape base (e.g. through ..)."""
    path = Path(os.path.normpath(base / relative))
    return path if path.is_relative_to(base) else None


def site_directories(relative: str):
    """Yield matching site directories in display-locale then archived-locale order."""
    for base in SITE_DIRS:
        directory = path_inside(base, relative)
        if directory and directory.is_dir():
            yield directory


def resolve_static(path: str) -> Path | None:
    """Return the file for a static asset URL.

    Look in a host mirror, else the site directory, else the shared directory. Return
    None if there's no such file.
    """
    relative = path.lstrip("/")

    # An override can replace a Japanese or shared asset at its original URL.
    # Browser scripts can also build URLs with the display locale in the path.
    if LANG == "zh":
        archived = re.sub(r"(^|/)zh(?=/)|(_)(?:zh)(?=\.)", r"\1\2ja", relative)
        paths = (relative, archived, _LANG_SEGMENT.sub("/", archived))
        for candidate in dict.fromkeys(paths):
            override = path_inside(SITE_DIR, candidate)
            if override and override.is_file():
                return override
        relative = archived

    if relative.startswith(tuple(f"{host}/" for host in HOST_MIRRORS)):
        host_path = path_inside(ASSETS_DIR, relative)
        if host_path and host_path.is_file():
            return host_path
        if host_path and (host_path / "index.html").is_file():
            return host_path / "index.html"

    site_path = path_inside(BASE_DIR, relative)
    if site_path and site_path.is_file():
        return site_path

    if relative.startswith("top/assets/images/info-default/"):
        candidate = path_inside(SHARED_DIR / "src/swf/top/images/info-default",
                                relative.removeprefix("top/assets/images/info-default/"))
        if candidate and candidate.is_file():
            return candidate

    # Some shared paths carry localized files, including the header sprites.
    shared_path = path_inside(SHARED_DIR, relative)
    if shared_path and shared_path.is_file():
        return shared_path

    # Follow archived language-prefixed URLs for assets stored without the prefix.
    shared_path = path_inside(SHARED_DIR, _LANG_SEGMENT.sub("/", relative))
    if shared_path and shared_path.is_file():
        return shared_path

    if relative.startswith(_GAME_ASSETS):
        alias = _GAME_ALIASES.get(relative.removeprefix(_GAME_ASSETS))
        if alias:
            target = SHARED_DIR / _GAME_ASSETS / alias
            if target.is_file():
                return target

    return None
