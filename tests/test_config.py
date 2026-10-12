from __future__ import annotations

import json

from ytktv.config import MIC_CHANNELS, Settings, SettingsStore


def test_defaults_enable_one_microphone():
    settings = Settings()
    assert len(settings.mics) == MIC_CHANNELS
    assert [m.enabled for m in settings.mics] == [True, False, False, False]
    assert settings.mic_monitor


def test_round_trip_and_unknown_keys(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.settings.music_volume = 42
    store.settings.mics[1].enabled = True
    store.settings.mics[1].device = "USB Mic"
    store.settings.mics[1].reverb = 0.9
    store.save()

    data = json.loads(path.read_text())
    data["from_a_newer_version"] = True
    data["mics"][0]["future_knob"] = 1
    path.write_text(json.dumps(data))

    loaded = SettingsStore(path).settings
    assert loaded.music_volume == 42
    assert (loaded.mics[1].device, loaded.mics[1].enabled, loaded.mics[1].reverb) == (
        "USB Mic",
        True,
        0.9,
    )


def test_corrupt_file_falls_back_to_defaults(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("{not json")
    assert SettingsStore(path).settings.server_port == 8765


def test_short_mic_list_is_padded(tmp_path):
    settings = Settings.from_dict({"mics": [{"gain": 1.5}]})
    assert len(settings.mics) == MIC_CHANNELS and settings.mics[0].gain == 1.5


def test_setup_wizard_is_for_new_installs_only(tmp_path):
    from ytktv.config import SettingsStore

    fresh = SettingsStore(tmp_path / "new" / "settings.json")
    assert fresh.settings.setup_done is False  # nothing saved yet: a first start

    old = tmp_path / "old.json"
    old.write_text('{"music_volume": 55}', encoding="utf-8")  # saved before the wizard existed
    store = SettingsStore(old)
    assert store.settings.setup_done is True and store.settings.music_volume == 55

    store.settings.setup_done = False
    store.save()
    assert SettingsStore(old).settings.setup_done is False  # an explicit value is kept
