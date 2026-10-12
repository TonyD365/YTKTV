from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402

from tests.helpers import FakeSource, make_song, wait_for  # noqa: E402
from ytktv.core.models import PlayStatus  # noqa: E402
from ytktv.ui.console_widgets import Fader, Knob  # noqa: E402
from ytktv.ui.main_window import MainWindow  # noqa: E402
from ytktv.ui.mv_window import MvWindow  # noqa: E402


@pytest.fixture
def window(qtbot, ktv, monkeypatch):
    controller, _, _ = ktv
    monkeypatch.setattr("ytktv.audio.devices.list_inputs", lambda: ["Test Mic"])
    monkeypatch.setattr("ytktv.audio.devices.list_outputs", lambda: ["Test Speakers"])
    mv = MvWindow(None)
    main = MainWindow(controller, FakeSource(), mv, "http://192.168.0.2:8765")  # type: ignore[arg-type]
    qtbot.addWidget(main)
    qtbot.addWidget(mv)
    main.show()
    return main, controller


def test_every_page_opens(window, qtbot):
    main, _ = window
    for key in main.pages:
        main.show_page(key)
        assert main.stack.currentWidget() is main.pages[key]
        qtbot.wait(10)


def test_console_follows_controller_state(window, qtbot):
    main, controller = window
    controller.enqueue(make_song(1), singer="Kim")
    controller.enqueue(make_song(2))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    qtbot.waitUntil(lambda: "Song 1" in main.now_title.text(), timeout=3000)
    assert "Kim" in main.now_title.text()
    assert main.next_title.text() == "Song 2"
    assert "(1)" in main._nav_buttons["queue"].text()

    controller.set_pitch(3)
    qtbot.waitUntil(lambda: main.key_readout.text() == "+3", timeout=3000)


def test_search_page_lists_results_and_select_enqueues(window, qtbot):
    main, controller = window
    page = main.pages["search"]
    page.input.setText("anything")
    page.search()
    qtbot.waitUntil(lambda: len(page._browse_songs) > 0, timeout=3000)
    first = page._browse_songs[0]
    controller.enqueue(first)
    wait_for(lambda: controller.current is not None)
    assert controller.current.song.video_id == first.video_id


def test_control_bar_buttons_drive_the_controller(window, qtbot):
    main, controller = window
    from ytktv.core.models import VocalMode

    qtbot.mouseClick(main.mode_buttons[VocalMode.INSTRUMENTAL], Qt.MouseButton.LeftButton)
    assert controller.vocal_mode == VocalMode.INSTRUMENTAL
    assert main.more_modes.text() == "More ▾" and not main.more_modes.isChecked()

    main.mode_actions[VocalMode.CENTER_CUT].trigger()  # picked from the More menu
    assert controller.vocal_mode == VocalMode.CENTER_CUT
    qtbot.waitUntil(lambda: main.more_modes.text() == "Vocal Cut", timeout=3000)
    assert main.more_modes.isChecked() and main.mode_actions[VocalMode.CENTER_CUT].isChecked()
    assert not main.mode_buttons[VocalMode.INSTRUMENTAL].isChecked()
    main.music_slider.setValue(33)
    assert controller.settings.music_volume == 33
    assert controller.settings.mic_volume == 80


def test_mixer_strip_edits_settings(window, qtbot):
    main, controller = window
    main.show_page("mixer")
    strip = main.mixer_page.strips[0]
    strip.fader.set_value(0.5, notify=True)
    strip.mute.setChecked(True)
    assert controller.settings.mics[0].fader == 0.5
    assert controller.settings.mics[0].mute is True
    assert strip.device.findText("Test Mic") >= 0

    main.mixer_page.mic_bus.faders[0].set_value(0.4, notify=True)
    assert controller.settings.mic_volume == 40
    assert controller.settings.music_volume == 80


def test_knob_drag_and_reset(qtbot):
    knob = Knob("GAIN", 0.0, 2.0, 1.0, "#25c26a")
    qtbot.addWidget(knob)
    knob.resize(64, 52)
    seen = []
    knob.valueChanged.connect(seen.append)
    qtbot.mousePress(knob, Qt.MouseButton.LeftButton, pos=QPoint(30, 40))
    qtbot.mouseMove(knob, QPoint(30, 5))
    qtbot.mouseRelease(knob, Qt.MouseButton.LeftButton, pos=QPoint(30, 5))
    assert seen and knob.value() > 1.0
    knob.set_value(99)
    assert knob.value() == 2.0
    qtbot.mouseDClick(knob, Qt.MouseButton.LeftButton)
    assert knob.value() == 1.0


