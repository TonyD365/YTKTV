"""What a room owes when it closes."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from html import escape

from ytktv.desk.store import DeskStore, Room

DEFAULT_RATE = "20"
PAYMENTS = ("Cash", "Card", "WeChat Pay", "Alipay", "Member balance")
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
    # Set at the till:
    member: str = ""  # the member's name, when one pays or collects points
    member_off: float = 0.0  # members' discount, percent
    discount: float = 0.0  # a discount given at the till, percent
    round_to: float = 0.0  # drop the small change: 0 (keep), 1 or 10
    payment: str = "Cash"
    birthday_off: float = 0.0  # the member's birthday discount, percent
    coupon: str = ""  # its code
    coupon_percent: float = 0.0
    coupon_amount: float = 0.0

    @property
    def subtotal(self) -> float:
        return round(sum(amount for _, amount in self.lines), 2)

    @property
    def before_discounts(self) -> float:
        return max(self.subtotal, self.minimum)

    @property
    def total(self) -> float:
        amount = self.before_discounts
        for percent in (self.member_off, self.birthday_off, self.discount, self.coupon_percent):
            amount *= 1 - percent / 100
        amount = max(0.0, amount - self.coupon_amount)
        if self.round_to:
            amount = math.floor(amount / self.round_to + 1e-9) * self.round_to
        return round(amount, 2)

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
        for label, percent in (
            (f"Member {self.member}", self.member_off),
            ("Happy birthday!", self.birthday_off),
            ("Discount", self.discount),
            (f"Coupon {self.coupon}", self.coupon_percent),
        ):
            if percent and (self.member or label in ("Discount",) or label.startswith("Coupon")):
                rows += f"<tr><td>{escape(label)} −{percent:g}%</td><td></td></tr>"
        if self.coupon_amount:
            rows += (
                f"<tr><td>Coupon {escape(self.coupon)}</td><td align='right'>"
                f"−{self.currency}{self.coupon_amount:.2f}</td></tr>"
            )
        if self.round_to:
            rows += "<tr><td>Small change dropped</td><td></td></tr>"
        rows += f"<tr><td>Paid by</td><td align='right'>{escape(self.payment)}</td></tr>"
        return (
            "<div style='color:#111'>"
            f"<h2>YTKTV · {escape(self.room)}</h2>"
            f"<p>{escape(self.guest)}<br>{time.strftime('%Y-%m-%d %H:%M')}</p>"
            f"<table width='100%' cellpadding='4'>{rows}"
            f"<tr><td><b>Total</b></td><td align='right'><b>{self.currency}{self.total:.2f}"
            "</b></td></tr></table></div>"
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
    package = store.session_package(room_id)
    if package is not None:
        # The package pays for its own time; only time beyond it is charged by the hour.
        includes = f" · {package.includes}" if package.includes else ""
        result.lines.append((f"Package · {package.name}{includes}", round(package.price, 2)))
        minutes = max(0.0, minutes - package.minutes)
    if minutes or package is None:
        hours = f"{int(minutes // 60)}h {int(minutes % 60):02d}m"
        label = "Extra time" if package is not None else "Room"
        result.lines.append(
            (f"{label} · {hours} at {result.currency}{rate:g}/h", round(rate * minutes / 60, 2))
        )
    for order in store.orders(room_id):
        if order.status != "cancelled":
            result.lines.append((f"{order.name} × {order.qty}", round(order.price * order.qty, 2)))
    return result
