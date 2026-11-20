"""The public arcade has no player identity, write route or cartridge dependency."""

import struct
import zlib

from api import practice
from api.server import create_app
from utils.data import load_json_data


def test_all_games_available_without_a_session():
    client = create_app().test_client()
    menu = client.get("/practice/")
    assert menu.status_code == 200 and not menu.headers.get("Set-Cookie")
    for number in range(1, 13):
        route = f"/practice/{number}/"
        assert route.encode() in menu.data
        page = client.get(route)
        assert page.status_code == 200 and not page.headers.get("Set-Cookie")
        assert f'data-game="{number}"'.encode() in page.data
        assert client.post(route).status_code == 405
    for route in ("/practice/0/", "/practice/13/", "/practice/pdw/assets/game/no.swf"):
        assert client.get(route).status_code == 404
    assert all(len(labels["games"]) == 12 for labels in load_json_data("practice").values())


def test_archived_stage_and_cafe_movies():
    client = create_app().test_client()
    root = "/practice/pdw/assets/game/"
    response = client.get(root + "player.swf")
    content = response.data
    assert content[:3] == b"CWS" and len(zlib.decompress(content[8:])) + 8 == struct.unpack_from("<I", content, 4)[0]
    assert client.get(root + "player.swf", headers={"If-None-Match": response.headers["ETag"]}).status_code == 304
    for number in (5, 11):
        movie = client.get(root + f"game{number}pm.swf").data
        assert b"po19\0" in zlib.decompress(movie[8:])
    assert practice._practice_movie.cache_info().hits >= 1
