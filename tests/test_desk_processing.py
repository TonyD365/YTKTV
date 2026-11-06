"""The Desk separates songs (and writes lyrics) for its rooms; rooms fall back to themselves."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.helpers import wait_for
from ytktv.config import SettingsStore
from ytktv.core.models import StemStatus
from ytktv.desk import processing
from ytktv.desk.server import Hub, create_desk_app
from ytktv.desk.store import DeskStore
from ytktv.rooms import processing as room_processing
from ytktv.rooms.processing import DeskOff, DeskStems
from ytktv.separation.cache import StemCache


class FakeStems:
    """The Desk's StemManager: songs become ready when the test says so."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.status_of: dict[str, StemStatus] = {}
        self.requested: list[str] = []
        self.retained: set[str] = set()
        self.order = lambda: []
        self.on_change = lambda *_a: None
        self.want_pitch = False

    def request(self, video_id):
        self.requested.append(video_id)
        return self.status_of.setdefault(video_id, StemStatus.QUEUED)

    def status(self, video_id):
        return self.status_of.get(video_id, StemStatus.NONE)

    def finish(self, video_id):
        (self.folder / f"{video_id}.flac").write_bytes(b"instrumental " + video_id.encode())
        (self.folder / f"{video_id}.json").write_text('{"hop":0.05,"notes":[60]}')
        self.status_of[video_id] = StemStatus.READY
        self.on_change(video_id, StemStatus.READY)

    def path(self, video_id):
        path = self.folder / f"{video_id}.flac"
        return path if path.exists() else None

    def pitch(self, video_id):
        path = self.folder / f"{video_id}.json"
        return path if path.exists() else None

    def retain(self, wanted):
        self.retained = set(wanted)


class FakeLyrics:
    installed = True

    def __init__(self, folder: Path) -> None:
        self.folder, self.requests = folder, []

    def path(self, video_id):
        return self.folder / f"{video_id}.lyrics.json"

    def cached(self, video_id):
        return [] if self.path(video_id).exists() else None

    def request(self, video_id, hint="", first=False):
        self.requests.append((video_id, hint, first))
        self.path(video_id).write_text(json.dumps([{"start": 1, "end": 2, "text": "la"}]))


def test_every_room_s_first_song_comes_before_anyone_s_second():
    orders = {"b": ["b1", "b2"], "a": ["a1", "a2", "a3"], "c": ["a1", "c2"]}
    assert processing.merged_order(orders) == ["a1", "b1", "a2", "b2", "c2", "a3"]


@pytest.fixture
def desk(tmp_path):
    store = DeskStore()
    room, key = store.pair(store.new_code(), "Room 1")
    stems = FakeStems(tmp_path)
    lyrics = FakeLyrics(tmp_path)
    processor = processing.SongProcessor(stems, lyrics, tmp_path / "uploads")
    app = create_desk_app(store, Hub(), processor=processor)
    client = TestClient(app)
    settings = SettingsStore(tmp_path / "room.json")
    s = settings.settings
    s.desk_url, s.room_id, s.room_key, s.desk_key = "https://desk", room.room_id, key, "k"
    return client, processor, stems, lyrics, settings, app


