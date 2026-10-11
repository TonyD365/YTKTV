from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeSource, make_song, wait_for
from ytktv.core.library import PLAYLIST_NAME_LENGTH, Library
from ytktv.core.models import PlayStatus
from ytktv.server.app import create_app
from ytktv.youtube import search
from ytktv.youtube.parse import extract_playlist_id


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "https://www.youtube.com/playlist?list=PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj",
            "PLMC9KNkIncKtPzgY-5rmhvj7fax8fdxoj",
        ),
        (
            "https://www.youtube.com/watch?v=JGwWNGJdvx8&list=PLabcdefghij123&index=2",
            "PLabcdefghij123",
        ),
        ("PLabcdefghij123", "PLabcdefghij123"),
        ("https://youtu.be/JGwWNGJdvx8", None),
        ("just some words", None),
    ],
)
def test_extract_playlist_id(text, expected):
    assert extract_playlist_id(text) == expected


def test_library_playlists_are_cleaned_deduplicated_and_persisted(tmp_path):
    path = tmp_path / "library.json"
    library = Library(path)
    name = library.create_playlist(
        "  Friday   night / hits ", [make_song(1), make_song(2), make_song(1)]
    )
    assert name == "Friday night hits"
    assert [s.title for s in library.playlist(name)] == ["Song 1", "Song 2"]

    with pytest.raises(ValueError, match="already"):
        library.create_playlist("Friday night hits")
    with pytest.raises(ValueError, match="needs a name"):
        library.create_playlist("  /  ")
    assert library.unique_playlist_name("Friday night hits") == "Friday night hits (2)"
    assert len(library.unique_playlist_name("x" * 200)) == PLAYLIST_NAME_LENGTH

    assert library.add_to_playlist(name, make_song(3)) is True
    assert library.add_to_playlist(name, make_song(3)) is False  # already there
    assert library.add_to_playlist("nope", make_song(3)) is False
    assert library.remove_from_playlist(name, make_song(1).video_id) is True
    assert library.remove_from_playlist(name, make_song(1).video_id) is False
    library.create_playlist("Second")

    reloaded = Library(path)
    assert reloaded.playlist_names() == ["Friday night hits", "Second"]
    assert [s.title for s in reloaded.playlist(name)] == ["Song 2", "Song 3"]
    assert reloaded.delete_playlist("Second") and not reloaded.delete_playlist("Second")
    assert reloaded.playlist("Second") is None


def test_old_library_files_without_playlists_still_load(tmp_path):
    path = tmp_path / "library.json"
    path.write_text('{"favorites": [], "history": []}')
    assert Library(path).playlist_names() == []


def test_youtube_playlist_import_parses_entries(monkeypatch):
    requested = {}

    class FakeYdl:
        def __init__(self, options):
            requested.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def extract_info(self, url, download=False):
            requested["url"] = url
            entries = [{"id": f"{i:011d}", "title": f"Track {i}"} for i in range(5)]
            entries.append({"id": "UCchannelchannelchannel1", "title": "not a video"})
            return {"title": "Road trip", "entries": entries}

    monkeypatch.setattr(search, "_ydl", lambda **options: FakeYdl(options))
    title, songs = search.YouTube().playlist(
        "https://www.youtube.com/watch?v=x&list=PLabcdefghij123", limit=3
    )
    assert title == "Road trip" and [s.title for s in songs] == ["Track 0", "Track 1", "Track 2"]
    assert requested["url"].endswith("list=PLabcdefghij123") and requested["playlistend"] == 3
    with pytest.raises(ValueError, match="not a YouTube playlist"):
        search.YouTube().playlist("https://youtu.be/JGwWNGJdvx8")


def test_enqueue_many_starts_playback_and_queues_the_rest(ktv):
    controller, _, _ = ktv
    toasts = []
    controller.bus.subscribe(
        lambda topic, data: toasts.append(data["message"]) if topic == "toast" else None
    )
    assert controller.enqueue_many([]) == 0
    assert controller.enqueue_many([make_song(i) for i in range(1, 6)], singer="Ann") == 5
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    state = controller.state()
    assert state["current"]["song"]["title"] == "Song 1" and state["current"]["singer"] == "Ann"
    assert [i["song"]["title"] for i in state["queue"]] == ["Song 2", "Song 3", "Song 4", "Song 5"]
    assert toasts == ["Added 5 songs"]  # one message, not five


def test_playlist_flow_through_the_controller(ktv):
    controller, _, resolver = ktv
    events = []
    controller.bus.subscribe(
        lambda topic, data: events.append(topic) if topic == "playlists" else None
    )

    name = controller.create_playlist("Party")
    assert controller.add_to_playlist(name, make_song(1)) and controller.add_to_playlist(
        name, make_song(2)
    )
    assert not controller.add_to_playlist(name, make_song(1))
    assert controller.playlists() == [{"name": "Party", "count": 2}]

    with pytest.raises(ValueError, match="nothing in the queue"):
        controller.save_queue_as_playlist("Empty")
    assert controller.enqueue_playlist("Party") == 2
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    controller.enqueue(make_song(9))
    saved = controller.save_queue_as_playlist("Tonight")
    assert [s.title for s in controller.library.playlist(saved)] == ["Song 1", "Song 2", "Song 9"]

    with pytest.raises(KeyError):
        controller.enqueue_playlist("Nope")
    with pytest.raises(ValueError, match="not available"):
        controller.import_playlist("https://www.youtube.com/playlist?list=PLabcdefghij123")

    resolver.playlist = lambda url: ("Party", [make_song(20), make_song(21)])
    imported = controller.import_playlist("https://www.youtube.com/playlist?list=PLabcdefghij123")
    assert imported == "Party (2)"  # the name was taken
    assert len(controller.library.playlist(imported)) == 2

    assert controller.remove_from_playlist("Party", make_song(1).video_id)
    assert controller.delete_playlist("Tonight") and not controller.delete_playlist("Tonight")
    assert len(events) >= 6


