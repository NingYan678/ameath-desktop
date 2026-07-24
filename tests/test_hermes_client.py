from pathlib import Path

import httpx

from digital_pet.config import Settings
from digital_pet.hermes_client import HermesClient


def test_http_chat_retries_a_temporary_server_error(monkeypatch, tmp_path):
    settings = Settings(tmp_path, tmp_path, "http://localhost:8000/v1", "", "model", 30, Path("missing"), Path("missing"))
    responses = [
        httpx.Response(503, request=httpx.Request("POST", "http://localhost:8000/v1/chat/completions")),
        httpx.Response(
            200,
            json={"choices": [{"message": {"content": '{"reply":"ready","state":"attention","proposal":null}'}}]},
            request=httpx.Request("POST", "http://localhost:8000/v1/chat/completions"),
        ),
    ]

    def fake_post(*args, **kwargs):
        return responses.pop(0)

    monkeypatch.setattr("digital_pet.hermes_client.httpx.post", fake_post)
    monkeypatch.setattr("digital_pet.hermes_client.time.sleep", lambda _: None)

    reply = HermesClient(settings).chat("hello")

    assert reply.reply == "ready"
    assert not responses
