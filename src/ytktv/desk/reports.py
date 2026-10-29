"""Takings over a day, a week or a month: the totals behind the chart, and a CSV export."""

from __future__ import annotations

import csv
import time
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
