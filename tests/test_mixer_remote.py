from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import FakeSource, make_controller
from ytktv.audio import presets
from ytktv.config import SettingsStore
from ytktv.server.app import create_app


def fx(mic) -> dict[str, float]:
    return presets.values_of(mic)


def test_built_in_presets_are_within_limits():
    assert list(presets.BUILT_IN) == ["Pop", "Ballad", "Rock", "KTV Hall", "Dry"]
    for values in presets.BUILT_IN.values():
        assert set(values) == set(presets.PRESET_FIELDS)
        for name, value in values.items():
            assert presets.clamp(name, value) == value


def test_set_mic_clamps_and_rejects_unknown_controls(ktv):
    controller, _, _ = ktv
    events = []
    controller.bus.subscribe(lambda topic, data: events.append(topic) if topic == "mixer" else None)
    controller.set_mic(0, reverb=5, low_db=-40, fader=0.5, mute=1)
    mic = controller.settings.mics[0]
    assert (mic.reverb, mic.low_db, mic.fader, mic.mute) == (1.0, -12.0, 0.5, True)
    assert events == ["mixer"]
    with pytest.raises(KeyError):
        controller.set_mic(0, device="hacked")  # only the strip's knobs can be set this way
    with pytest.raises(IndexError):
        controller.set_mic(99, fader=0.1)


def test_presets_apply_to_every_channel_and_track_what_matches(ktv):
    controller, _, _ = ktv
    mics = controller.settings.mics
    mics[1].fader, mics[1].pan, mics[1].mute = 0.3, -0.5, True

    controller.apply_preset("KTV Hall")
    assert all(fx(mic) == presets.BUILT_IN["KTV Hall"] for mic in mics)
    assert (mics[1].fader, mics[1].pan, mics[1].mute) == (0.3, -0.5, True)  # levels are left alone
    assert controller.mixer_state()["preset"] == "KTV Hall"

    controller.set_mic(0, fader=0.9)
    assert controller.mixer_state()["preset"] == "KTV Hall"  # volume is not part of a preset
    controller.set_mic(0, reverb=0.1)
    assert controller.mixer_state()["preset"] == ""  # now it is a custom sound
    controller.set_mic(0, reverb=0.6)
    assert controller.mixer_state()["preset"] == "KTV Hall"  # dialled back onto the preset

    with pytest.raises(KeyError):
        controller.apply_preset("Nope")


def test_saving_and_deleting_your_own_presets(tmp_path):
    controller, _, _ = make_controller(tmp_path)
    try:
        controller.set_mic(0, low_db=4, mid_db=-2, high_db=5, reverb=0.33, echo=0.2)
        assert controller.save_preset("  My / voice  ") == "My voice"
        names = [p["name"] for p in controller.mixer_state()["presets"]]
        assert names == ["Pop", "Ballad", "Rock", "KTV Hall", "Dry", "My voice"]
        assert controller.mixer_state()["presets"][-1]["builtin"] is False
        assert controller.mixer_state()["preset"] == ""  # only channel 1 has that sound so far

        controller.apply_preset("Dry")
        controller.apply_preset("My voice")
        assert all(mic.reverb == 0.33 and mic.low_db == 4 for mic in controller.settings.mics)
        assert controller.mixer_state()["preset"] == "My voice"

        with pytest.raises(ValueError, match="built-in"):
            controller.save_preset("Rock")
        with pytest.raises(ValueError, match="needs a name"):
            controller.save_preset(" / ")
        assert not controller.delete_preset("Rock")  # built-ins stay
    finally:
        controller.close()

    reloaded = SettingsStore(tmp_path / "settings.json").settings
    assert reloaded.mic_presets["My voice"]["reverb"] == 0.33 and reloaded.mic_preset == "My voice"

    controller, _, _ = make_controller(tmp_path)
    try:
        assert controller.delete_preset("My voice") and not controller.delete_preset("My voice")
        assert controller.mixer_state()["preset"] == ""
    finally:
        controller.close()


