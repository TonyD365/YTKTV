"""Admin settings: set by the staff terminal, checked and applied by the room."""

from __future__ import annotations

import pytest

from ytktv.config import Settings
from ytktv.rooms import admin


def test_room_accepts_only_known_valid_settings():
    settings = Settings()
    changed = admin.apply(
        settings,
        {"max_height": 720, "auto_update": False, "evil": "rm -rf /", "local_folders": ["/a", " "]},
    )
    assert set(changed) == {"max_height", "auto_update", "local_folders"}
    assert settings.max_height == 720 and settings.local_folders == ["/a"]
    assert not hasattr(settings, "evil")
    before = settings.max_height
    for bad in (
        {"max_height": 999},
        {"auto_update": "yes"},
        {"smart_lights": "disco"},
        {"smart_lights_host": "x; rm -rf /"},
        {"mv_screen": True},
        {"local_folders": ["/x"] * 21},
    ):
        with pytest.raises(ValueError):
            admin.apply(settings, {"max_height": 1080, **bad})
    assert settings.max_height == before  # nothing changes when one value is bad
    with pytest.raises(ValueError):
        admin.apply(settings, ["not", "a", "dict"])
    report = admin.report(settings, {"version": "9"})
    assert report["type"] == "admin_report" and report["settings"]["max_height"] == 720
    assert set(report["settings"]) == set(admin.FIELDS) and report["version"] == "9"


def test_desk_keeps_reports_and_sends_changes(qtbot):
    from ytktv.desk.admin_dialog import AdminSettingsDialog
    from ytktv.desk.server import Hub, clean_report
    from ytktv.desk.store import DeskStore
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Kids")
    hub = Hub()
    sent: list[tuple[str, dict]] = []
    hub.send_soon = lambda room_id, message: sent.append((room_id, message))  # type: ignore[method-assign]
    window = DeskWindow(store, hub, "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.select(room.room_id)
    assert hub.report(room.room_id) is None and not window.admin_settings({"max_height": 720})

    hub.channels[room.room_id] = object()  # type: ignore[assignment]
    hub.reports[room.room_id] = clean_report(
        admin.report(Settings(), {"screens": ["Built-in", "TV"], "outputs": ["HDMI"]})
    )
    dialog = AdminSettingsDialog("Kids", hub.report(room.room_id))
    qtbot.addWidget(dialog)
    assert dialog.values() == {}
    dialog.widgets["auto_update"].setChecked(False)
    dialog.widgets["mv_screen"].setCurrentIndex(2)
    assert dialog.values() == {"auto_update": False, "mv_screen": 1}

    assert window.admin_settings({"local_folders": ["/songs"], "auto_update": False})
    assert sent[-1] == (
        room.room_id,
        {"type": "admin_settings", "values": {"local_folders": ["/songs"], "auto_update": False}},
    )
    assert store.room(room.room_id).local_folders == ["/songs"]