def test_fader_click_jumps_and_clamps(qtbot):
    fader = Fader()
    qtbot.addWidget(fader)
    fader.resize(56, 210)
    qtbot.mouseClick(fader, Qt.MouseButton.LeftButton, pos=QPoint(30, 200))
    assert fader.value() < 0.1
    fader.set_value(5)
    assert fader.value() == 1.0


def test_mv_screen_shows_pause_and_play_symbols(window, qtbot):
    main, controller = window
    mv = main.mv_window
    mv.show()
    controller.enqueue(make_song(1))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    qtbot.waitUntil(lambda: mv._last_status == "playing", timeout=3000)
    assert not mv.badge.isVisible()  # nothing shown just because a song started

    controller.toggle_pause()
    qtbot.waitUntil(lambda: mv.badge.isVisible() and mv.badge.symbol == "pause", timeout=3000)
    qtbot.wait(1600)
    assert mv.badge.isVisible()  # the pause symbol stays for as long as it is paused

    controller.toggle_pause()
    qtbot.waitUntil(lambda: mv.badge.symbol == "play", timeout=3000)
    assert mv.badge.isVisible()
    qtbot.waitUntil(lambda: not mv.badge.isVisible(), timeout=4000)  # then it fades away

    controller.toggle_pause()
    qtbot.waitUntil(lambda: mv.badge.isVisible(), timeout=3000)
    controller.skip()  # the song ends while paused: the symbol must not linger
    qtbot.waitUntil(lambda: not mv.badge.isVisible(), timeout=4000)


def test_garbage_collection_moves_to_the_gui_thread(qtbot):
    import gc

    from PySide6.QtCore import QObject

    from ytktv.ui.support import collect_garbage_on_gui_thread

    owner = QObject()
    was_enabled = gc.isenabled()
    try:
        timer = collect_garbage_on_gui_thread(owner)
        assert not gc.isenabled()  # worker threads can no longer trigger a collection
        assert timer.isActive() and timer.interval() == 1000

        class Node:
            pass

        a, b = Node(), Node()
        a.other, b.other = b, a  # a cycle only the collector can free
        import weakref

        ref = weakref.ref(a)
        del a, b
        assert ref() is not None
        timer.timeout.emit()  # what the GUI thread does every second
        assert ref() is None
    finally:
        timer.stop()
        if was_enabled:
            gc.enable()


def test_lyrics_overlay_follows_playback_time(qtbot):
    from ytktv.ui.mv_overlays import LyricsOverlay

    overlay = LyricsOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(800, 200)
    assert not overlay.isVisible()
    overlay.set_lines(
        [
            {"start": 10.0, "end": 12.0, "text": "first"},
            {"start": 12.0, "end": 14.0, "text": "second"},
            {"start": 40.0, "end": 42.0, "text": "after the break"},
        ]
    )
    overlay.show()
    overlay.set_time(2.0)
    assert overlay._current() is None  # too early to show anything
    overlay.set_time(8.0)
    assert overlay._current() == (0, 0.0)  # shown ahead of time, not yet filling
    overlay.set_time(11.0)
    assert overlay._current() == (0, 0.5)
    overlay.set_time(13.5)
    index, progress = overlay._current()
    assert index == 1 and 0.7 < progress < 0.8
    overlay.set_time(20.0)
    assert overlay._current() is None  # instrumental break
    overlay.grab()  # painting must not fail in any of these states
    overlay.set_time(41.0)
    overlay.grab()
    overlay.set_lines([])
    assert not overlay.isVisible() and not overlay.has_lines()


def test_lyrics_overlay_colour_follows_word_timing(qtbot):
    from ytktv.ui.mv_overlays import LyricsOverlay

    overlay = LyricsOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(800, 200)
    # "la" is sung at once, then nothing until "di" eight seconds later.
    overlay.set_lines(
        [{"start": 10.0, "end": 20.0, "text": "la di", "words": [[10.0, 0], [18.0, 3]]}]
    )
    overlay.show()
    overlay.set_time(14.0)
    index, waiting = overlay._current()
    assert index == 0 and 0.3 < waiting < 0.7  # "la" is done, "di" has not started
    overlay.set_time(17.5)
    assert overlay._current() == (0, waiting)  # an even fill would have moved on
    overlay.set_time(19.9)
    assert overlay._current()[1] > waiting
    overlay.grab()


