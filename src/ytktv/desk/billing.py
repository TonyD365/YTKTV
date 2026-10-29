"""What a room owes when it closes."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from html import escape

from ytktv.desk.store import DeskStore, Room

DEFAULT_RATE = "20"
# How an open-ended session's time is charged.
ROUNDING = {
    "minute": "By the minute",
    "hour": "Every started hour",
    "unit": "Every started block (see Block minutes)",
}


@dataclass
class Bill:
    room: str
    guest: str
    currency: str
    lines: list[tuple[str, float]] = field(default_factory=list)
    minimum: float = 0.0

    @property
    def subtotal(self) -> float:
        return round(sum(amount for _, amount in self.lines), 2)

    @property
    def total(self) -> float:
        return max(self.subtotal, self.minimum)

    def html(self) -> str:
        rows = "".join(
            f"<tr><td>{escape(text)}</td><td align='right'>{self.currency}{amount:.2f}</td></tr>"
            for text, amount in self.lines
        )
        if self.minimum > self.subtotal:
            rows += (
                f"<tr><td>Minimum spend</td><td align='right'>{self.currency}"
                f"{self.minimum:.2f}</td></tr>"
            )
        return (
            f"<h2>YTKTV · {escape(self.room)}</h2>"
            f"<p>{escape(self.guest)}<br>{time.strftime('%Y-%m-%d %H:%M')}</p>"
            f"<table width='100%' cellpadding='4'>{rows}"
            f"<tr><td><b>Total</b></td><td align='right'><b>{self.currency}{self.total:.2f}"
            "</b></td></tr></table>"
        )


def billed_minutes(room: Room, rounding: str, block: int, now: float) -> float:
    """Booked time for a timed room; used time, rounded as set, for an open-ended one."""
    if room.ends_at is not None:
        return max(0.0, (room.ends_at - room.opened_at) / 60)
    used = max(0.0, (now - room.opened_at) / 60)
    if rounding == "hour":
        return math.ceil(used / 60) * 60
    if rounding == "unit":
        return math.ceil(used / block) * block
    return math.ceil(used)


def bill(store: DeskStore, room_id: str, now: float | None = None) -> Bill:
    room = store.room(room_id)
    if room is None:
        raise KeyError(room_id)
    now = time.time() if now is None else now
    rate = room.rate if room.rate is not None else float(store.setting("rate", DEFAULT_RATE))
    minutes = billed_minutes(
        room, store.setting("rounding", "minute"), int(store.setting("block", "15")), now
    )
    result = Bill(
        room.name,
        room.guest,
        store.setting("currency", "$"),
        minimum=float(store.setting("minimum", "0")),
    )
    hours = f"{int(minutes // 60)}h {int(minutes % 60):02d}m"
    result.lines.append(
        (f"Room · {hours} at {result.currency}{rate:g}/h", round(rate * minutes / 60, 2))
    )
    for order in store.orders(room_id):
        if order.status != "cancelled":
            result.lines.append((f"{order.name} × {order.qty}", round(order.price * order.qty, 2)))
    return result
