from __future__ import annotations

from fastapi.testclient import TestClient

from tests.helpers import FakeSource
from ytktv.core.recap import SessionRecap, lines, page
from ytktv.server.app import create_app


def _sung(recap: SessionRecap) -> None:
    recap.song("Song A", "Amy", 200)
    recap.song("Song B", "Bob", 180)
    recap.song("Song C", "Amy", 220)
    recap.score(88, "Song A", "Amy")
    recap.score(93, "Song B", "Bob", duet=True)


def test_summary_counts_songs_singers_and_scores():
    recap = SessionRecap()
    _sung(recap)
    summary = recap.finish()
    assert summary is not None
    assert summary["songs"] == 3
    assert summary["seconds"] == 600
    assert summary["top_singer"] == {"name": "Amy", "songs": 2}
    assert summary["best_score"]["points"] == 93
    assert summary["best_duet"]["title"] == "Song B"
    labels = [label for label, _ in lines(summary)]
    assert labels == ["Songs sung", "Time singing", "Sang the most", "Highest score", "Best duet"]


def test_nothing_sung_means_no_recap():
    assert SessionRecap().finish() is None


def test_token_is_checked_and_expires_with_the_next_session():
    recap = SessionRecap()
    _sung(recap)
    token = recap.finish()["token"]
    assert len(token) >= 32
    assert recap.lookup(token) is not None
    assert recap.lookup("wrong") is None
    recap.start()
    assert recap.lookup(token) is None


def test_page_escapes_titles():
    recap = SessionRecap()
    recap.song("<script>x</script>", "", 60)
    html = page(recap.finish())
    assert "<script>x" not in html
    assert "Recordings" not in html  # no recordings, no download section


def test_closing_the_room_makes_a_recap_served_to_phones(ktv):
    controller, _, _ = ktv
    controller.recap.song("Song A", "Amy", 120)
    controller.close_room()
    summary = controller.last_recap
    assert summary is not None
    with TestClient(create_app(controller, FakeSource())) as client:
        ok = client.get(f"/recap/{summary['token']}")
        assert ok.status_code == 200 and "Song A" in ok.text
        assert client.get("/recap/not-the-token").status_code == 404
        controller.open_room()
        assert controller.last_recap is None
        assert client.get(f"/recap/{summary['token']}").status_code == 404


def test_recap_setting_turns_it_off(ktv):
    controller, _, _ = ktv
    controller.settings.session_recap = False
    controller.recap.song("Song A", "Amy", 120)
    controller.close_room()
    assert controller.last_recap is None


def test_recap_card_renders_offscreen(qtbot):
    from PySide6.QtWidgets import QWidget

    from ytktv.ui.recap_card import RecapCard

    recap = SessionRecap()
    _sung(recap)
    parent = QWidget()
    parent.resize(1280, 720)
    card = RecapCard(parent, recap.finish(), "http://192.168.1.2:8765/recap/abc")
    card.place()
    assert len(card.rows) == 5
    assert not card.qr.pixmap().isNull()
    parent.deleteLater()