def test_lyrics_overlay_draws_lines_once_and_ahead_of_time(qtbot, monkeypatch):
    """Drawing a line is slow: it happens once, in steps, before the line is needed."""
    from ytktv.ui import mv_overlays

    built = []
    sprite = mv_overlays._TextSprite

    def counting(font, text, *args, **kwargs):
        built.append(text)
        return sprite(font, text, *args, **kwargs)

    monkeypatch.setattr(mv_overlays, "_TextSprite", counting)
    overlay = mv_overlays.LyricsOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(800, 200)
    overlay.set_lines(
        [
            {"start": 0.0, "end": 4.0, "text": "first"},
            {"start": 4.0, "end": 8.0, "text": "second"},
            {"start": 8.0, "end": 12.0, "text": "third"},
        ]
    )
    overlay.show()
    for step in range(100):  # frames while the first line is sung
        overlay.set_time(0.5 + step * 0.03)
        overlay.grab()
    # The first line (white, sung, preview of the second) and already the second one.
    assert sorted(built) == ["first", "first", "second", "second", "second", "third"]
    assert overlay._job is None and sorted(overlay._art) == [0, 1]

    filled = overlay.grab().toImage()
    overlay.set_time(0.0)
    assert overlay.grab().toImage() != filled  # the sung part still follows the time

    built.clear()
    overlay._art.pop(0)  # as when playback moves on
    overlay._position = 5.0
    overlay.grab()
    assert built == []  # changing to the second line needs no drawing at all

    overlay.resize(1000, 250)  # a different screen size needs the lines drawn again
    overlay.grab()
    assert sorted(built) == ["second", "second", "third"]


def test_lyrics_overlay_finishes_a_line_when_playback_jumps_to_it(qtbot):
    from ytktv.ui.mv_overlays import LyricsOverlay

    overlay = LyricsOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(800, 200)
    overlay.set_lines(
        [{"start": i * 4.0, "end": i * 4.0 + 4.0, "text": f"line {i}"} for i in range(6)]
    )
    overlay.show()
    overlay.set_time(1.0)  # one step of line 0 done, far from finished
    assert 0 not in overlay._art
    overlay.set_time(17.0)  # a seek to line 4
    empty = overlay.grab().toImage()
    empty.fill(0)
    assert overlay.grab().toImage() != empty and 4 in overlay._art
    assert all(index in (4, 5) for index in overlay._art)  # older lines are dropped


def test_lyrics_overlay_survives_dropping_unfinished_drawing(qtbot):
    """A line half drawn when playback jumps away is discarded without harm."""
    import gc

    from ytktv.ui.mv_overlays import LyricsOverlay

    overlay = LyricsOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(800, 200)
    overlay.set_lines(
        [{"start": i * 4.0, "end": i * 4.0 + 4.0, "text": f"line {i}"} for i in range(30)]
    )
    overlay.show()
    for jump in range(60):
        for step in range(jump % 13):  # stop at every possible point in the drawing
            overlay.set_time((jump % 28) * 4.0 + 0.01 * step)
        overlay.set_time(((jump + 9) % 28) * 4.0)
        gc.collect()
    overlay.set_lines([])
    gc.collect()
    overlay.grab()


def test_danmaku_flies_across_and_is_removed(qtbot):
    from ytktv.ui.mv_overlays import DANMAKU_LIMIT, DANMAKU_SECONDS, DanmakuOverlay

    overlay = DanmakuOverlay()
    qtbot.addWidget(overlay)
    overlay.resize(1000, 300)
    assert not overlay.active()
    overlay.add("hello")
    overlay.add("world")
    assert overlay.active() and overlay.isVisible()
    assert overlay._items[0]["lane"] != overlay._items[1]["lane"]  # no overlap at the edge
    start = overlay._items[0]["x"]
    overlay.advance(1.0)
    assert overlay._items[0]["x"] < start
    overlay.grab()
    overlay.advance(DANMAKU_SECONDS + 1)
    assert not overlay.active() and not overlay.isVisible()
    for i in range(DANMAKU_LIMIT + 10):
        overlay.add(f"flood {i}")
    assert len(overlay._items) == DANMAKU_LIMIT


