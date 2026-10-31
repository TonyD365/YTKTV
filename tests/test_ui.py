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
    main.level_keys["music_volume"][0].click()  # one segment quieter: 80 -> 75
    assert controller.settings.music_volume == 75
    assert controller.settings.mic_volume == 80
    assert main.level_hud.isVisible() and main.level_hud.kind == "music_volume"
    assert main.level_hud.value == 75
    assert main.mv_window.level_hud.value == 75  # shown on the MV screen too


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

    party = main.pages["party"]
    party.danmaku_input.setText("nice!")
    party.send()
    qtbot.waitUntil(lambda: mv.danmaku.active(), timeout=3000)
    assert party.danmaku_input.text() == ""

    for _ in range(6):
        main.level_keys["guide_vocal"][1].click()
    assert controller.settings.guide_vocal == 38  # six of sixteen segments
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


def test_setup_wizard_applies_each_choice_and_does_not_come_back(window, qtbot, monkeypatch):
    from ytktv.ui.setup_wizard import OFF, SetupWizard

    main, controller = window
    monkeypatch.setattr("ytktv.audio.devices.list_inputs", lambda: ["Test Mic", "USB Mic"])
    monkeypatch.setattr("ytktv.audio.devices.list_outputs", lambda: ["Test Speakers", "HDMI"])
    placed = []
    wizard = SetupWizard(controller, lambda: placed.append(1), main)
    qtbot.addWidget(wizard)
    assert controller.settings.setup_done is False
    assert wizard.step_label.text().startswith("STEP 1 OF 3") and not wizard.back.isEnabled()

    wizard.output.setCurrentText("HDMI")
    wizard._output_chosen(0)
    assert controller.settings.output_device == "HDMI"

    wizard.next.click()
    assert wizard.step_label.text().startswith("STEP 2 OF 3") and wizard.back.isEnabled()
    assert wizard.screen_combo.itemData(0) == -1 and wizard.screen_combo.count() >= 2
    wizard.screen_combo.setCurrentIndex(1)
    wizard._screen_chosen(1)
    assert controller.settings.mv_screen == 0 and placed == [1]

    wizard.next.click()
    assert wizard.next.text() == "Finish" and wizard._meter.isActive()
    wizard.mic.setCurrentText("USB Mic")
    wizard._mic_chosen(0)
    strip = controller.settings.mics[0]
    assert strip.enabled and strip.device == "USB Mic"
    wizard._show_level()
    assert "not running" in wizard.heard.text()  # no sound card in the tests
    wizard.mic.setCurrentText(OFF)
    wizard._mic_chosen(0)
    assert not strip.enabled and strip.device == "USB Mic"  # switched off, device remembered
    wizard._show_level()
    assert wizard.heard.text() == "Channel 1 is off."

    wizard.back.click()
    assert wizard.step_label.text().startswith("STEP 2 OF 3") and not wizard._meter.isActive()
    wizard.go(2)
    wizard.next.click()
    assert controller.settings.setup_done is True and not wizard.isVisible()


def test_setup_wizard_counts_as_done_when_closed_or_skipped(window, qtbot):
    from ytktv.ui.setup_wizard import SetupWizard

    main, controller = window
    wizard = SetupWizard(controller, lambda: None, main)
    qtbot.addWidget(wizard)
    wizard.reject()
    assert controller.settings.setup_done is True


def test_lyrics_nudge_buttons_shift_the_lyrics_on_the_mv_screen(window, qtbot):
    main, controller = window
    controller.enqueue(make_song(1))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    qtbot.waitUntil(lambda: main._state["current"] is not None, timeout=3000)
    main.lyrics_earlier.click()
    main.lyrics_earlier.click()
    qtbot.waitUntil(lambda: main.lyrics_button.text() == "+0.2", timeout=3000)
    assert abs(main.mv_window._lyrics_offset - 0.2) < 1e-6
    main.lyrics_later.click()
    main.lyrics_later.click()
    qtbot.waitUntil(lambda: main.lyrics_button.text() == "Lyrics", timeout=3000)
    assert main.mv_window._lyrics_offset == 0.0


