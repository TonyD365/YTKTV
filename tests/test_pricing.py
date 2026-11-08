"""Room prices by time of day."""

from __future__ import annotations

from datetime import datetime

import pytest

from ytktv.desk import billing
from ytktv.desk.pricing import (
    WEEKDAYS,
    WEEKEND,
    PriceRule,
    price_stay,
    rules_from_json,
    rules_to_json,
)
from ytktv.desk.store import DeskStore, Package

HAPPY = PriceRule("Happy hour", WEEKDAYS, 14 * 60, 18 * 60, "rate", 60)
WEEKEND_UP = PriceRule("Weekend", WEEKEND, 0, 0, "percent", 20)
LATE = PriceRule("Late night", (0, 1, 2, 3, 4, 5, 6), 0, 6 * 60, "package", 150)
MONDAY = datetime(2026, 11, 9)  # a Monday
FRIDAY = datetime(2026, 11, 13)


def summary(parts):
    return [(p.rule, round(p.minutes, 2), p.amount) for p in parts]


def test_no_rules_is_one_room_part():
    parts = price_stay(MONDAY.replace(hour=15), 130, 100, [])
    assert summary(parts) == [("", 130, round(100 * 130 / 60, 2))]
    assert parts[0].text("¥") == "Room · 2h 10m at ¥100/h"
    assert summary(price_stay(MONDAY, 0, 100, [])) == [("", 0, 0)]


def test_stay_split_across_happy_hour():
    parts = price_stay(MONDAY.replace(hour=13), 3 * 60, 100, [HAPPY])
    assert summary(parts) == [("", 60, 100.0), ("Happy hour", 120, 120.0)]
    assert parts[1].text("¥") == "Room · 2h 00m at ¥60/h · Happy hour"
    # Not on a Saturday.
    assert summary(price_stay(datetime(2026, 11, 14, 15), 60, 100, [HAPPY])) == [("", 60, 100.0)]


def test_percent_and_first_rule_wins():
    sat = datetime(2026, 11, 14, 15)
    assert summary(price_stay(sat, 60, 100, [WEEKEND_UP])) == [("Weekend", 60, 120.0)]
    off = PriceRule("Off", WEEKEND, 0, 0, "percent", -30)
    assert summary(price_stay(sat, 60, 100, [off, WEEKEND_UP])) == [("Off", 60, 70.0)]


def test_window_crossing_midnight_belongs_to_its_start_day():
    friday_late = PriceRule("Fri late", (4,), 22 * 60, 2 * 60, "rate", 50)
    parts = price_stay(FRIDAY.replace(hour=21), 6 * 60, 100, [friday_late])
    assert summary(parts) == [("", 120, 200.0), ("Fri late", 240, 200.0)]
    # Thursday 23:00 to Friday 01:00 is not in a Friday window...
    thursday = datetime(2026, 11, 12, 23)
    assert summary(price_stay(thursday, 120, 100, [friday_late])) == [("", 120, 200.0)]
    # ...but Saturday 01:00 is.
    saturday = datetime(2026, 11, 14, 1)
    assert summary(price_stay(saturday, 60, 100, [friday_late])) == [("Fri late", 60, 50.0)]


def test_package_partly_inside_charges_package_once_per_window():
    parts = price_stay(MONDAY.replace(hour=23), 3 * 60, 100, [LATE])
    assert summary(parts) == [("", 60, 100.0), ("Late night", 120, 150.0)]
    assert parts[1].text("¥") == "Room · Late night · 2h 00m"
    two_nights = price_stay(MONDAY.replace(hour=1), 25 * 60, 0, [LATE])
    assert two_nights[0].amount == 300.0 and len(two_nights[0].starts) == 2
    assert two_nights[0].text("¥").startswith("Room · 2 × Late night")


def test_room_types_and_inactive_rules():
    vip = PriceRule("VIP", WEEKDAYS, 0, 0, "rate", 200, ("VIP",))
    off = PriceRule("Off", WEEKDAYS, 0, 0, "rate", 1, active=False)
    assert summary(price_stay(MONDAY, 60, 100, [off, vip], "VIP")) == [("VIP", 60, 200.0)]
    assert summary(price_stay(MONDAY, 60, 100, [off, vip], "Small")) == [("", 60, 100.0)]