def test_mixer_over_http(ktv):
    controller, _, _ = ktv
    with TestClient(create_app(controller, FakeSource())) as http:
        state = http.get("/api/mixer").json()
        assert len(state["mics"]) == 4 and state["mics"][0]["enabled"] is True
        assert state["mics"][0]["index"] == 0 and state["running"] is False
        assert {"gain", "low_db", "reverb", "echo", "pan", "fader", "mute", "device"} <= state[
            "mics"
        ][0].keys()

        changed = http.post("/api/mixer/mics/0", json={"reverb": 0.7, "mute": True}).json()
        assert changed["mics"][0]["reverb"] == 0.7 and changed["mics"][0]["mute"] is True
        assert controller.settings.mics[0].reverb == 0.7
        assert http.post("/api/mixer/mics/0", json={"reverb": 3}).status_code == 422
        assert http.post("/api/mixer/mics/9", json={"fader": 0.5}).status_code == 404
        # Fields outside the strip (like the input device) are simply not part of the model.
        http.post("/api/mixer/mics/0", json={"device": "evil", "fader": 0.4})
        assert (
            controller.settings.mics[0].device is None and controller.settings.mics[0].fader == 0.4
        )

        applied = http.post("/api/mixer/presets/Ballad/apply").json()
        assert applied["preset"] == "Ballad" and applied["mics"][2]["reverb"] == 0.45
        assert http.post("/api/mixer/presets/Nope/apply").status_code == 404

        assert http.post("/api/mixer/presets", json={"name": "Duet"}).json() == {"name": "Duet"}
        assert http.post("/api/mixer/presets", json={"name": "Pop"}).status_code == 400
        assert http.post("/api/mixer/presets/Duet/apply").json()["preset"] == "Duet"
        assert http.delete("/api/mixer/presets/Duet").json() == {"ok": True}
        assert http.delete("/api/mixer/presets/Duet").status_code == 404
        assert http.delete("/api/mixer/presets/Pop").status_code == 404

        with http.websocket_connect("/ws") as ws:
            ws.receive_json()  # initial state
            http.post("/api/mixer/mics/1", json={"echo": 0.5})
            for _ in range(10):
                if ws.receive_json()["type"] == "mixer":
                    break
            else:
                pytest.fail("phones were not told the mixer changed")


def test_desktop_mixer_follows_remote_changes_and_presets(qtbot, ktv, monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QInputDialog

    from ytktv.ui.main_window import MainWindow
    from ytktv.ui.mv_window import MvWindow

    controller, _, _ = ktv
    monkeypatch.setattr("ytktv.audio.devices.list_inputs", lambda: ["Test Mic"])
    monkeypatch.setattr("ytktv.audio.devices.list_outputs", lambda: ["Test Speakers"])
    mv = MvWindow(None)
    main = MainWindow(controller, FakeSource(), mv, "http://192.168.0.2:8765")  # type: ignore[arg-type]
    qtbot.addWidget(main)
    qtbot.addWidget(mv)
    main.show_page("mixer")
    panel = main.mixer_page
    strip = panel.strips[0]
    assert panel.preset.currentText() == "Custom"

    # A phone turns the reverb up and mutes the channel: the hardware-style controls move.
    controller.set_mic(0, reverb=0.8, mute=True, fader=0.35)
    qtbot.waitUntil(lambda: strip.knobs["reverb"].value() == pytest.approx(0.8), timeout=3000)
    assert strip.mute.isChecked() and strip.fader.value() == pytest.approx(0.35)

    panel.preset.setCurrentIndex(panel.preset.findData("Rock"))
    panel._preset_chosen(0)
    qtbot.waitUntil(lambda: strip.knobs["mid_db"].value() == pytest.approx(3.0), timeout=3000)
    assert panel.strips[3].knobs["reverb"].value() == pytest.approx(0.15)
    assert panel.preset.currentData() == "Rock" and not panel.delete_preset.isEnabled()

    # Turning a knob by hand goes through the same path and makes it a custom sound.
    strip.knobs["echo"].set_value(0.9, notify=True)
    assert controller.settings.mics[0].echo == pytest.approx(0.9)
    qtbot.waitUntil(lambda: panel.preset.currentText() == "Custom", timeout=3000)

    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Echo heavy", True))
    panel._save_preset()
    assert "Echo heavy" in controller.settings.mic_presets
    controller.apply_preset("Echo heavy")
    qtbot.waitUntil(lambda: panel.preset.currentData() == "Echo heavy", timeout=3000)
    assert panel.delete_preset.isEnabled()
    panel._delete_preset()
    assert "Echo heavy" not in controller.settings.mic_presets


def test_compressor_and_feedback_guard_are_remote_controls_too(ktv):
    controller, _, _ = ktv
    controller.set_mic(0, comp=0.7)
    assert controller.settings.mics[0].comp == 0.7
    controller.set_mic(0, comp=5)
    assert controller.settings.mics[0].comp == 1.0  # clamped
    state = controller.mixer_state()
    assert state["mics"][0]["comp"] == 1.0 and state["feedback_guard"] is True
    controller.set_feedback_guard(False)
    assert controller.mixer_state()["feedback_guard"] is False
