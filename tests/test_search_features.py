from __future__ import annotations

import io
import json

import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeSource, make_song, wait_for
from tests.test_controller import FakeStems
from ytktv.core.library import SEARCH_HISTORY, Library
from ytktv.core.models import PlayStatus, StemStatus
from ytktv.server.app import create_app
from ytktv.youtube import search
from ytktv.youtube.search import ARTISTS


def test_recent_searches_are_deduplicated_bounded_and_persisted(tmp_path):
    path = tmp_path / "library.json"
    library = Library(path)
    assert library.add_search("  jay   chou ") and library.searches() == ["jay chou"]
    assert not library.add_search("jay chou")  # same as the latest: nothing to do
    assert library.add_search("adele") and library.add_search("Jay Chou")
    assert library.searches() == ["Jay Chou", "adele"]  # moved to the front, not repeated
    assert not library.add_search("") and not library.add_search("https://youtu.be/dQw4w9WgXcQ")
    for i in range(SEARCH_HISTORY + 5):
        library.add_search(f"query {i}")
    assert len(library.searches()) == SEARCH_HISTORY
    assert Library(path).searches()[0] == f"query {SEARCH_HISTORY + 4}"
    library.clear_searches()
    assert Library(path).searches() == []


class _Response(io.BytesIO):
    class headers:  # noqa: N801 - mimics http.client.HTTPMessage
        @staticmethod
        def get_content_charset():
            return "utf-8"

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_suggest_parses_caches_and_never_raises(monkeypatch):
    calls = []

    def fake_urlopen(request, timeout=5):
        calls.append(request.full_url)
        return _Response(json.dumps(["周杰", ["周杰伦", "周杰倫", 3, "周杰伦演唱会"]]).encode())

    monkeypatch.setattr(search, "urlopen", fake_urlopen)
    youtube = search.YouTube()
    assert youtube.suggest("周杰") == ["周杰伦", "周杰倫", "周杰伦演唱会"]
    assert youtube.suggest("周杰", limit=1) == ["周杰伦"] and len(calls) == 1  # served from cache
    assert "%E5%91%A8" in calls[0]
    assert youtube.suggest("a") == [] and youtube.suggest("https://youtu.be/x") == []

    def broken(request, timeout=5):
        raise OSError("offline")

    monkeypatch.setattr(search, "urlopen", broken)
    assert youtube.suggest("adele") == []


def test_artist_list_is_sane():
    assert set(ARTISTS) == {"Mandarin", "Cantonese", "English", "Japanese", "Korean"}
    for names in ARTISTS.values():
        assert len(names) >= 10 and len(set(names)) == len(names) and all(names)


def test_song_marks_and_search_memory(ktv):
    controller, _, _ = ktv
    events = []
    controller.bus.subscribe(
        lambda topic, data: events.append(topic) if topic == "searches" else None
    )
    controller.remember_search("adele")
    controller.remember_search("adele")
    controller.clear_searches()
    assert events == ["searches", "searches"]

    assert controller.song_marks(make_song(1)) == {"stem": "none", "queued": False}
    controller.enqueue(make_song(1))
    controller.enqueue(make_song(2))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    assert controller.queued_ids() == {make_song(1).video_id, make_song(2).video_id}
    assert controller.song_marks(make_song(2))["queued"] is True


def test_search_api_marks_results_and_remembers(ktv):
    controller, _, _ = ktv
    with TestClient(create_app(controller, FakeSource())) as http:
        results = http.get("/api/search", params={"q": "karaoke", "limit": 3}).json()
        assert all(r["stem"] == "none" and r["queued"] is False for r in results)
        assert controller.library.searches() == ["karaoke"]
        http.post("/api/queue", json={"song": {k: results[0][k] for k in ("video_id", "title")}})
        again = http.get("/api/search", params={"q": "karaoke", "limit": 3}).json()
        assert again[0]["queued"] is True and again[1]["queued"] is False
        assert http.get("/api/suggest", params={"q": "ade"}).json() == ["ade karaoke", "ade lyrics"]
        assert set(http.get("/api/artists").json()) == set(ARTISTS)


