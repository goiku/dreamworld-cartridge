from types import SimpleNamespace

from flask import Flask
import pytest

from game_sync_server.entralinked.network.http.nas_handler import NasHandler
from game_sync_server.entralinked.utility.url_encoded_form import decode_form, encode_form
from utils import badwords


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(NasHandler(SimpleNamespace(configuration=None, user_manager=None)).blueprint())
    return app.test_client()


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16"])
def test_name_check_between_validation_and_deposit(client, monkeypatch, encoding):
    monkeypatch.setattr(badwords, "contains_bad_word", lambda name: name == "Sample")
    data = encode_form({"words": "ピィ\tSample\tLeaf\0".encode(encoding).decode("latin-1")})
    for _ in range(2):
        response = client.post("/pr", data=data)
        assert response.status_code == 200 and response.headers["NODE"] == "wifiappe1"
        fields = decode_form(response.get_data(as_text=True))
        assert fields["returncd"] == "000" and len(fields["datetime"]) == 14
        assert all(fields["prwords" + region] == "010" for region in ["", *"ACEJKP"])


@pytest.mark.parametrize("data", ["", "words=!!!"])
def test_invalid_name_request(client, data):
    response = client.post("/pr", data=data)
    assert decode_form(response.get_data(as_text=True))["returncd"] == "102"
