"""The desk's rooms, kept in SQLite."""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

CODE_SECONDS = 300  # a pairing code works for five minutes, once


@dataclass
class Room:
    room_id: str
    name: str
    last_seen: float


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class DeskStore:
    def __init__(self, path: Path | str = ":memory:") -> None:
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._lock = threading.Lock()
        self._codes: dict[str, float] = {}
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
                " key_hash TEXT NOT NULL, last_seen REAL NOT NULL DEFAULT 0)"
            )
            self._db.commit()

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
            self._db.execute(
                "INSERT INTO rooms VALUES (?, ?, ?, ?)", (room_id, name, _hash(key), now)
            )
            self._db.commit()
        return Room(room_id, name, now), key

    def verify(self, room_id: str, key: str) -> bool:
        with self._lock:
            row = self._db.execute("SELECT key_hash FROM rooms WHERE id=?", (room_id,)).fetchone()
        return row is not None and secrets.compare_digest(row[0], _hash(key))

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
            self._db.commit()

    def rooms(self) -> list[Room]:
        with self._lock:
            rows = self._db.execute("SELECT id, name, last_seen FROM rooms ORDER BY rowid")
            return [Room(*row) for row in rows.fetchall()]
