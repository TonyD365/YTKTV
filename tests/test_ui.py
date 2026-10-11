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
    qtbot.waitUntil(lambda: len(page._songs) > 0, timeout=3000)
    first = page._songs[0]
    controller.enqueue(first)
    wait_for(lambda: controller.current is not None)
    assert controller.current.song.video_id == first.video_id


def test_control_bar_buttons_drive_the_controller(window, qtbot):
    main, controller = window
    from ytktv.core.models import VocalMode

    qtbot.mouseClick(main.mode_buttons[VocalMode.CENTER_CUT], Qt.MouseButton.LeftButton)
    assert controller.vocal_mode == VocalMode.CENTER_CUT
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
