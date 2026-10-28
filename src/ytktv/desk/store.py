"""The desk's rooms, kept in SQLite."""

from __future__ import annotations

import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ytktv.rooms import crypto

CODE_SECONDS = 300  # a pairing code works for five minutes, once


@dataclass
class Room:
    room_id: str
    name: str
    last_seen: float
    is_open: bool = False
    guest: str = ""
    ends_at: float | None = None

    def message(self) -> dict[str, object]:
        """What the room is told about itself."""
        if not self.is_open:
            return {"type": "close"}
        return {"type": "open", "guest": self.guest, "ends_at": self.ends_at}


class DeskStore:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._codes: dict[str, float] = {}
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
                " key TEXT NOT NULL, last_seen REAL NOT NULL DEFAULT 0)"
            )
            self._db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (room_id TEXT PRIMARY KEY, guest TEXT,"
                " ends_at REAL)"
            )
            row = self._db.execute("SELECT v FROM meta WHERE k='private_key'").fetchone()
            if row is None:
                row = (crypto.new_private_key(),)
                self._db.execute("INSERT INTO meta VALUES ('private_key', ?)", row)
            self._db.commit()
        self.private_key: str = row[0]
        self.public_key = crypto.public_key(self.private_key)
        self.desk_id = crypto.desk_id(self.public_key)
        self.fingerprint = crypto.fingerprint(self.public_key)

    def new_code(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        code = f"{secrets.randbelow(1_000_000):06d}"
        with self._lock:
            self._codes = {c: t for c, t in self._codes.items() if t > now}
            self._codes[code] = now + CODE_SECONDS
        return code

    def pair(self, code: str, name: str, now: float | None = None) -> tuple[Room, str]:
        """Use up *code* and add a room. Raises KeyError for a wrong or expired code."""
        now = time.time() if now is None else now
        with self._lock:
            expires = self._codes.pop(code, 0.0)
            if expires <= now:
                raise KeyError(code)
            room_id, key = secrets.token_hex(8), secrets.token_urlsafe(24)
            name = (
                name or f"Room {self._db.execute('SELECT COUNT(*) FROM rooms').fetchone()[0] + 1}"
            )
            self._db.execute("INSERT INTO rooms VALUES (?, ?, ?, ?)", (room_id, name, key, now))
            self._db.commit()
        return Room(room_id, name, now), key

    def key(self, room_id: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT key FROM rooms WHERE id=?", (room_id,)).fetchone()
        return None if row is None else str(row[0])

    def sign(self, data: bytes) -> str:
        return crypto.sign(self.private_key, data)

    def seen(self, room_id: str, now: float | None = None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE rooms SET last_seen=? WHERE id=?",
                (time.time() if now is None else now, room_id),
            )
            self._db.commit()

    def rename(self, room_id: str, name: str) -> None:
        with self._lock:
            self._db.execute("UPDATE rooms SET name=? WHERE id=?", (name, room_id))
            self._db.commit()

    def remove(self, room_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM rooms WHERE id=?", (room_id,))
            self._db.execute("DELETE FROM sessions WHERE room_id=?", (room_id,))
            self._db.commit()

    def rooms(self) -> list[Room]:
        with self._lock:
            rows = self._db.execute(
                "SELECT r.id, r.name, r.last_seen, s.room_id IS NOT NULL, COALESCE(s.guest, ''),"
                " s.ends_at FROM rooms r LEFT JOIN sessions s ON s.room_id = r.id ORDER BY r.rowid"
            )
            return [Room(a, b, c, bool(d), e, f) for a, b, c, d, e, f in rows.fetchall()]

    def room(self, room_id: str) -> Room | None:
        return next((r for r in self.rooms() if r.room_id == room_id), None)

    def open_room(
        self, room_id: str, guest: str, minutes: int | None, now: float | None = None
    ) -> None:
        now = time.time() if now is None else now
        ends_at = None if minutes is None else now + minutes * 60
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)", (room_id, guest, ends_at)
            )
            self._db.commit()

    def extend(self, room_id: str, minutes: int, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            # A room whose time already ran out gets the extra time from now.
            self._db.execute(
                "UPDATE sessions SET ends_at = MAX(ends_at, ?) + ? WHERE room_id=?"
                " AND ends_at IS NOT NULL",
                (now, minutes * 60, room_id),
            )
            self._db.commit()

    def close_room(self, room_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM sessions WHERE room_id=?", (room_id,))
            self._db.commit()
