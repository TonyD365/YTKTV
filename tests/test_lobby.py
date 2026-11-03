"""The Desk's lobby screen: what it lists, and that the setting shows and hides it."""

from __future__ import annotations

from ytktv.desk.lobby import SETTING, describe
from ytktv.desk.store import Booking, Room


def test_lists_free_rooms_busy_rooms_and_later_bookings():
    now = 1_000_000.0
    rooms = [
        Room("a", "Blue", 0, room_type="Large", capacity=10),
        Room("b", "Red", 0, is_open=True, ends_at=now + 65 * 60),
        Room("c", "Kids", 0, is_open=True),
        Room("d", "Gold", 0),
    ]
    status = {"a": "free", "b": "in_use", "c": "in_use", "d": "offline"}
    bookings = [
        Booking(1, "a", now + 3600, 60),
        Booking(2, "a", now - 3 * 3600, 60),  # long past
        Booking(3, "b", now + 7200, 60, status="cancelled"),
    ]
    free, busy, booked = describe(rooms, lambda r: status[r.room_id], bookings, now)
    assert free == ["Blue · Large, 10 seats"]
    assert busy == ["Kids · open", "Red · free in 1:05"]
    assert len(booked) == 1 and booked[0].endswith("· Blue")


def test_setting_opens_and_closes_the_window(qtbot):
    from ytktv.desk.server import Hub
    from ytktv.desk.store import DeskStore
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    store.pair(store.new_code(), "Blue")
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    assert window.lobby.window is None
    window.lobby_settings.enabled.setChecked(True)
    assert store.setting(SETTING) == "-1"
    lobby = window.lobby.window
    assert lobby is not None and lobby.isVisible()
    window.lobby_settings.enabled.setChecked(False)
    assert window.lobby.window is None and store.setting(SETTING) == ""