def test_lyrics_and_tune_that_arrive_while_a_song_loads_stay_on_screen(window, qtbot):
    """The first song of an evening streams, so its lyrics come in before it plays."""
    main, controller = window
    mv = main.mv_window
    song = {"id": "a", "singer": "", "owner": "", "song": make_song(1).to_dict()}
    loading = {**controller.state(), "status": "loading", "current": song}
    mv.apply_state(loading)
    mv.set_lyrics([{"start": 0.0, "end": 60.0, "text": "sing"}])
    mv.set_melody({"hop": 0.05, "notes": [60.0] * 40, "transpose": 0.0})
    mv.apply_state(loading)  # more state while still loading
    assert mv.lyrics.has_lines() and mv.pitch_lane.has_melody()
    mv.apply_state({**loading, "status": "playing"})
    assert mv.lyrics.has_lines() and mv.pitch_lane.has_melody()
    mv.apply_state({**loading, "status": "idle", "current": None})
    assert not mv.lyrics.has_lines() and not mv.pitch_lane.has_melody()


def test_first_song_shows_its_lyrics_without_touching_the_button(window, qtbot, monkeypatch):
    """Like the first song of an evening: the video takes a while, the lyrics do not."""
    from ytktv.youtube.lyrics import LyricLine

    main, controller = window
    mv = main.mv_window
    assert controller.settings.show_lyrics
    player = controller.player
    report = player.on_position
    started = []
    # The player starts quietly; the test decides when the first position arrives.
    monkeypatch.setattr(player, "on_position", None)
    controller.resolver.lyrics = lambda video_id, max_height, allow_auto: [
        LyricLine(0.0, 60.0, "la")
    ]
    controller.enqueue(make_song(1))
    qtbot.waitUntil(lambda: controller.lyrics != [], timeout=3000)
    assert controller.status == PlayStatus.LOADING  # lyrics are in, the video is not
    qtbot.wait(200)  # the console and MV screen take in the loading state and the lyrics
    report(0.5, 200.0)  # now the video starts
    started.append(True)
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    qtbot.waitUntil(lambda: main._state["status"] == "playing", timeout=3000)
    qtbot.wait(100)
    assert mv.lyrics.has_lines()  # shown without pressing Lyrics off and on


def test_party_games_show_on_the_console_and_mv_screen(window, qtbot):
    import random

    from ytktv.core import games

    main, _ = window
    page = main.pages["games"]
    page.animate = False
    dice = page.open_game("dice")
    assert page.stack.currentWidget() is dice
    dice.count.setValue(3)
    dice.start()
    assert page.last_result["title"].endswith("Dice") and len(page.last_result["text"].split()) == 3
    qtbot.waitUntil(lambda: "Dice" in main.mv_window.game_card.text(), timeout=3000)
    page.screens["truthdare"].draw("truth")
    assert page.last_result["text"] in games.TRUTHS
    page.show_lobby()
    assert page.stack.currentWidget() is page.lobby
    assert games.spin(["Kim", "Alex"], random.Random(1))["text"] in ("Kim", "Alex")
    assert games.spin([])["text"] == "Add singers first"


def test_home_tiles_open_their_pages_and_show_the_room(window, qtbot):
    main, controller = window
    home = main.pages["home"]
    assert main.stack.currentWidget() is home  # the console opens on the tile wall
    controller.enqueue(make_song(1), singer="Kim")
    controller.enqueue(make_song(2), singer="Alex")
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    qtbot.waitUntil(lambda: home.now_title.text() == "Song 1", timeout=3000)
    assert home.now_singer.text() == "Kim"
    assert home.next_rows[0].text().startswith("Song 2") and "Alex" in home.next_rows[0].text()
    assert home.tiles["queue"].text().endswith("Selected (1)")
    for key, tile in home.tiles.items():
        tile.click()
        assert main.stack.currentWidget() is main.pages[key]
        assert main._nav_buttons[key].isChecked()


def test_reactions_float_up_the_mv_screen(window, qtbot):
    from ytktv.core.controller import REACTIONS

    main, controller = window
    mv = main.mv_window
    mv.resize(800, 450)
    assert controller.send_reaction("🔥") is True
    assert controller.send_reaction("not an emoji") is False
    qtbot.waitUntil(lambda: mv.reactions.active(), timeout=3000)
    mv.reactions.advance(1.0)
    mv.reactions.grab()  # painting works part way up
    mv.reactions.advance(mv.reactions.RISE_SECONDS + 1)
    assert not mv.reactions.active()
    sent = sum(controller.send_reaction(REACTIONS[0]) for _ in range(40))
    assert 0 < sent < 40  # too many at once are refused


