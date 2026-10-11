"""Phone-remote HTTP API latency (in-process, no network)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeSource, make_controller, make_song
from ytktv.server.app import create_app


@pytest.fixture
def api(tmp_path):
    controller, _, _ = make_controller(tmp_path)
    for i in range(30):
        controller.queue.add(make_song(i))
    with TestClient(create_app(controller, FakeSource())) as client:
        yield client, controller
    controller.close()


def test_get_state(benchmark, api):
    client, _ = api
    response = benchmark(client.get, "/api/state")
    assert response.status_code == 200


def test_search(benchmark, api):
    client, _ = api
    response = benchmark(client.get, "/api/search", params={"q": "karaoke"})
    assert response.status_code == 200


def test_enqueue_and_remove(benchmark, api):
    client, _ = api
    body = {"song": make_song(999).to_dict(), "singer": "Bench"}

    def run():
        item = client.post("/api/queue", json=body).json()
        return client.delete(f"/api/queue/{item['id']}")

    assert benchmark(run).status_code == 200


def test_sound_update(benchmark, api):
    client, _ = api
    response = benchmark(client.post, "/api/sound", json={"pitch": 1, "music_volume": 70})
    assert response.status_code == 200