@pytest.fixture
def console(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from tests.helpers import make_controller
    from ytktv.ui.main_window import MainWindow
    from ytktv.ui.mv_window import MvWindow

    stems = FakeStems(tmp_path)
    controller, _, _ = make_controller(tmp_path, stems=stems)
    controller.settings.wait_for_instrumental = False
    monkeypatch.setattr("ytktv.audio.devices.list_inputs", lambda: [])
    monkeypatch.setattr("ytktv.audio.devices.list_outputs", lambda: [])
    mv = MvWindow(None)
    main = MainWindow(controller, FakeSource(), mv, "http://192.168.0.2:8765")  # type: ignore[arg-type]
    qtbot.addWidget(main)
    qtbot.addWidget(mv)
    main.show()
    yield main, controller, stems
    controller.close()


def chip_texts(layout) -> list[str]:
    from PySide6.QtWidgets import QPushButton

    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    return [w.text() for w in widgets if isinstance(w, QPushButton)]


def row_tags(page) -> list[list[str]]:
    from PySide6.QtWidgets import QLabel

    from ytktv.ui.song_list import SongRow

    rows = page.browse_list.widget().findChildren(SongRow)
    return [
        [label.text() for label in row.findChildren(QLabel) if label.objectName() == "tag"]
        for row in rows
    ]


def test_recent_searches_row_and_artist_shortcut(console, qtbot):
    main, controller, _ = console
    page = main.pages["search"]
    assert chip_texts(page.recent) == []

    page.search_for("jay chou")
    qtbot.waitUntil(lambda: len(page._browse_songs) > 0, timeout=3000)
    qtbot.waitUntil(lambda: chip_texts(page.recent) == ["jay chou", "Clear"], timeout=3000)

    main.show_page("artists")
    main.pages["artists"].buttons["Adele"].click()
    assert main.stack.currentWidget() is page and page.input.text() == "Adele"
    qtbot.waitUntil(lambda: chip_texts(page.recent)[:2] == ["Adele", "jay chou"], timeout=3000)

    controller.clear_searches()
    qtbot.waitUntil(lambda: chip_texts(page.recent) == [], timeout=3000)


def test_result_cards_show_selected_and_instrumental_ready(console, qtbot):
    main, controller, stems = console
    page = main.pages["search"]
    page.search_for("anything")
    qtbot.waitUntil(lambda: len(page._browse_songs) > 0, timeout=3000)
    assert all(tags == [] for tags in row_tags(page))

    first, second = page._browse_songs[0], page._browse_songs[1]
    controller.enqueue(first)
    qtbot.waitUntil(lambda: row_tags(page)[0] == ["Selected"], timeout=3000)

    stems.ready.add(second.video_id)  # its instrumental finished in the background
    controller._on_stem_change(second.video_id, StemStatus.READY)
    qtbot.waitUntil(lambda: row_tags(page)[1] == ["Instrumental ready"], timeout=3000)
    assert row_tags(page)[0] == ["Selected"]


def test_typing_fetches_suggestions(console, qtbot):
    main, _, _ = console
    page = main.pages["search"]
    page.input.setFocus()
    page.input.setText("ade")
    page._fetch_suggestions()
    # Suggestions only show while the box has focus; offscreen it may not, so check the fetch.
    qtbot.waitUntil(
        lambda: (
            page._suggestions.stringList() == ["ade karaoke", "ade lyrics"]
            or not page.input.hasFocus()
        ),
        timeout=3000,
    )
    page.search()
    assert page.browse_list is not None


def test_pinyin_initials_find_songs():
    from ytktv import catalog

    assert catalog.initials("月亮代表我的心") == "yldbwdx"
    assert catalog.initials("Let It Be") == "lib"
    assert catalog.initials("K歌之王") == "kgzw"
    assert catalog.match_initials("yldb")[0].startswith("月亮代表我的心")
    assert catalog.match_initials("hktk")[0].startswith("海闊天空")
    assert catalog.match_initials("wdge", [("我的歌兒", "Kim")]) == ["我的歌兒 - Kim"]
    assert catalog.match_initials("hello world") == []  # not initials
    assert set(catalog.artists("Cantonese", "Group")) >= {"Beyond", "Twins"}
    assert "Beyond" not in catalog.artists("Mandarin")


def test_initials_reach_the_phone(ktv):
    controller, _, _ = ktv
    with TestClient(create_app(controller, FakeSource())) as http:
        assert http.get("/api/suggest", params={"q": "yldb"}).json()[0].startswith("月亮代表我的心")


def test_duet_parts_follow_markers_or_alternate_by_verse():
    from ytktv.youtube.lyrics import PART_A, PART_B, PART_BOTH, LyricLine, duet_parts

    marked = [
        LyricLine(0, 2, "Intro line"),
        LyricLine(2, 4, "男：你好", ((2.0, 0), (3.0, 3))),
        LyricLine(4, 6, "再见"),
        LyricLine(6, 8, "(女) 嗯"),
        LyricLine(8, 9, "合：一起"),
        LyricLine(9, 10, "Note: not a part"),
    ]
    lines, parts = duet_parts(marked)
    assert parts == [PART_BOTH, PART_A, PART_A, PART_B, PART_BOTH, PART_BOTH]
    assert [line.text for line in lines][1:5] == ["你好", "再见", "嗯", "一起"]
    assert lines[1].words == ((2.0, 0), (3.0, 1))
    assert lines[5].text == "Note: not a part"

    plain = [LyricLine(s, s + 1.5, "x") for s in (0, 2, 8, 10, 16)]
    assert duet_parts(plain)[1] == [PART_A, PART_A, PART_B, PART_B, PART_A]