def test_shuffle_play_keeps_every_song(ktv, monkeypatch):
    controller, _, _ = ktv
    monkeypatch.setattr("random.shuffle", lambda items: items.reverse())
    controller.create_playlist("Mix", [make_song(i) for i in range(1, 5)])
    controller.enqueue_playlist("Mix", shuffle=True)
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    state = controller.state()
    titles = [state["current"]["song"]["title"]] + [i["song"]["title"] for i in state["queue"]]
    assert titles == ["Song 4", "Song 3", "Song 2", "Song 1"]
    assert [s.title for s in controller.library.playlist("Mix")] == [
        "Song 1",
        "Song 2",
        "Song 3",
        "Song 4",
    ]


@pytest.fixture
def client(ktv):
    controller, _, resolver = ktv
    with TestClient(create_app(controller, FakeSource())) as http:
        yield http, controller, resolver


def test_playlists_over_http(client):
    http, controller, resolver = client
    song = make_song(1).to_dict()
    assert http.get("/api/playlists").json() == []
    assert http.post("/api/playlists", json={"name": "Road trip"}).json() == {"name": "Road trip"}
    assert http.post("/api/playlists", json={"name": "Road trip"}).status_code == 400
    assert http.post("/api/playlists", json={"name": "  "}).status_code == 400
    assert http.post("/api/playlists", json={"name": "Q", "from_queue": True}).status_code == 400

    assert http.post("/api/playlists/Road%20trip/songs", json=song).json() == {"added": True}
    assert http.post("/api/playlists/Road%20trip/songs", json=song).json() == {"added": False}
    assert http.post("/api/playlists/Nope/songs", json=song).status_code == 404
    assert [s["title"] for s in http.get("/api/playlists/Road%20trip").json()] == ["Song 1"]
    assert http.get("/api/playlists/Nope").status_code == 404
    assert http.get("/api/playlists").json() == [{"name": "Road trip", "count": 1}]

    assert http.post("/api/playlists/Road%20trip/enqueue", json={"singer": "Bo"}).json() == {
        "added": 1
    }
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    assert controller.current.singer == "Bo"
    assert http.post("/api/playlists/Nope/enqueue", json={}).status_code == 404
    assert http.post("/api/playlists", json={"name": "Saved", "from_queue": True}).json() == {
        "name": "Saved"
    }

    assert http.post("/api/playlists/import", json={"url": "https://youtu.be/x"}).status_code == 400
    resolver.playlist = lambda url: ("Imported hits", [make_song(5), make_song(6)])
    imported = http.post(
        "/api/playlists/import",
        json={"url": "https://www.youtube.com/playlist?list=PLabcdefghij123"},
    )
    assert imported.json() == {"name": "Imported hits"}

    def broken(url):
        raise RuntimeError("network down")

    resolver.playlist = broken
    assert http.post("/api/playlists/import", json={"url": "PLabcdefghij123"}).status_code == 502

    video_id = make_song(1).video_id
    assert http.delete(f"/api/playlists/Road%20trip/songs/{video_id}").json() == {"ok": True}
    assert http.delete(f"/api/playlists/Road%20trip/songs/{video_id}").status_code == 404
    assert http.delete("/api/playlists/Road%20trip").json() == {"ok": True}
    assert http.delete("/api/playlists/Road%20trip").status_code == 404


def test_playlists_page(qtbot, ktv, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QMessageBox

    from ytktv.ui import pages
    from ytktv.ui.main_window import MainWindow
    from ytktv.ui.mv_window import MvWindow

    controller, _, resolver = ktv
    monkeypatch.setattr("ytktv.audio.devices.list_inputs", lambda: [])
    monkeypatch.setattr("ytktv.audio.devices.list_outputs", lambda: [])
    mv = MvWindow(None)
    main = MainWindow(controller, FakeSource(), mv, "http://192.168.0.2:8765")  # type: ignore[arg-type]
    qtbot.addWidget(main)
    qtbot.addWidget(mv)
    main.show_page("playlists")
    page = main.pages["playlists"]
    assert page.selected() == ""

    answers = iter(
        ["Karaoke night", "https://www.youtube.com/playlist?list=PLabcdefghij123", "Tonight"]
    )
    monkeypatch.setattr(pages, "ask_text", lambda *args, **kwargs: next(answers))
    page._new()
    qtbot.waitUntil(lambda: page.selected() == "Karaoke night", timeout=3000)

    controller.add_to_playlist("Karaoke night", make_song(1))
    controller.add_to_playlist("Karaoke night", make_song(2))
    qtbot.waitUntil(lambda: "(2)" in page.picker.currentText(), timeout=3000)

    resolver.playlist = lambda url: ("From YouTube", [make_song(7), make_song(8), make_song(9)])
    page._import()
    qtbot.waitUntil(lambda: page.selected() == "From YouTube", timeout=3000)
    assert "(3)" in page.picker.currentText()

    page._enqueue(False)
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    assert controller.current.song.title == "Song 7" and len(controller.queue) == 2

    main.pages["queue"]._save_as_playlist()
    qtbot.waitUntil(lambda: controller.library.playlist("Tonight") is not None, timeout=3000)
    qtbot.wait(50)
    assert page.selected() == "From YouTube"  # a refresh must not jump to another playlist

    monkeypatch.setattr(
        QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes
    )
    page._delete()
    qtbot.waitUntil(lambda: "From YouTube" not in controller.library.playlist_names(), timeout=3000)
    assert page.selected() in ("Karaoke night", "Tonight")