def test_light_show_follows_the_music():
    from ytktv.ui.mv_overlays import LightShow

    show = LightShow()
    assert all(intensity == 0.0 for intensity, _ in show.step(0.0, 0.033).values())
    loud = show.step(0.8, 0.033)
    assert set(loud) == {"left", "right", "top", "bottom"}
    assert all(0.5 < intensity <= 1.0 for intensity, _ in loud.values())
    assert len({round(hue % 1.0, 3) for _, hue in loud.values()}) == 4  # each side its own colour
    for _ in range(200):  # the music stops: lights fade out rather than cut
        faded = show.step(0.0, 0.033)
    assert all(intensity == 0.0 for intensity, _ in faded.values())


def test_mv_window_shows_lyrics_and_danmaku_and_console_controls_work(window, qtbot):
    main, controller = window
    mv = main.mv_window
    mv.show()
    controller.enqueue(make_song(1))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    qtbot.waitUntil(lambda: mv._playing, timeout=3000)

    controller.bus.emit(
        "lyrics",
        {"id": controller.current.id, "lines": [{"start": 0.0, "end": 60.0, "text": "sing"}]},
    )
    qtbot.waitUntil(lambda: mv.lyrics.has_lines() and mv.lyrics.isVisible(), timeout=3000)
    assert mv._animator.isActive()

    main.danmaku_input.setText("nice!")
    main._send_danmaku()
    qtbot.waitUntil(lambda: mv.danmaku.active(), timeout=3000)
    assert main.danmaku_input.text() == ""

    main.guide_slider.setValue(40)
    assert controller.settings.guide_vocal == 40
    assert main.lights_button.isChecked()
    main.lights_button.click()
    assert controller.settings.lights is False

    controller.skip()  # song gone: lyrics are cleared with it
    qtbot.waitUntil(lambda: not mv.lyrics.has_lines(), timeout=4000)


def test_settings_offers_install_now_when_an_update_is_downloaded(
    window, qtbot, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from ytktv import updater
    from ytktv.ui.update_manager import UpdateManager

    main, controller = window
    page = main.settings_page
    main.show_page("settings")
    assert not page.install_button.isVisible()

    manager = UpdateManager(controller, main)
    manager._timer.stop()
    manager.ready.connect(page.set_update_ready)
    page.install_update.connect(manager.install_now)
    installer = tmp_path / "YTKTV-9.9.9-macos-universal.pkg"
    installer.write_bytes(b"pkg")
    manager._installer = installer
    manager._info = updater.UpdateInfo("9.9.9", "v9.9.9", installer.name, "", "", "", "")
    manager.ready.emit(True)
    assert page.install_button.isVisible()

    installed = []
    monkeypatch.setattr(updater, "install_update", installed.append)
    monkeypatch.setattr(
        "ytktv.ui.update_manager.QApplication.quit", lambda: installed.append("quit")
    )
    shown = []

    def fake_exec(box):
        shown.append(box.informativeText())
        # Accept on the second showing only.
        box.clickedButton = lambda: box.buttons()[0] if len(shown) > 1 else box.buttons()[1]
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)

    manager._declined = True  # "Later" was chosen earlier this session
    page.install_button.click()  # the button still works, and this time says Later again
    assert len(shown) == 1 and installed == []
    assert "will stop" not in shown[0]  # nothing is playing

    controller.enqueue(make_song(1))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    page.install_button.click()
    assert "will stop" in shown[1]  # warns before interrupting a song
    assert installed == [installer, "quit"]


def test_score_toggle_live_score_and_score_card(window, qtbot):
    main, controller = window
    mv = main.mv_window
    mv.show()
    assert main.score_button.isChecked()
    main.score_button.click()
    assert controller.settings.scoring is False
    main.score_button.click()
    assert controller.settings.scoring is True

    assert not mv.live_score.isVisible()
    controller.bus.emit("position", {"position": 30.0, "duration": 200.0, "score": 87})
    qtbot.waitUntil(
        lambda: mv.live_score.isVisible() and "87" in mv.live_score.text(), timeout=3000
    )
    controller.bus.emit("position", {"position": 31.0, "duration": 200.0, "score": None})
    qtbot.waitUntil(lambda: not mv.live_score.isVisible(), timeout=3000)

    score = {"points": 92, "grade": "Amazing!", "title": "Song 1", "singer": "Ann"}
    controller.bus.emit("score", score)
    qtbot.waitUntil(lambda: mv.score_card.isVisible(), timeout=3000)
    assert mv.score_card._points == 92 and "Ann" in mv.score_card._caption
    mv.score_card.grab()  # painting must not fail
    assert "92" in main.toast.text()