def test_levels_stay_within_range_and_changes_from_a_phone_show_up(window, qtbot):
    main, controller = window
    for _ in range(30):
        main.level_keys["mic_volume"][1].click()
    assert controller.settings.mic_volume == 100
    for _ in range(30):
        main.level_keys["mic_volume"][0].click()
    assert controller.settings.mic_volume == 0
    main.level_hud.hide()
    controller.set_volume("music", 40)  # as if from the phone page
    qtbot.waitUntil(lambda: main.level_hud.isVisible(), timeout=3000)
    assert main.level_hud.kind == "music_volume" and main.level_hud.value == 40
    main.level_hud.grab()


def test_more_party_games(window, qtbot):
    import random

    from ytktv.core import games

    rng = random.Random(4)
    bomb = games.NumberBomb(rng)
    secret = bomb.secret
    below = bomb.guess(secret - 1) if secret > 2 else bomb.guess(secret + 1)
    assert "–" in below["text"]
    assert bomb.guess(secret, "Kim")["title"] == "💥 BOOM!"
    assert (bomb.low, bomb.high) == (1, 100)  # a new round starts
    assert "not in the range" in bomb.guess(150)["detail"]

    liars = games.LiarsDice(rng)
    assert len(liars.roll("Kim")) == 5 and len(liars.hand("Kim").split()) == 5
    liars.roll("Alex")
    reveal = liars.reveal()
    assert "Kim:" in reveal["text"] and "Alex:" in reveal["text"] and liars.hands == {}

    sevens = games.Sevens()
    said = [sevens.next()["text"] for _ in range(17)]
    assert said[6] == "PASS!" and said[13] == "PASS!" and said[16] == "PASS!" and said[7] == "8"
    assert games.high_low(["Kim"], rng)["detail"].startswith("High:")
    assert games.challenge(rng)["text"] in games.CHALLENGES
    assert games.coin(rng)["text"] in ("Heads", "Tails")

    main, controller = window
    page = main.pages["games"]
    page.animate = False
    liar = page.open_game("liar")
    liar.start()
    assert "1 players rolled" in main.mv_window.game_card.text()
    liar.show_hand()
    assert controller.liars.hand("Console") in liar.stage.text()
    liar.hide_hand()
    assert controller.liars.hand("Console") not in liar.stage.text()  # hidden again
    liar.reveal()
    assert "Console:" in page.last_result["text"]

    bomb = page.open_game("bomb")
    bomb.start()
    for _ in range(100):  # keep guessing the bottom of the range until it blows up
        bomb.guess.setValue(controller.bomb.low + 1)
        bomb.try_guess()
        if page.last_result["title"].startswith("💥"):
            break
    assert page.last_result["title"].startswith("💥")

    page.players.setText("Kim, Alex, Sam")
    page.open_game("spin").start()
    assert page.last_result["text"] in ("Kim", "Alex", "Sam")
    page.open_game("highlow").start()
    assert "Kim" in page.last_result["text"]
    page.open_game("lots").start()
    assert "Sam:" in page.last_result["text"]
    sevens = page.open_game("sevens")
    for _ in range(7):
        sevens.start()
    assert page.last_result["text"] == "PASS!"
    page.open_game("coin").start()
    assert page.last_result["text"] in ("Heads", "Tails")
    page.open_game("challenge").start()
    assert page.last_result["text"] in games.CHALLENGES
    countdown = page.open_game("countdown")
    countdown.seconds.setValue(3)
    countdown.start()
    assert "3" in countdown.stage.text()
    from tests.helpers import make_song

    result = controller.random_song([make_song(91)], who="Kim")
    assert result is not None
    queued = [i.singer for i in controller.queue.snapshot()]
    if controller.current is not None:  # nothing was playing, so it started right away
        queued.append(controller.current.singer)
    assert "Kim" in queued


def test_a_closed_room_takes_no_songs_and_times_up_after_the_song(window, qtbot):
    import time

    import pytest

    from ytktv.core.models import Song
    from ytktv.rooms.state import RoomState

    main, controller = window

    class Client:
        state = RoomState(closed=True)
        on_event = None

    main.room_client = Client()
    main.apply_room()
    assert controller.room_closed and main.room_closed_view.isVisible()
    assert not main.mv_window._closed_cover.isHidden()
    with pytest.raises(PermissionError):
        controller.enqueue(Song("v1", "Song"))
    assert controller.state()["room_closed"]

    Client.state.apply({"type": "open", "ends_at": time.time() + 3600})
    main.apply_room()
    assert not controller.room_closed and not main.room_closed_view.isVisible()
    assert "left" in main.time_left.text()

    Client.state.ends_at = time.time() - 1  # time is up, nothing playing
    main._tick_room()
    assert Client.state.closed
    qtbot.waitUntil(lambda: controller.room_closed, timeout=7000)


