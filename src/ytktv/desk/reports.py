"""Takings over a day, a week or a month: the totals behind the chart, and a CSV export."""

from __future__ import annotations

import csv
import time
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from ytktv.desk.store import DeskStore, Visit

PERIODS = ("Day", "Week", "Month")
COLUMNS = ("Closed", "Room", "Guest", "Minutes", "Songs", "Paid by", "Total", "Items")


def period_buckets(day: date, period: str) -> list[tuple[str, float, float]]:
    """The bars of the chart, as (label, start, end): hours of a day, days of a week or month."""
    if period == "Day":
        start = datetime(day.year, day.month, day.day)
        return [
            (
                f"{h:02d}",
                (start + timedelta(hours=h)).timestamp(),
                (start + timedelta(hours=h + 1)).timestamp(),
            )
            for h in range(24)
        ]
    if period == "Week":
        first = day - timedelta(days=day.weekday())  # weeks start on Monday
        days = [first + timedelta(days=i) for i in range(7)]
    else:
        first = day.replace(day=1)
        following = (first + timedelta(days=32)).replace(day=1)
        days = [first + timedelta(days=i) for i in range((following - first).days)]
    buckets = []
    for d in days:
        start = datetime(d.year, d.month, d.day)
        label = d.strftime("%a") if period == "Week" else str(d.day)
        buckets.append((label, start.timestamp(), (start + timedelta(days=1)).timestamp()))
    return buckets


def takings(visits: list[Visit], buckets: list[tuple[str, float, float]]) -> list[float]:
    return [sum(v.total for v in visits if start <= v.closed_at < end) for _, start, end in buckets]


def visits_in(store: DeskStore, day: date, period: str) -> list[Visit]:
    buckets = period_buckets(day, period)
    return store.history(buckets[0][1], buckets[-1][2])


def export_csv(visits: list[Visit], path: Path | str) -> None:
    """One row per session. The byte-order mark lets Excel read names in any language."""
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(COLUMNS)
        for v in visits:
            writer.writerow(
                (
                    time.strftime("%Y-%m-%d %H:%M", time.localtime(v.closed_at)),
                    v.room,
                    v.guest,
                    int((v.closed_at - v.opened_at) // 60),
                    len(v.songs),
                    v.payment,
                    f"{v.total:.2f}",
                    "; ".join(f"{text} {amount:.2f}" for text, amount in v.lines),
                )
            )


# -- the dashboard ---------------------------------------------------------------

RANGES = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}
ROOM_LINES = ("Room ·", "Package ·", "Extra time ·")  # bill lines that pay for the room
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Insights:
    sessions: int
    takings: float
    hours: float
    busy_hours: list[float]  # how many rooms were in use, summed over the days, per hour of day
    weekdays: list[float]  # takings per weekday, Monday first
    top_songs: list[tuple[str, int]]
    top_items: list[tuple[str, int, float]]  # name, how many, takings
    rooms: list[tuple[str, float]]  # takings per room, best first
    payments: list[tuple[str, float]]

    @property
    def per_session(self) -> float:
        return self.takings / self.sessions if self.sessions else 0.0


def insights(visits: list[Visit]) -> Insights:
    busy = [0.0] * 24
    weekdays = [0.0] * 7
    songs: Counter[str] = Counter()
    items: dict[str, tuple[int, float]] = {}
    rooms: dict[str, float] = {}
    payments: dict[str, float] = {}
    for v in visits:
        # Spread the session over the hours of the day it covered.
        start = v.opened_at
        while start < v.closed_at:
            hour_start = start - (start % 3600)
            end = min(v.closed_at, hour_start + 3600)
            busy[time.localtime(start).tm_hour] += (end - start) / 3600
            start = end
        weekdays[time.localtime(v.closed_at).tm_wday] += v.total
        songs.update(v.songs)
        rooms[v.room] = rooms.get(v.room, 0.0) + v.total
        payments[v.payment] = payments.get(v.payment, 0.0) + v.total
        for text, amount in v.lines:
            if text.startswith(ROOM_LINES) or " × " not in text:
                continue
            name, qty = text.rsplit(" × ", 1)
            count, money = items.get(name, (0, 0.0))
            items[name] = (count + (int(qty) if qty.isdigit() else 1), money + amount)
    top_items = sorted(((n, q, a) for n, (q, a) in items.items()), key=lambda i: -i[1])
    return Insights(
        sessions=len(visits),
        takings=round(sum(v.total for v in visits), 2),
        hours=sum(v.closed_at - v.opened_at for v in visits) / 3600,
        busy_hours=[round(b, 2) for b in busy],
        weekdays=[round(w, 2) for w in weekdays],
        top_songs=songs.most_common(10),
        top_items=top_items[:10],
        rooms=sorted(rooms.items(), key=lambda pair: -pair[1]),
        payments=sorted(payments.items(), key=lambda pair: -pair[1]),
    )


def last_days(store: DeskStore, days: int, now: float | None = None) -> list[Visit]:
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    return store.history(start.timestamp(), now + 1)
