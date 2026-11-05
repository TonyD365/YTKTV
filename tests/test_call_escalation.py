"""Service calls that wait too long: counted for the shift report and flagged on the desk."""

from __future__ import annotations

from ytktv.desk.store import DeskStore


def test_late_calls_are_counted():
    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Blue")
    store.set_setting("call_overdue_minutes", "3")
    quick = store.add_call(room.room_id, "Drinks", "", now=1000.0)
    slow = store.add_call(room.room_id, "Snacks", "", now=1000.0)
    store.add_call(room.room_id, "Other", "", now=1100.0)  # still waiting at the end
    store.finish_call(quick, now=1060.0)
    store.finish_call(slow, now=1300.0)
    assert store.late_calls(0, 1200.0) == (3, 1)  # the slow one; the last one is not late yet
    assert store.late_calls(0, 1400.0) == (3, 2)  # now the waiting one is too


def test_overdue_call_turns_red_on_the_desk(qtbot):
    import time

    from ytktv.desk.pages import shift_report
    from ytktv.desk.server import Hub
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Blue")
    store.open_room(room.room_id, "", None)
    store.add_call(room.room_id, "Drinks", "", now=time.time() - 10 * 60)
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.refresh()
    chip = window.call_chips.itemAt(0).widget()
    assert "⚠ 10 min" in chip.text() and "#ff1744" in chip.styleSheet()
    assert "Service calls" in shift_report(store)