def test_queue_rows_are_reordered_by_dragging_the_grip(window, qtbot):
    main, controller = window
    for i in range(1, 6):
        controller.enqueue(make_song(i))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    main.show_page("queue")
    song_list = main.pages["queue"].list
    qtbot.waitUntil(lambda: len(song_list._rows) == 4, timeout=3000)
    qtbot.wait(50)  # let the rows take their places

    def titles():
        return [item.song.title for item in controller.queue.snapshot()]

    def middle(row):
        return row.mapToGlobal(row.rect().center())

    assert titles() == ["Song 2", "Song 3", "Song 4", "Song 5"]
    rows = list(song_list._rows)
    below_last = rows[3].mapToGlobal(rows[3].rect().bottomLeft()) + QPoint(20, 30)

    song_list.drag_start(rows[0])  # the first song to the very end
    song_list.drag_to(below_last)
    assert song_list._marker.isVisible()
    song_list.drag_end(below_last)
    assert titles() == ["Song 3", "Song 4", "Song 5", "Song 2"]
    assert not song_list._marker.isVisible()

    qtbot.waitUntil(lambda: song_list._rows and song_list._rows[0] is not rows[0], timeout=3000)
    qtbot.wait(50)
    rows = list(song_list._rows)
    above_first = rows[0].mapToGlobal(rows[0].rect().topLeft()) + QPoint(20, 2)
    song_list.drag_start(rows[2])  # "Song 5" to the top
    song_list.drag_end(above_first)
    assert titles() == ["Song 5", "Song 3", "Song 4", "Song 2"]

    qtbot.waitUntil(lambda: song_list._rows and song_list._rows[0] is not rows[0], timeout=3000)
    qtbot.wait(50)
    rows = list(song_list._rows)
    song_list.drag_start(rows[1])  # dropped where it already is: nothing moves
    song_list.drag_end(middle(rows[1]))
    assert titles() == ["Song 5", "Song 3", "Song 4", "Song 2"]


def test_pitch_lane_shows_the_tune_and_the_voice_in_its_octave(qtbot):
    from ytktv.ui.mv_overlays import PitchLane

    lane = PitchLane()
    qtbot.addWidget(lane)
    lane.resize(600, 120)
    assert not lane.has_melody()
    lane.set_melody(
        {"hop": 0.05, "notes": [60.0] * 20 + [None] * 10 + [64.2] * 20, "transpose": 2.0}
    )
    assert lane.has_melody()
    assert lane._bars == [(0.0, 1.0, 60.0), (1.5, 2.5, 64.0)]  # one bar per held note

    lane.add_voice(0.5, 50.1)  # an octave below the tune (62 after the key change): on it
    lane.add_voice(0.6, 77.0)  # three semitones off, whatever the octave
    lane.add_voice(0.7, None)  # nothing heard: nothing drawn
    assert [(round(note, 1), on_it) for _t, note, on_it in lane._voice] == [
        (62.1, True),
        (65.0, False),
    ]
    lane.add_voice(1.25, 70.0)  # in the gap between two notes: shown, but cannot be "on it"
    assert lane._voice[-1][2] is False

    lane.show()
    lane.set_time(0.6)
    empty = lane.grab().toImage()
    lane.set_time(1.9)
    assert lane.grab().toImage() != empty  # the lane scrolls with the song
    lane.set_melody(None)
    assert not lane.has_melody() and not lane.isVisible() and not lane._voice


def test_score_card_grows_for_the_leaderboard(window, qtbot):
    main, _ = window
    mv = main.mv_window
    mv.resize(1280, 720)
    mv.show_score({"points": 80, "grade": "Great!", "title": "Song 1", "singer": ""})
    alone = mv.score_card.height()
    assert mv.score_card.board_rows() == 0
    board = [
        {"rank": 1, "points": 91, "title": "Song 2", "singer": "Ann"},
        {"rank": 2, "points": 80, "title": "Song 1", "singer": ""},
    ]
    mv.show_score(
        {
            "points": 80,
            "grade": "Great!",
            "title": "Song 1",
            "singer": "",
            "rank": 2,
            "board": board,
        }
    )
    assert mv.score_card.board_rows() == 2 and mv.score_card.height() > alone
    mv.score_card.grab()