def test_service_from_the_console_and_the_phone(window, qtbot):
    from fastapi.testclient import TestClient
    from PySide6.QtWidgets import QPushButton

    from tests.helpers import FakeSource
    from ytktv.rooms.state import RoomState
    from ytktv.server.app import create_app
    from ytktv.ui.service_dialog import ServiceDialog

    main, controller = window
    sent = []

    class Client:
        state = RoomState(closed=False)
        products = [{"product_id": 1, "name": "Cola", "category": "Drinks", "price": 3.5}]
        currency = "$"
        online = True
        on_event = None

        def call(self, kind, note=""):
            sent.append(("call", kind, note))
            return True

        def order(self, items):
            sent.append(("order", items))
            return True

    client = Client()
    dialog = ServiceDialog(client)
    qtbot.addWidget(dialog)
    dialog.note.setText("two straws")
    dialog.call("Other")
    assert sent[-1] == ("call", "Other", "two straws")
    buttons = [b.text() for b in dialog.findChildren(QPushButton)]
    assert "Drinks" not in buttons and "Other" in buttons  # drinks come from the menu
    stepper = next(iter(dialog.quantities.values()))
    stepper.more.click()
    stepper.more.click()
    stepper.less.click()
    assert stepper.value() == 1

    controller.front_desk = client
    assert controller.state()["service"]["products"][0]["name"] == "Cola"
    with TestClient(create_app(controller, FakeSource())) as http:
        assert http.post("/api/service", json={"kind": "Snacks"}).json() == {"ok": True}
        assert (
            http.post("/api/service", json={"items": [{"product_id": 1, "qty": 2}]}).status_code
            == 200
        )
        assert sent[-1] == ("order", [(1, 2)])


def test_desk_messages_and_controls_reach_the_room(window, qtbot):
    from ytktv.rooms.state import RoomState

    main, controller = window

    class Client:
        state = RoomState(closed=False)
        on_event = None
        products: list = []
        currency = "$"
        online = True

    main.room_client = Client()
    main._on_desk({"type": "message", "text": "Dinner is ready!", "seconds": 10})
    assert "Dinner is ready!" in main.mv_window.game_card.text()
    main._on_desk({"type": "control", "action": "volume", "value": 33})
    assert controller.settings.music_volume == 33
    Client.state.apply({"type": "lock"})
    main._on_desk({"type": "lock"})
    assert main.room_closed_view.isVisible() and "paused" in main.room_closed_view.message.text()
    assert not controller.room_closed  # locked, not closed: the queue is kept
    Client.state.apply({"type": "unlock"})
    main._on_desk({"type": "unlock"})
    assert not main.room_closed_view.isVisible()


def test_artist_filters_pk_battle_and_glow(window, qtbot):
    main, controller = window
    artists = main.pages["artists"]
    artists.filters["language:Cantonese"].click()
    artists.filters["kind:Group"].click()
    assert "Beyond" in artists.buttons and "陳奕迅" not in artists.buttons

    party = main.pages["party"]
    party.pk_button.setChecked(True)
    assert controller.pk_mode and controller.state()["pk"]
    main.mv_window.show_score(
        {
            "points": 92,
            "grade": "Great!",
            "title": "Song",
            "singer": "",
            "board": [],
            "pk": {"scores": [{"mic": 1, "points": 87}, {"mic": 2, "points": 92}], "winner": 2},
        }
    )
    assert "Mic 2 wins" in main.mv_window.score_card._grade

    glows = []
    controller.bus.subscribe(lambda topic, data: glows.append(data) if topic == "glow" else None)
    main.mv_window.on_light(0.5, 0.25)
    assert glows == [{"level": 0.5, "hue": 0.25}]


def test_live_pk_bars(window, qtbot):
    main, controller = window
    controller.set_pk_mode(True)
    main.mv_window.set_pk([{"mic": 1, "points": 40}, {"mic": 2, "points": 55}])
    bars = main.mv_window._pk_bars
    assert not bars.isHidden() and bars.scores[1]["points"] == 55
    bars.grab()  # paints without errors
    main.mv_window.set_pk(None)
    assert bars.isHidden()
    assert controller.live_pk() is None  # nothing is being scored