def test_fractional_minutes_and_seconds():
    parts = price_stay(MONDAY.replace(hour=17, minute=59, second=30), 1.5, 120, [HAPPY])
    assert summary(parts) == [("Happy hour", 1, 1.0), ("", 0.5, 1.0)]


def test_dst_agnostic_wall_clock():
    # Wall-clock arithmetic: 01:30 + 60 minutes is 02:30 even on a DST night.
    night = PriceRule("Night", (6,), 2 * 60, 3 * 60, "rate", 10)
    parts = price_stay(datetime(2026, 3, 29, 1, 30), 60, 100, [night])
    assert summary(parts) == [("", 30, 50.0), ("Night", 30, 5.0)]


def test_json_round_trip_skips_bad_entries():
    rules = [HAPPY, WEEKEND_UP, LATE]
    assert rules_from_json(rules_to_json(rules)) == rules
    assert rules_from_json("not json") == []
    assert rules_from_json('[{"name": "x", "kind": "free"}, {"kind": "rate"}, 3]') == []


def _room(store, rate="100", rounding="minute"):
    store.set_setting("rate", rate)
    store.set_setting("rounding", rounding)
    store.set_setting("currency", "¥")
    room, _ = store.pair(store.new_code(), "A1")
    return room


def test_bill_unchanged_without_rules_and_split_with_them():
    store = DeskStore()
    room = _room(store, rounding="hour")
    opened = MONDAY.replace(hour=13, minute=30).timestamp()
    store.open_room(room.room_id, "Kim", None, now=opened)
    now = opened + 100 * 60  # 1h40m used, billed as 2 hours
    assert billing.bill(store, room.room_id, now=now).lines == [("Room · 2h 00m at ¥100/h", 200.0)]
    store.set_setting("price_rules", rules_to_json([HAPPY]))
    result = billing.bill(store, room.room_id, now=now)
    assert result.lines == [
        ("Room · 0h 30m at ¥100/h", 50.0),
        ("Room · 1h 30m at ¥60/h · Happy hour", 90.0),
    ]
    result.discount = 10
    result.service_rate = 10
    result.tax_rate = 5
    after = 140 * 0.9
    assert result.total == pytest.approx(round(after + after * 0.1 + after * 1.1 * 0.05, 2))


def test_session_package_then_rules_from_where_it_ends():
    store = DeskStore()
    room = _room(store)
    party = store.save_package(Package(0, "Party", 99.0, 60))
    opened = MONDAY.replace(hour=13).timestamp()
    store.open_room(room.room_id, "Kim", 120, now=opened)
    store.set_session_package(room.room_id, party)
    store.set_setting("price_rules", rules_to_json([HAPPY]))
    lines = billing.bill(store, room.room_id, now=opened).lines
    assert lines == [("Package · Party", 99.0), ("Extra time · 1h 00m at ¥60/h · Happy hour", 60.0)]


def test_settings_add_edit_remove_rules(qtbot):
    from ytktv.desk.deals import DealsSettings, PriceRuleDialog

    store = DeskStore()
    settings = DealsSettings(store)
    qtbot.addWidget(settings)
    settings.add_rule(HAPPY)
    settings.add_rule(LATE)
    assert settings.rule_list.count() == 2
    assert "Mon–Fri 14:00–18:00" in settings.rule_list.item(0).text()
    dialog = PriceRuleDialog(LATE)
    qtbot.addWidget(dialog)
    dialog.name.setText("Midnight")
    dialog.types[0].setChecked(True)
    edited = dialog.rule()
    assert (edited.name, edited.start, edited.end, edited.kind) == ("Midnight", 0, 360, "package")
    assert edited.room_types == ("Small",)
    settings.rule_list.setCurrentRow(0)
    settings.remove_rule()
    assert [r.name for r in settings.rules()] == ["Late night"]
