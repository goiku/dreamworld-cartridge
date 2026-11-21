import io
import logging

import pytest
from flask import Flask, request
from werkzeug.test import EnvironBuilder

from game_sync_server.entralinked.network.http.http_server import RequestBodyMiddleware


@pytest.mark.parametrize("missing", [0, 1])
def test_fragmented_upload_requires_the_last_byte(missing, caplog):
    payload = bytes(range(256)) * 2048
    submitted = []
    requests = []

    class ShortReads(io.BytesIO):
        def read(self, size=-1):
            requests.append(size)
            return super().read(min(509, size))

    app = Flask(__name__)
    app.wsgi_app = RequestBodyMiddleware(app.wsgi_app)

    @app.post("/dsio/gw")
    def upload():
        submitted.append(request.get_data())
        return b"OK"

    env = EnvironBuilder(path="/dsio/gw", method="POST",
                         query_string={"p": "savedata.upload", "tok": "private-test-token"}).get_environ()
    env.update({"CONTENT_LENGTH": str(len(payload)), "wsgi.input": ShortReads(payload[:len(payload) - missing])})
    with caplog.at_level(logging.INFO), app.test_client() as client:
        result = client.open(environ_overrides=env)
    assert result.status_code == (400 if missing else 200)
    assert submitted == ([] if missing else [payload])
    assert 0 < max(requests) <= 16 * 1024
    assert ("Tuck-in upload timing" in caplog.text) == (not missing)
    assert "private-test-token" not in caplog.text
