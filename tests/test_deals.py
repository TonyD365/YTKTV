"""Packages, coupons and members' birthdays at the till."""

from __future__ import annotations

import time

import pytest

from ytktv.desk import billing
from ytktv.desk.store import Coupon, DeskStore, Package


def test_package_bill_charges_the_package_and_extra_time():
    store = DeskStore()
    store.set_setting("rate", "40")
    room, _ = store.pair(store.new_code(), "Kids")
    party = store.save_package(Package(0, "Party", 99.0, 120, "1 × Beer tower"))
    now = time.time()
    store.open_room(room.room_id, "Kim", 180, now=now)  # booked for an hour more than the package
    store.set_session_package(room.room_id, party)
    lines = billing.bill(store, room.room_id, now=now + 60).lines
    assert lines[0] == ("Package · Party · 1 × Beer tower", 99.0)
    assert lines[1] == ("Extra time · 1h 00m at $40/h", 40.0)
    assert store.session_package(room.room_id).name == "Party"
    store.close_room(room.room_id)
    assert store.session_package(room.room_id) is None


def test_coupons_and_birthdays():
    store = DeskStore()
    store.save_coupon(Coupon("summer20", "percent", 20, uses_left=1))
    store.save_coupon(Coupon("OLD", "amount", 5, expires=time.time() - 10))
    with pytest.raises(ValueError, match="expired"):
        store.coupon("old")
    with pytest.raises(ValueError, match="No such"):
        store.coupon("nope")
    assert store.coupon("SUMMER20").value == 20
    store.use_coupon("SUMMER20")
    with pytest.raises(ValueError, match="used up"):
        store.coupon("summer20")
    with pytest.raises(ValueError):
        store.save_coupon(Coupon("BAD", "free", 1))

    bill = billing.Bill("Kids", "", "$", [("Room", 100.0)], birthday_off=10, coupon_amount=5)
    bill.coupon_percent = 20
    assert bill.total == pytest.approx(100 * 0.9 * 0.8 - 5)
    assert "Coupon" in bill.html() and "−$5.00" in bill.html()

    member = store.add_member("Kim", "5551234")
    store.set_birthday(member, time.strftime("%m-%d"))
    assert store.member_by_phone("5551234").birthday == time.strftime("%m-%d")
    with pytest.raises(ValueError, match="MM-DD"):
        store.set_birthday(member, "13-45")


def test_till_and_window_use_packages_coupons_and_birthdays(qtbot):
    from ytktv.desk.panels import BillDialog
    from ytktv.desk.server import Hub
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    store.set_setting("rate", "40")
    store.set_setting("birthday_discount", "15")
    store.set_setting("member_discount", "0")
    room, _ = store.pair(store.new_code(), "Kids")
    store.save_package(Package(0, "Party", 99.0, 180))
    store.save_coupon(Coupon("TEN", "amount", 10, uses_left=2))
    member = store.add_member("Kim", "5551234")
    store.set_birthday(member, time.strftime("%m-%d"))

    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.select(room.room_id)
    window.open_room(guest="Kim", length="Package · Party (3 h, $99)")
    assert store.session_package(room.room_id).name == "Party"
    assert window.deals.package_list.count() == 1 and window.deals.coupon_list.count() == 1

    dialog = BillDialog(billing.bill(store, room.room_id), window, store)
    qtbot.addWidget(dialog)
    dialog.phone.setText("5551234")
    dialog.find_member()
    assert dialog.bill.birthday_off == 15
    assert not dialog.apply_coupon("WRONG") and "No such" in dialog.error.text()
    assert dialog.apply_coupon("ten")
    assert dialog.bill.total == pytest.approx(99 * 0.85 - 10)

    window.close_room(confirm=False)  # a plain close: no coupon was given
    assert store.coupon("TEN").uses_left == 2