def test_duet_colours_the_lyrics_by_singer(qtbot):
    from ytktv.ui.mv_overlays import DUET_COLOURS, LyricsOverlay

    overlay = LyricsOverlay()
    qtbot.addWidget(overlay)
    overlay.set_lines(
        [{"start": 0, "end": 2, "text": "男：one"}, {"start": 2, "end": 4, "text": "女：two"}]
    )
    assert overlay._colours(0)[0].name() == "#ffffff"
    overlay.set_duet(True)
    assert overlay._lines[0].text == "one"
    assert overlay._colours(1)[0].name() == DUET_COLOURS[1][0]
    overlay.set_duet(False)
    assert overlay._lines[0].text == "男：one"


def test_duet_toggle_reaches_the_state(tmp_path):
    from tests.helpers import make_controller

    controller, _, _ = make_controller(tmp_path)
    try:
        controller.set_duet_mode(True)
        assert controller.state()["duet"] is True
    finally:
        controller.close()


def test_king_of_singers_and_birthday(window, qtbot):
    import random

    from ytktv.core import games

    tour = games.Tournament(random.Random(2))
    tour.start(["A", "B", "C", "D"])
    for _ in range(3):  # two semi-finals and a final
        first, second = tour.current()
        tour.record(first, 90)
        result = tour.record(second, 60)
    assert tour.champion and result["detail"].endswith("Champion!")
    assert tour.record("A", 99) is None  # it is over

    main, controller = window
    page = main.pages["games"]
    page.animate = False
    page.players.setText("Kim, Alex")
    screen = page.open_game("tournament")
    screen.start()
    assert "vs" in main.mv_window.game_card.text() and not screen.first.isHidden()
    screen.points.setValue(88)
    screen.score(0)
    screen.points.setValue(70)
    screen.score(1)
    assert controller.tournament.champion in ("Kim", "Alex")
    birthday = page.open_game("birthday")
    birthday.name.setText("Mia")
    birthday.start()
    qtbot.waitUntil(lambda: "Mia" in main.mv_window.game_card.text(), timeout=3000)


def test_keyboard_and_remote_keys(window, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtWidgets import QApplication, QLineEdit

    from ytktv.ui.remote_keys import RemoteKeys, key_help

    main, controller = window
    keys = RemoteKeys(controller)
    none = Qt.KeyboardModifier.NoModifier
    volume = controller.settings.music_volume
    assert keys.handle(Qt.Key.Key_Up, none)
    assert controller.settings.music_volume == min(100, volume + 5)
    assert keys.handle(Qt.Key.Key_BracketRight, none) and controller.pitch == 1
    before = controller.vocal_mode
    keys.handle(Qt.Key.Key_V, none)
    assert controller.vocal_mode != before
    keys.handle(Qt.Key.Key_V, none)
    assert controller.vocal_mode == before
    lyrics = controller.settings.show_lyrics
    keys.handle(Qt.Key.Key_L, none)
    assert controller.settings.show_lyrics is not lyrics
    assert not keys.handle(Qt.Key.Key_S, Qt.KeyboardModifier.ControlModifier)  # Ctrl+S: not ours
    assert not keys.handle(Qt.Key.Key_Q, none)

    # While a text box has the focus, keys type into it.
    box = QLineEdit()
    qtbot.addWidget(box)
    box.show()
    box.setFocus()
    qtbot.waitUntil(lambda: QApplication.focusWidget() is box)
    press = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_N, none, "n")
    assert keys.eventFilter(box, press) is False
    assert any(action == "Next song" for _keys, action in key_help())


def test_settings_buttons_save_a_zip(window, tmp_path, qtbot):
    import json
    import zipfile

    from ytktv.desk.panels import UpdateSettings
    from ytktv.desk.store import DeskStore

    main, _controller = window
    saved = main.settings_page.save_diagnostics(str(tmp_path / "app.zip"))
    with zipfile.ZipFile(saved) as bundle:
        assert "settings.json" in bundle.namelist()
    panel = UpdateSettings(DeskStore())
    qtbot.addWidget(panel)
    desk = panel.save_diagnostics(str(tmp_path / "desk.zip"))
    with zipfile.ZipFile(desk) as bundle:
        assert json.loads(bundle.read("about.json"))["app"] == "YTKTV Desk"


