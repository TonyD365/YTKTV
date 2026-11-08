"""Room prices by time of day: happy hours, weekend surcharges and late-night packages.

Pure and Qt-free. The rules are kept as JSON in the ``price_rules`` setting, so older
databases need no new tables.

How a stay is priced:

- The billed minutes (already rounded as set: minute, hour or block) are laid out on the local
  wall clock from the moment the room opened. Wall-clock time is used throughout, so a DST
  change is ignored: a minute is always one minute of the clock.
- Each minute takes the first active rule (in list order) whose weekdays, time window and room
  types match; minutes no rule matches are charged at the room's own hourly rate.
- A window whose end is not after its start crosses midnight (22:00–02:00); its weekdays are
  the days it *starts* on, so "Fri 22:00–02:00" covers Saturday 01:00. Start equal to end
  means the whole day.
- ``percent`` changes the room's rate (-30 is 30% off, +20 a 20% surcharge); ``rate`` sets a
  fixed hourly price.
- ``package`` charges its price once for every window a stay touches, however much of the
  window the stay uses; time outside the window is priced as usual. So a stay from 23:00 to
  02:00 with a 00:00–06:00 package pays one hour by the hour plus the package.

Discounts, minimum spend, service charge and tax are applied to the whole bill afterwards, as
before.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

KINDS = {
    "percent": "Percent on the hourly rate",
    "rate": "Fixed hourly rate",
    "package": "Fixed price for the window",
}
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
WEEKDAYS = (0, 1, 2, 3, 4)
WEEKEND = (5, 6)
EVERY_DAY = (0, 1, 2, 3, 4, 5, 6)


@dataclass
class PriceRule:
    name: str
    days: tuple[int, ...] = EVERY_DAY  # 0 = Monday; the days a window starts on
    start: int = 0  # minutes after midnight
    end: int = 0  # minutes after midnight; not after start = crosses midnight
    kind: str = "percent"  # see KINDS
    value: float = 0.0
    room_types: tuple[str, ...] = ()  # empty = every room
    active: bool = True

    def window_start(self, moment: datetime, room_type: str) -> datetime | None:
        """When the window holding this wall-clock minute began, or None if it doesn't apply."""
        if not self.active or (self.room_types and room_type not in self.room_types):
            return None
        minute = moment.hour * 60 + moment.minute
        midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
        today = midnight + timedelta(minutes=self.start)
        if self.start < self.end:
            inside = self.start <= minute < self.end
            return today if inside and moment.weekday() in self.days else None
        if minute >= self.start:
            return today if moment.weekday() in self.days else None
        if minute < self.end or self.start == self.end:
            # Belongs to the window that started yesterday.
            return today - timedelta(days=1) if (moment.weekday() - 1) % 7 in self.days else None
        return None

    def label(self, currency: str) -> str:
        days = days_text(self.days)
        hours = f"{clock(self.start)}–{clock(self.end)}"
        if self.kind == "percent":
            price = f"{self.value:+g}%"
        elif self.kind == "rate":
            price = f"{currency}{self.value:g}/h"
        else:
            price = f"{currency}{self.value:g} package"
        types = f" · {', '.join(self.room_types)}" if self.room_types else ""
        return f"{self.name} · {days} {hours} · {price}{types}"


@dataclass
class Part:
    """A stretch of a stay charged one way."""

    minutes: float
    amount: float
    rate: float | None = None  # hourly; None for a package
    rule: str = ""  # "" = the room's own rate
    package: bool = False
    price: float = 0.0  # a package's price per window
    starts: list[datetime] = field(default_factory=list)

    def text(self, currency: str, label: str = "Room") -> str:
        hours = f"{int(self.minutes // 60)}h {int(self.minutes % 60):02d}m"
        if self.package:
            count = f"{len(self.starts)} × " if len(self.starts) > 1 else ""
            return f"{label} · {count}{self.rule} · {hours}"
        rule = f" · {self.rule}" if self.rule else ""
        return f"{label} · {hours} at {currency}{self.rate:g}/h{rule}"


def clock(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def days_text(days: tuple[int, ...]) -> str:
    chosen = tuple(sorted(set(days)))
    named = {EVERY_DAY: "Every day", WEEKDAYS: "Mon–Fri", WEEKEND: "Sat–Sun"}
    return named.get(chosen) or ", ".join(DAY_NAMES[d] for d in chosen) or "No days"


def price_stay(
    opened: datetime, minutes: float, rate: float, rules: list[PriceRule], room_type: str = ""
) -> list[Part]:
    """Split a stay of ``minutes`` starting at the naive local time ``opened`` into priced parts.

    Parts come in the order they are first reached. With no matching rule this is one part at
    ``rate``, exactly the old single "Room" line.
    """
    parts: dict[str, Part] = {}
    whole = math.ceil(minutes - 1e-9)
    for index in range(whole):
        weight = min(1.0, minutes - index)
        moment = opened + timedelta(minutes=index)
        rule, began = None, None
        for candidate in rules:
            began = candidate.window_start(moment, room_type)
            if began is not None:
                rule = candidate
                break
        if rule is None:
            part = parts.setdefault("", Part(0.0, 0.0, rate))
        elif rule.kind == "package":
            part = parts.setdefault(
                f"package:{rule.name}", Part(0.0, 0.0, None, rule.name, True, rule.value)
            )
            if began not in part.starts and began is not None:
                part.starts.append(began)
        else:
            hourly = rule.value if rule.kind == "rate" else rate * (1 + rule.value / 100)
            hourly = max(0.0, round(hourly, 2))
            part = parts.setdefault(f"{rule.name}:{hourly}", Part(0.0, 0.0, hourly, rule.name))
        part.minutes += weight
    for part in parts.values():
        if part.package:
            part.amount = round(part.price * len(part.starts), 2)
        else:
            part.amount = round((part.rate or 0.0) * part.minutes / 60, 2)
    if not parts:
        return [Part(0.0, 0.0, rate)]
    return list(parts.values())


def rules_to_json(rules: list[PriceRule]) -> str:
    return json.dumps([asdict(rule) for rule in rules])


def rules_from_json(text: str) -> list[PriceRule]:
    """The saved rules; anything unreadable is skipped rather than breaking the till."""
    try:
        raw = json.loads(text or "[]")
    except ValueError:
        return []
    rules = []
    for item in raw if isinstance(raw, list) else []:
        try:
            rule = PriceRule(
                str(item["name"]),
                tuple(int(d) % 7 for d in item.get("days", EVERY_DAY)),
                int(item.get("start", 0)) % 1440,
                int(item.get("end", 0)) % 1440,
                str(item.get("kind", "percent")),
                float(item.get("value", 0)),
                tuple(str(t) for t in item.get("room_types", ())),
                bool(item.get("active", True)),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if rule.kind in KINDS:
            rules.append(rule)
    return rules