def send_through(client):
    """The room's request function, sent to the Desk's app in-process."""

    def send(settings, method, path, body=None):
        headers = room_processing.signed_headers(settings, method, path)
        if body is not None:
            headers["Content-Type"] = room_processing.content_type(path)
        response = client.request(method, path, content=body, headers=headers)
        if response.status_code in (401, 503):
            raise DeskOff(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response.content

    return send


def test_only_paired_rooms_with_a_good_signature_get_in(desk):
    client, _processor, _stems, _lyrics, settings, app = desk
    headers = room_processing.signed_headers(settings.settings, "POST", "/api/process")
    assert client.post("/api/process", json={"songs": []}, headers=headers).status_code == 200
    bad = {**headers, "X-YTKTV-Mac": "0" * 64}
    assert client.post("/api/process", json={"songs": []}, headers=bad).status_code == 401
    old = room_processing.signed_headers(settings.settings, "POST", "/api/other")
    assert client.post("/api/process", json={"songs": []}, headers=old).status_code == 401
    app.state.processor = None  # processing switched off
    headers = room_processing.signed_headers(settings.settings, "POST", "/api/process")
    assert client.post("/api/process", json={"songs": []}, headers=headers).status_code == 503


def test_a_room_gets_the_desk_s_instrumental_melody_and_lyrics(desk, tmp_path):
    client, processor, stems, lyrics, settings, _app = desk
    cache = StemCache(tmp_path / "room-stems", 10**9)
    room = DeskStems(settings, cache, tmp_path / "room-lyrics", send=send_through(client))
    changes, written = [], []
    room.on_change = lambda video_id, status: changes.append((video_id, status))
    room.order = lambda: ["song1", "song2"]
    room.hints = lambda video_id: f"words of {video_id}"
    room.on_lyrics = lambda video_id, path: written.append(video_id)
    assert room.request("song1") == StemStatus.QUEUED
    room.request("song2")
    room.poll()
    assert stems.requested[:2] == ["song1", "song2"] and processor.order() == ["song1", "song2"]
    stems.finish("song1")  # the Desk separated it and wrote its lyrics, hint and all
    assert lyrics.requests == [("song1", "words of song1", True)]
    room.poll()
    assert room.status("song1") == StemStatus.READY and ("song1", StemStatus.READY) in changes
    assert room.path("song1").read_bytes() == b"instrumental song1"
    assert room.pitch("song1") is not None and written == ["song1"]
    assert (tmp_path / "room-lyrics" / "song1.json").exists()
    assert room.status("song2") == StemStatus.QUEUED


def test_without_the_desk_the_room_does_it_itself(tmp_path):
    settings = SettingsStore(tmp_path / "room.json")
    s = settings.settings
    s.desk_url, s.room_id, s.room_key, s.desk_key = "https://desk", "r", "key", "k"

    class Local(FakeStems):
        pass

    local = Local(tmp_path)

    def off(*_a, **_k):
        raise DeskOff("unreachable")

    room = DeskStems(settings, StemCache(tmp_path / "c", 10**9), tmp_path / "l", local, send=off)
    room.order = lambda: ["song1"]
    room.request("song1")
    room.poll()
    assert local.requested == ["song1"]
    room.request("song2")  # the Desk is known to be off: straight here
    assert local.requested == ["song1", "song2"]
    s.process_on_desk = False
    s.desk_url = ""  # unbound too


def test_a_song_the_desk_cannot_download_is_sent_to_it(desk, tmp_path):
    client, _processor, stems, _lyrics, settings, _app = desk
    audio = []

    def fetch_audio(video_id, dest):
        dest.mkdir(parents=True, exist_ok=True)
        audio.append(video_id)
        (dest / "source.wav").write_bytes(b"RIFF audio")
        return dest / "source.wav"

    room = DeskStems(
        settings,
        StemCache(tmp_path / "c", 10**9),
        tmp_path / "l",
        audio=fetch_audio,
        send=send_through(client),
    )
    room.order = lambda: ["blocked"]
    room.request("blocked")
    room.poll()
    stems.status_of["blocked"] = StemStatus.FAILED  # YouTube refused the Desk
    room.poll()
    assert audio == ["blocked"]
    assert (tmp_path / "uploads" / "blocked.wav").read_bytes() == b"RIFF audio"


def test_the_song_on_is_done_here_when_the_desk_is_too_slow(desk, tmp_path, monkeypatch):
    client, _processor, _stems, _lyrics, settings, _app = desk
    local = FakeStems(tmp_path / "local")
    (tmp_path / "local").mkdir()
    room = DeskStems(
        settings, StemCache(tmp_path / "c", 10**9), tmp_path / "l", local, send=send_through(client)
    )
    room.order = lambda: ["slow"]
    room.request("slow")
    room.poll()
    assert local.requested == []
    monkeypatch.setattr(room_processing, "GIVE_UP", 0.0)
    time.sleep(0.01)
    room.poll()
    assert local.requested == ["slow"]


def test_the_room_thread_polls_on_its_own(desk, tmp_path):
    client, _processor, stems, _lyrics, settings, _app = desk
    room = DeskStems(
        settings, StemCache(tmp_path / "c", 10**9), tmp_path / "l", send=send_through(client)
    )
    room.order = lambda: ["auto"]
    try:
        room.start()
        room.request("auto")
        wait_for(lambda: "auto" in stems.requested, timeout=5)
        stems.finish("auto")
        wait_for(lambda: room.status("auto") == StemStatus.READY, timeout=10)
    finally:
        room.stop()