def test_large_text(window):
    from PySide6.QtWidgets import QApplication

    from ytktv.ui import theme

    main, controller = window
    assert "font-size: 18px" in theme.stylesheet("Large")  # 14px * 1.25
    assert theme.stylesheet("Normal") == theme.STYLESHEET
    main.settings_page.text_size.setCurrentText("Extra large")
    assert controller.settings.text_size == "Extra large"
    assert "font-size: 21px" in QApplication.instance().styleSheet()
    main.settings_page.text_size.setCurrentText("Normal")


def test_room_window_applies_desk_settings_and_hides_admin_cards(window):
    main, controller = window
    page = main.settings_page
    controller.settings.desk_url = "https://desk:8770"
    page.apply_role()
    assert all(frame.isHidden() for frame in page.admin_cards)
    main._apply_admin({"auto_update": False, "max_height": 720, "unknown": 1})
    assert controller.settings.auto_update is False and controller.settings.max_height == 720
    assert page._checks["auto_update"].isChecked() is False
    main._apply_admin({"max_height": "4k"})  # invalid: ignored, nothing changes
    assert controller.settings.max_height == 720
    controller.settings.desk_url = ""
    page.apply_role()
    assert not any(frame.isHidden() for frame in page.admin_cards)


# -- look checks: every page, no white boxes on the dark theme ---------------------------

LOOK_TYPES = ("QLineEdit", "QListWidget", "QTableWidget", "QComboBox", "QPlainTextEdit",
              "QSpinBox", "QDoubleSpinBox", "QDateEdit", "QTextEdit")  # fmt: skip
WHITE_SHARE = 0.5  # a box more than half white stands out on the dark theme


@pytest.fixture
def themed():
    """The app's dark style sheet, as YTKTV sets it at start (tests run without it)."""
    from PySide6.QtWidgets import QApplication

    from ytktv.ui import theme

    app = QApplication.instance()
    before = app.styleSheet()
    app.setStyleSheet(theme.STYLESHEET)
    yield
    app.setStyleSheet(before)


def white_boxes(root, allowed=()):
    """Visible input boxes and lists that are drawn mostly white."""
    import os

    from PySide6.QtWidgets import QWidget

    bad = []
    for widget in root.findChildren(QWidget):
        kind = type(widget).__name__
        if kind not in LOOK_TYPES or not widget.isVisible() or widget.objectName() in allowed:
            continue
        if widget.width() < 20 or widget.height() < 12:
            continue
        image = widget.grab().toImage()
        step = max(1, min(image.width(), image.height()) // 12)
        samples = [
            image.pixelColor(x, y)
            for x in range(0, image.width(), step)
            for y in range(0, image.height(), step)
        ]
        white = sum(1 for c in samples if min(c.red(), c.green(), c.blue()) > 225)
        if samples and white / len(samples) > WHITE_SHARE:
            bad.append(f"{kind} {widget.objectName() or ''} in {type(widget.parent()).__name__}")
    folder = os.environ.get("YTKTV_SCREENSHOTS")
    if folder:  # CI keeps the pictures for people to look at
        os.makedirs(folder, exist_ok=True)
        root.grab().save(
            os.path.join(folder, f"{root.property('shot') or type(root).__name__}.png")
        )
    return bad


def test_console_pages_have_no_white_boxes(themed, window, qtbot):
    main, _ = window
    main.resize(1400, 900)
    problems = {}
    for key in main.pages:
        main.show_page(key)
        qtbot.wait(20)
        main.setProperty("shot", f"console-{key}")
        found = white_boxes(main)
        if found:
            problems[key] = found
    assert problems == {}


def test_desk_pages_have_no_white_boxes(themed, qtbot):
    from ytktv.desk.server import Hub
    from ytktv.desk.store import DeskStore
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    store.pair(store.new_code(), "Kids")
    desk = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(desk)
    desk.resize(1400, 900)
    desk.show()
    problems = {}
    for index in range(desk.stack.count()):
        desk.show_tab(index)
        qtbot.wait(20)
        desk.setProperty("shot", f"desk-{index}")
        found = white_boxes(desk)
        if found:
            problems[index] = found
    assert problems == {}


def test_wireless_tv_screen_and_picture_delay(window, qtbot):
    main, controller = window
    moved = []
    main.place_mv = lambda: moved.append(True)

    class Screen:
        def name(self):
            return "Living Room TV"

    main._screen_added(Screen())
    qtbot.waitUntil(lambda: bool(moved), timeout=4000)
    assert "Living Room TV" in main.toast.text()
    main.settings_page.screen_delay.setValue(240)
    assert controller.settings.screen_delay_ms == 240 and controller.player.audio_delay == 0.24
