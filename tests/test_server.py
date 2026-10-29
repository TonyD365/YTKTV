from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeSource, make_song, wait_for
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


def test_danmaku_guide_and_lights_over_http(client):
    http, controller = client
    seen = []
    controller.bus.subscribe(lambda topic, data: seen.append(data) if topic == "danmaku" else None)
    assert http.post("/api/danmaku", json={"text": "Encore!"}).json() == {"ok": True}
    assert seen == [{"text": "Encore!"}]
    assert http.post("/api/danmaku", json={"text": ""}).status_code == 422
    assert http.post("/api/danmaku", json={"text": "   "}).status_code == 429
    for _ in range(10):
        last = http.post("/api/danmaku", json={"text": "spam"})
    assert last.status_code == 429

    state = http.post("/api/sound", json={"guide_vocal": 25, "lights": False}).json()
    assert state["guide_vocal"] == 25 and state["lights"] is False
    assert state["scoring"] is True and state["last_score"] is None
    assert http.post("/api/sound", json={"scoring": False}).json()["scoring"] is False
    assert state["show_lyrics"] is True
    assert http.post("/api/sound", json={"show_lyrics": False}).json()["show_lyrics"] is False
    assert http.post("/api/sound", json={"lyrics_offset": 11}).status_code == 422
    assert http.post("/api/sound", json={"lyrics_offset": 0.3}).json()["lyrics_offset"] == 0.0
    assert http.post("/api/sound", json={"guide_vocal": 101}).status_code == 422
    assert http.get("/api/lyrics").json() == []


def test_phones_are_told_apart_and_find_their_own_songs(client):
    http, controller = client
    me = http.get("/api/me").json()["id"]
    assert len(me) == 10 and "testclient" not in me  # a fingerprint, not the address

    songs = http.get("/api/search", params={"q": "x", "limit": 3}).json()
    for song in songs:
        assert http.post("/api/queue", json={"song": song}).json()["owner"] == me
    controller.enqueue(make_song(9))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    state = http.get("/api/state").json()
    assert state["current"]["owner"] == me
    assert [item["owner"] for item in state["queue"]] == [me, me, ""]  # the last from the console


def test_games_over_http(client):
    http, _ = client
    assert http.post("/api/game/dare").json()["title"].endswith("Dare")
    assert http.post("/api/game/chess").status_code == 404


def test_reactions_over_http(client):
    http, controller = client
    seen = []
    controller.bus.subscribe(lambda topic, data: seen.append(data) if topic == "reaction" else None)
    assert http.get("/api/state").json()["reactions"][0] == "❤️"
    assert http.post("/api/reaction", json={"emoji": "🎉"}).json() == {"ok": True}
    assert seen == [{"emoji": "🎉"}]
    assert http.post("/api/reaction", json={"emoji": "💩"}).status_code == 429


def test_more_games_over_http(client):
    http, controller = client
    assert http.post("/api/game/bomb").json()["text"] == "1 – 100"
    assert http.post("/api/game/bomb_guess", json={"value": 50}).status_code == 200
    assert http.post("/api/game/bomb_guess", json={"value": 500}).status_code == 422
    mine = http.post("/api/game/liar_roll", json={}).json()["mine"]
    assert len(mine.split()) == 5
    assert "Phone" in http.post("/api/game/liar_reveal").json()["text"]
    assert http.post("/api/game/sevens").json()["text"] == "1"


def test_phone_games_use_the_phone_name(client):
    http, controller = client
    reply = http.post("/api/game/liar_roll", json={"player": "Kim"}).json()
    assert "Kim" in controller.liars.hands and len(reply["mine"].split()) == 5
    dice = http.post("/api/game/dice", json={"value": 2}).json()
    assert len(dice["text"].split()) == 2
