"""Whether a room bound to the staff terminal is open, and until when."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

WARN_AT = 10 * 60  # seconds left when the room gets a one-time warning


@dataclass
class RoomState:
    closed: bool = True
    guest: str = ""
    ends_at: float | None = None  # desk clock; None = no time limit
    locked: bool = False  # the desk paused the room for a while; the session goes on

    def apply(self, message: dict[str, Any]) -> bool:
        """Take a (verified) desk message; True when it changed the room."""
        kind = message.get("type")
        if kind == "open":
            ends = message.get("ends_at")
            self.closed = False
            self.guest = str(message.get("guest") or "")
            self.ends_at = float(ends) if ends is not None else None
            return True
        if kind == "close":
            self.closed, self.guest, self.ends_at, self.locked = True, "", None, False
            return True
        if kind in ("lock", "unlock"):
            self.locked = kind == "lock"
            return True
        return False

    def seconds_left(self, now: float | None = None) -> float | None:
        if self.closed or self.ends_at is None:
            return None
        return self.ends_at - (time.time() if now is None else now)


def format_left(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    return f"{hours}:{rest // 60:02d}:{rest % 60:02d}" if hours else f"{rest // 60}:{rest % 60:02d}"
