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
    heat: list[list[float]]  # the same room-hours split by weekday (Monday first), then hour
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
    heat = [[0.0] * 24 for _ in range(7)]
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
            local = time.localtime(start)
            busy[local.tm_hour] += (end - start) / 3600
            heat[local.tm_wday][local.tm_hour] += (end - start) / 3600
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
        heat=[[round(h, 2) for h in row] for row in heat],
        weekdays=[round(w, 2) for w in weekdays],
        top_songs=songs.most_common(20),
        top_items=top_items[:20],
        rooms=sorted(rooms.items(), key=lambda pair: -pair[1]),
        payments=sorted(payments.items(), key=lambda pair: -pair[1]),
    )


def last_days(store: DeskStore, days: int, now: float | None = None) -> list[Visit]:
    now = time.time() if now is None else now
    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=days - 1)
    return store.history(start.timestamp(), now + 1)


# Periods for the dashboard. The fixed ones end now; "Custom range" uses the two dates picked.
DASHBOARD_PERIODS = (
    "Today",
    "This week",
    "This month",
    "Last 7 days",
    "Last 30 days",
    "Last 90 days",
    "Custom range",
)


def period_span(
    period: str, now: float, first: date | None = None, last: date | None = None
) -> tuple[float, float]:
    """The (start, end) timestamps of a dashboard period. A custom range includes both dates."""
    today = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "Custom range" and first and last:
        if last < first:
            first, last = last, first
        start = datetime(first.year, first.month, first.day)
        end = datetime(last.year, last.month, last.day) + timedelta(days=1)
        return start.timestamp(), end.timestamp()
    if period == "This week":
        start = today - timedelta(days=today.weekday())
    elif period == "This month":
        start = today.replace(day=1)
    elif period in RANGES:
        start = today - timedelta(days=RANGES[period] - 1)
    else:  # Today
        start = today
    return start.timestamp(), now + 1


def utilisation(
    visits: list[Visit], rooms: list[str], start: float, end: float
) -> list[tuple[str, float, float]]:
    """How much of the period each room was in use, as (room, hours, share), busiest first.

    Only the part of each session inside the period counts, and a period that runs into the
    future is cut at its last session, so "this month" is not diluted by days still to come.
    """
    used = dict.fromkeys(rooms, 0.0)
    for v in visits:
        overlap = min(v.closed_at, end) - max(v.opened_at, start)
        if overlap > 0:
            used[v.room] = used.get(v.room, 0.0) + overlap / 3600
    span = (min(end, max((v.closed_at for v in visits), default=end)) - start) / 3600
    rows = [
        (room, round(h, 2), min(1.0, h / span) if span > 0 else 0.0) for room, h in used.items()
    ]
    return sorted(rows, key=lambda row: -row[1])


def export_dashboard_csv(
    found: Insights, rooms: list[tuple[str, float, float]], path: Path | str
) -> None:
    """The dashboard's tables, one after another, in a single spreadsheet."""
    with open(path, "w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(("Top songs", "Times sung"))
        writer.writerows(found.top_songs)
        writer.writerow(())
        writer.writerow(("Best-selling items", "Quantity", "Takings"))
        writer.writerows((n, q, f"{a:.2f}") for n, q, a in found.top_items)
        writer.writerow(())
        writer.writerow(("Room", "Hours in use", "Utilisation"))
        writer.writerows((r, f"{h:.2f}", f"{s:.0%}") for r, h, s in rooms)
        writer.writerow(())
        writer.writerow(("Weekday", *(f"{h:02d}" for h in range(24))))
        writer.writerows(
            (day, *(f"{h:.2f}" for h in row)) for day, row in zip(WEEKDAYS, found.heat, strict=True)
        )
