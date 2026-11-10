"""Birthday celebrations: a member whose birthday it is gets a party on the room's TV.

The desk only sends a signed ``{"type": "birthday", "name": ...}`` to that one room;
the lobby TV is never told.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ytktv.desk.store import DeskStore, Member

ENABLED_SETTING = "birthday_celebration"  # "0" turns the automatic party off
WINDOW_SETTING = "birthday_window_days"  # days either side of the birthday that count; 0 = today


def enabled(store: DeskStore) -> bool:
    return store.setting(ENABLED_SETTING, "1") != "0"


def window_days(store: DeskStore) -> int:
    try:
        return max(0, min(31, int(store.setting(WINDOW_SETTING, "0"))))
    except ValueError:
        return 0


def is_birthday(birthday: str, today: dt.date, window: int = 0) -> bool:
    """*birthday* ("MM-DD") falls within *window* days of *today*, in any year."""
    if not birthday:
        return False
    try:
        month, day = (int(part) for part in birthday.split("-"))
    except ValueError:
        return False
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            date = dt.date(year, month, day)
        except ValueError:  # 02-29 outside a leap year: kept on 02-28
            date = dt.date(year, 2, 28)
        if abs((date - today).days) <= window:
            return True
    return False


def first_name(name: str) -> str:
    parts = name.split()
    return parts[0] if parts else ""


def member_for_guest(store: DeskStore, guest: str) -> Member | None:
    """The member a room was opened for: the guest field holds their name or phone."""
    guest = guest.strip()
    if not guest:
        return None
    by_phone = store.member_by_phone(guest) if any(ch.isdigit() for ch in guest) else None
    if by_phone is not None:
        return by_phone
    folded = guest.casefold()
    return next((m for m in store.members(guest) if m.name.strip().casefold() == folded), None)


def birthday_member(store: DeskStore, guest: str, today: dt.date | None = None) -> Member | None:
    """The member behind *guest* when it is their birthday and the party is switched on."""
    if not enabled(store):
        return None
    member = member_for_guest(store, guest)
    today = dt.date.today() if today is None else today
    if member is None or not is_birthday(member.birthday, today, window_days(store)):
        return None
    return member


def message(name: str) -> dict[str, Any]:
    return {"type": "birthday", "name": first_name(name)[:40]}


def celebrate(hub: Any, room_id: str, name: str) -> None:
    """Throw the party in *room_id* now (by hand, or because a member's room opened)."""
    hub.send_soon(room_id, message(name))


def celebrate_if_birthday(
    store: DeskStore, hub: Any, room_id: str, today: dt.date | None = None
) -> Member | None:
    room = store.room(room_id)
    if room is None or not room.is_open:
        return None
    member = birthday_member(store, room.guest, today)
    if member is not None:
        celebrate(hub, room_id, member.name)
    return member
