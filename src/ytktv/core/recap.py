"""The end-of-session recap: what a room sang between the desk opening and closing it.

Only what the room already knows is counted: the songs that finished in Sung, who
sang them (the queue's singer names), how long each played, and the scores. The
recap's phone page is reached through a link that carries a random token, made
fresh for every session; the next session starting makes the old link stop working.
"""

from __future__ import annotations

import hmac
import secrets
import threading
from collections import Counter
from html import escape
from typing import Any


class SessionRecap:
    """Collects one session's songs and scores, and hands out its summary."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._songs: list[dict[str, Any]] = []
        self._best: dict[str, Any] | None = None
        self._best_duet: dict[str, Any] | None = None
        self._summary: dict[str, Any] | None = None
        self.token = ""

    def start(self) -> None:
        """A new session: forget the last one, and stop its link from working."""
        with self._lock:
            self._songs.clear()
            self._best = self._best_duet = self._summary = None
            self.token = ""

    def song(self, title: str, singer: str, seconds: float) -> None:
        with self._lock:
            self._songs.append({"title": title, "singer": singer, "seconds": max(0.0, seconds)})

    def score(self, points: int, title: str, singer: str, duet: bool = False) -> None:
        entry = {"points": int(points), "title": title, "singer": singer}
        with self._lock:
            if self._best is None or entry["points"] > self._best["points"]:
                self._best = entry
            if duet and (self._best_duet is None or entry["points"] > self._best_duet["points"]):
                self._best_duet = entry

    def finish(self) -> dict[str, Any] | None:
        """The session ended: its summary (None when nothing was sung), with a new token."""
        with self._lock:
            if not self._songs:
                self._summary, self.token = None, ""
                return None
            singers = Counter(s["singer"] for s in self._songs if s["singer"])
            top = singers.most_common(1)
            self.token = secrets.token_urlsafe(24)
            self._summary = {
                "songs": len(self._songs),
                "seconds": int(sum(s["seconds"] for s in self._songs)),
                "top_singer": {"name": top[0][0], "songs": top[0][1]} if top else None,
                "best_score": self._best,
                "best_duet": self._best_duet,
                "titles": [s["title"] for s in self._songs],
                # Rooms do not record singing yet; the page lists links only when present.
                "recordings": [],
            }
            return {**self._summary, "token": self.token}

    def lookup(self, token: str) -> dict[str, Any] | None:
        """The summary for a phone that scanned the code, if *token* is still valid."""
        with self._lock:
            secret, summary = self.token, self._summary
        if not secret or summary is None or not hmac.compare_digest(token, secret):
            return None
        return summary


def duration_text(seconds: int) -> str:
    hours, rest = divmod(max(0, int(seconds)), 3600)
    minutes = rest // 60
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def lines(summary: dict[str, Any]) -> list[tuple[str, str]]:
    """The recap as (label, value) rows, shared by the TV card and the phone page."""
    rows = [
        ("Songs sung", str(summary["songs"])),
        ("Time singing", duration_text(summary["seconds"])),
    ]
    top = summary.get("top_singer")
    if top:
        rows.append(("Sang the most", f"{top['name']} ({top['songs']} songs)"))
    best = summary.get("best_score")
    if best:
        who = f" by {best['singer']}" if best["singer"] else ""
        rows.append(("Highest score", f"{best['points']} - {best['title']}{who}"))
    duet = summary.get("best_duet")
    if duet:
        rows.append(("Best duet", f"{duet['points']} - {duet['title']}"))
    return rows


def page(summary: dict[str, Any]) -> str:
    """The phone page behind the QR code (everything escaped; no scripts)."""
    rows = "".join(
        f"<tr><th>{escape(label)}</th><td>{escape(value)}</td></tr>"
        for label, value in lines(summary)
    )
    titles = "".join(f"<li>{escape(title)}</li>" for title in summary.get("titles", []))
    recordings = "".join(
        f'<li><a href="{escape(r["url"])}" download>{escape(r["name"])}</a></li>'
        for r in summary.get("recordings", [])
    )
    downloads = f"<h2>Recordings</h2><ul>{recordings}</ul>" if recordings else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tonight's recap</title>
<style>
body {{ margin: 0; padding: 24px 16px; background: #07040f; color: #fff;
  font-family: system-ui, sans-serif; }}
h1 {{ color: #ff4fd8; text-shadow: 0 0 12px #ff4fd8; font-size: 26px; }}
h2 {{ color: #4ff0ff; font-size: 18px; margin-top: 28px; }}
table {{ width: 100%; border-collapse: collapse; }}
th {{ text-align: left; color: #9a93b8; font-weight: 500; padding: 8px 8px 8px 0; }}
td {{ padding: 8px 0; font-weight: 700; }}
li {{ margin: 4px 0; }}
</style></head>
<body><h1>Tonight's recap</h1><table>{rows}</table>
<h2>Songs</h2><ol>{titles}</ol>{downloads}
<p style="color:#9a93b8">Thanks for singing!</p></body></html>"""
