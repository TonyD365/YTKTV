from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from tests.helpers import FakeSource  # noqa: E402
from ytktv.config import Settings  # noqa: E402
from ytktv.ui.main_window import MainWindow  # noqa: E402
from ytktv.ui.mv_overlays import LyricsOverlay, LyricsStyle  # noqa: E402
from ytktv.ui.mv_window import MvWindow  # noqa: E402

LINES = [
    {"start": 0.0, "end": 4.0, "text": "a rather long line of lyrics that keeps going on and on"},
    {"start": 4.0, "end": 8.0, "text": "next"},
]


def test_default_settings_give_the_original_look():
    style = LyricsStyle.from_settings(Settings())
    assert style == LyricsStyle()
    assert style.waiting == "#ffffff" and style.sung == ("#ff3d9a", "#2ee6ff")
    assert style.size == 1.0 and style.outline == 1.0 and not style.high_contrast


def test_custom_and_unknown_settings():
    settings = Settings(
        lyrics_colours="Custom", lyrics_waiting_colour="#00ff00", lyrics_sung_colour="#123456"
    )
    style = LyricsStyle.from_settings(settings)
    assert style.waiting == "#00ff00" and style.sung == ("#123456", "#123456")
    odd = LyricsStyle.from_settings(Settings(lyrics_size="Huge", lyrics_colours="Nope"))
    assert odd == LyricsStyle()
    settings = Settings.from_dict({"lyrics_size": "Large", "lyrics_high_contrast": True})
    assert LyricsStyle.from_settings(settings).size == 1.25


@pytest.mark.parametrize("contrast", [False, True])
@pytest.mark.parametrize("size", [0.8, 1.0, 1.5])
def test_styles_draw_and_long_lines_fit(qtbot, size, contrast):
    overlay = LyricsOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(800, int(200 * max(1.0, size)))
    overlay.set_style(LyricsStyle(size=size, outline=1.8, high_contrast=contrast))
    overlay.set_lines(LINES)
    overlay.show()
    overlay.set_time(2.0)
    assert not overlay.grab().toImage().isNull()
    art = overlay._ready(0)
    assert art.x >= 0 and art.line.width <= overlay.width()  # shrunk to fit


def test_style_changes_the_picture(qtbot):
    overlay = LyricsOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(800, 200)
    overlay.set_lines(LINES)
    overlay.show()
    overlay.set_time(2.0)
    before = overlay.grab().toImage()
    overlay.set_style(LyricsStyle(sung=("#00ff00", "#00ff00")))
    assert overlay.grab().toImage() != before


def test_large_lyrics_push_the_pitch_guide_up(qtbot):
    mv = MvWindow(None)
    qtbot.addWidget(mv)
    mv.resize(1280, 720)
    mv._place_lyrics()
    normal = mv.lyrics.geometry()
    assert normal.y() == int(720 * 0.74) and mv.pitch_lane.geometry().y() == int(720 * 0.57)
    mv.set_lyrics_style(LyricsStyle(size=1.5))
    lyrics, lane = mv.lyrics.geometry(), mv.pitch_lane.geometry()
    assert lyrics.height() > normal.height()
    assert lyrics.bottom() <= 720
    assert lane.bottom() < lyrics.top()  # no overlap with the pitch guide


def test_settings_page_saves_and_previews(qtbot, ktv):
    controller, _, _ = ktv
    mv = MvWindow(None)
    main = MainWindow(controller, FakeSource(), mv, "http://192.168.0.2:8765")  # type: ignore[arg-type]
    qtbot.addWidget(main)
    qtbot.addWidget(mv)
    page = main.settings_page
    assert page.lyrics_size.currentText() == "Medium"
    assert not page.lyrics_sung_button.isEnabled()
    page.lyrics_size.setCurrentText("Extra large")
    page.lyrics_colours.setCurrentText("Gold")
    page.lyrics_contrast.setChecked(True)
    settings = controller.settings
    assert settings.lyrics_size == "Extra large" and settings.lyrics_colours == "Gold"
    assert settings.lyrics_high_contrast
    assert mv.lyrics.lyrics_style() == page.lyrics_preview.lyrics_style()
    assert mv.lyrics.lyrics_style().size == 1.5 and mv.lyrics.lyrics_style().high_contrast
    page.lyrics_colours.setCurrentText("Custom")
    assert page.lyrics_sung_button.isEnabled()
    page.resize(900, 2000)
    page.lyrics_preview_frame.grab()  # the preview paints (look check)
