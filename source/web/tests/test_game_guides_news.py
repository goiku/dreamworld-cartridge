"""The archived homepage, game stage and public guides must agree on localized content."""
from flask import url_for

from api import pgl_news, practice
from api.server import create_app
from utils.data import load_json_data


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
