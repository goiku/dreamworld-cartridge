"""The archived homepage, game stage and public guides must agree on localized content."""
from flask import url_for

from api import pgl_news, practice
from api.server import create_app
from utils.data import load_json_data


def test_guide_home_links_use_the_current_host_and_language(monkeypatch):
    from api import player_guide

    client = create_app().test_client()
    for lang, labels in player_guide._messages.items():
        monkeypatch.setattr(player_guide, "LANG", lang)
        for path in ("/player-guide/", "/player-guide/phone/", "/player-guide/pictures/"):
            page = client.get(path, base_url="http://192.168.2.3:8088").get_data(as_text=True)
            assert page.count('class="guide-home" href="/"') == 2
            assert page.count(labels["back_home"]) >= 2
    for path in ("/information/", "/player-guide/pictures/"):
        location = client.get("/languages/ja/", query_string={"page": path}).location
        assert location.endswith(":8081" + path)


def test_picture_guide_loads_one_step_and_preserves_archive_variants(monkeypatch, tmp_path):
    from api import player_guide

    monkeypatch.setattr(player_guide, "SITE_DIR", tmp_path)
    monkeypatch.setattr(player_guide, "ASSET_LANG", "ja")
    monkeypatch.setattr(player_guide, "LANG", "zh")
    folder = tmp_path / "src/swf/pdw/assets/ja/img"
    folder.mkdir(parents=True)
    for number in ("02", "02a", "03"):
        (folder / f"tutorial02-{number}.jpg").touch()
    (folder / "tutorial-captions.json").write_text('{"tutorial02-02a.jpg":"查看梦友地图"}', encoding="utf-8")
    player_guide._picture_chapters.cache_clear()
    try:
        client = create_app().test_client()
        base = "/player-guide/pictures/"
        index = client.get(base).get_data(as_text=True)
        assert "<img " not in index and base + "02/1/" in index
        page = client.get(base + "02/2/").get_data(as_text=True)
        assert page.count("<img ") == 1 and "tutorial02-02a.jpg" in page
        assert "查看梦友地图" in page and base + "02/1/" in page and base + "02/3/" in page
        assert client.get(base + "02/4/").status_code == 404
        assert client.get(base + "06/1/").status_code == 404
    finally:
        player_guide._picture_chapters.cache_clear()


def test_every_translated_game_links_to_its_own_practice(monkeypatch):
    from api import player_guide

    app = create_app()
    client = app.test_client()
    for lang in load_json_data("practice"):
        monkeypatch.setattr(player_guide, "LANG", lang)
        monkeypatch.setattr(practice, "LANG", lang)
        practice.labels.cache_clear()
        try:
            labels = practice.labels()
            guide = client.get("/player-guide/").get_data(as_text=True)
            assert 'id="minigames"' in guide
            assert len(labels["instructions"]) == len(labels["games"]) == 12
            assert len(player_guide._messages[lang]["dream_steps"]) == 5
            for number, steps in enumerate(labels["instructions"], 1):
                with app.test_request_context():
                    path = url_for("practice.arcade", number=number)
                page = client.get(path).get_data(as_text=True)
                assert f'href="{path}"' in guide
                assert all(step in page and step in guide for step in steps)
        finally:
            practice.labels.cache_clear()


def test_original_articles_have_translations_and_pagination(monkeypatch):
    raw = load_json_data("news")["news"]
    assert set(load_json_data("news_zh")) == {k for k, row in raw.items() if "jp" in (row.get("title") or {})}
    monkeypatch.setattr(pgl_news, "LANG", "zh")
    client = create_app().test_client()
    def page(offset):
        return client.get("/api/", query_string={"p":"pgl.news.news_list", "offset":offset,"rowcount":4}).json
    assert len(page(0)) == 4 and page(0)[0]["url"] == "/player-guide/"
    assert {x["news_id"] for x in page(0)}.isdisjoint(x["news_id"] for x in page(4))
    assert page(99999) == []
    overview = client.get("/information/").get_data(as_text=True)
    assert "七夕青鸟" in overview
    for item in page(0):
        assert item["title"] in overview
        assert client.get(f"/top/assets/images/info-default/{item['news_category_id']}.png").data.startswith(b"\x89PNG")
