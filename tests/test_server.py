from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeSource, wait_for
from ytktv.core.models import PlayStatus
from ytktv.server.app import create_app


@pytest.fixture
def client(ktv):
    controller, _, _ = ktv
    with TestClient(create_app(controller, FakeSource())) as test_client:
        yield test_client, controller


def test_index_page_is_served(client):
    http, _ = client
    response = http.get("/")
    assert response.status_code == 200
    assert "YTKTV Remote" in response.text


def test_search_and_categories(client):
    http, _ = client
    results = http.get("/api/search", params={"q": "karaoke", "limit": 5}).json()
    assert len(results) == 5 and {"video_id", "title", "thumbnail"} <= results[0].keys()
    categories = http.get("/api/categories").json()
    assert "Karaoke Hits" in categories
    assert http.get("/api/hot", params={"category": categories[0]}).status_code == 200
    assert http.get("/api/hot", params={"category": "nope"}).status_code == 404


def test_queue_lifecycle_over_http(client):
    http, controller = client
    songs = http.get("/api/search", params={"q": "x", "limit": 3}).json()
    for song in songs:
        assert http.post("/api/queue", json={"song": song, "singer": " Bo "}).status_code == 200
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    state = http.get("/api/state").json()
    assert state["current"]["song"]["video_id"] == songs[0]["video_id"]
    assert state["current"]["singer"] == "Bo"
    queue = state["queue"]
    assert len(queue) == 2

    assert http.post(f"/api/queue/{queue[1]['id']}/top").status_code == 200
    assert http.get("/api/state").json()["queue"][0]["id"] == queue[1]["id"]
    assert http.post(f"/api/queue/{queue[1]['id']}/move", json={"index": 1}).status_code == 200
    assert http.delete(f"/api/queue/{queue[0]['id']}").status_code == 200
    assert http.delete(f"/api/queue/{queue[0]['id']}").status_code == 404
    assert len(http.get("/api/state").json()["queue"]) == 1


def test_enqueue_by_url_and_validation(client):
    http, _ = client
    ok = http.post("/api/queue", json={"url": "https://youtu.be/dQw4w9WgXcQ", "priority": True})
    assert ok.status_code == 200 and ok.json()["song"]["title"] == "Looked up"
    assert http.post("/api/queue", json={"url": "https://example.com/nope"}).status_code == 400
    assert http.post("/api/queue", json={}).status_code == 400
    assert http.post("/api/queue", json={"song": {"video_id": "../../etc"}}).status_code == 422


def test_player_and_sound_controls(client):
    http, controller = client
    assert http.post("/api/player/explode").status_code == 404
    assert http.post("/api/player/skip").status_code == 200
    state = http.post(
        "/api/sound", json={"pitch": 2, "music_volume": 30, "vocal_mode": "original"}
    ).json()
    assert (state["pitch"], state["music_volume"], state["vocal_mode"]) == (2, 30, "original")
    assert state["mic_volume"] == 80
    assert http.post("/api/sound", json={"pitch": 40}).status_code == 422
    assert http.post("/api/sound", json={"vocal_mode": "loud"}).status_code == 422
    assert http.post("/api/sfx/applause").json() == {"ok": False}  # no audio engine in tests
    assert http.post("/api/sfx/nope").status_code == 404


def test_favorites_over_http(client):
    http, _ = client
    song = http.get("/api/search", params={"q": "x", "limit": 1}).json()[0]
    assert http.post("/api/favorites", json=song).json() == {"favorite": True}
    assert [s["video_id"] for s in http.get("/api/favorites").json()] == [song["video_id"]]
    assert http.post("/api/favorites", json=song).json() == {"favorite": False}


def test_websocket_pushes_state_changes(client):
    http, _ = client
    song = http.get("/api/search", params={"q": "x", "limit": 1}).json()[0]
    with http.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "state" and first["data"]["current"] is None
        http.post("/api/queue", json={"song": song})
        for _ in range(10):
            message = ws.receive_json()
            if message["type"] == "state" and message["data"]["current"]:
                break
        else:
            pytest.fail("no state update with the new song arrived")
