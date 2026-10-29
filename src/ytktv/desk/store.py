"""The desk's rooms, kept in SQLite."""

from __future__ import annotations

import contextlib
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ytktv.rooms import crypto

CODE_SECONDS = 300  # a pairing code works for five minutes, once


@dataclass
class Product:
    product_id: int
    name: str
    category: str
    price: float
    active: bool = True
    stock: int | None = None  # None = never runs out


@dataclass
class Order:
    order_id: int
    room_id: str
    name: str
    price: float
    qty: int
    status: str  # pending, delivered or cancelled
    created: float


@dataclass
class Call:
    call_id: int
    room_id: str
    kind: str
    note: str
    created: float


@dataclass
class Booking:
    booking_id: int
    room_id: str
    starts: float
    minutes: int | None
    guest: str = ""
    contact: str = ""
    note: str = ""
    status: str = "booked"  # booked, arrived, cancelled or no_show


@dataclass
class Visit:
    """A closed session, kept for the records."""

    visit_id: int
    room: str
    guest: str
    opened_at: float
    closed_at: float
    total: float
    lines: list[tuple[str, float]]
    songs: list[str]


@dataclass
class Room:
    room_id: str
    name: str
    last_seen: float
    is_open: bool = False
    guest: str = ""
    ends_at: float | None = None
    opened_at: float = 0.0
    rate: float | None = None  # this room's price per hour; None = the desk's default
    room_type: str = "Medium"
    capacity: int = 6
    state: str = "ready"  # ready, cleaning or maintenance (while closed)

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
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(rooms)")}
            if columns and "key" not in columns:
                # Rooms paired by the first test version kept only a hash of their key,
                # which the signed handshake cannot use: they have to pair again.
                self._db.execute("DROP TABLE rooms")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS rooms (id TEXT PRIMARY KEY, name TEXT NOT NULL,"
                " key TEXT NOT NULL, last_seen REAL NOT NULL DEFAULT 0)"
            )
            self._db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT)")
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (room_id TEXT PRIMARY KEY, guest TEXT,"
                " ends_at REAL, opened_at REAL NOT NULL DEFAULT 0)"
            )
            for table, column in (
                ("sessions", "opened_at REAL NOT NULL DEFAULT 0"),
                ("rooms", "rate REAL"),
                ("sessions", "songs TEXT NOT NULL DEFAULT '[]'"),
                ("rooms", "room_type TEXT NOT NULL DEFAULT 'Medium'"),
                ("rooms", "capacity INTEGER NOT NULL DEFAULT 6"),
                ("rooms", "state TEXT NOT NULL DEFAULT 'ready'"),
                ("products", "stock INTEGER"),
            ):
                with contextlib.suppress(sqlite3.OperationalError):  # added later
                    self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
            self._db.executescript(
                "CREATE TABLE IF NOT EXISTS products (id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
                " category TEXT NOT NULL DEFAULT '', price REAL NOT NULL, active INTEGER NOT NULL"
                " DEFAULT 1, stock INTEGER);"
                "CREATE TABLE IF NOT EXISTS orders (id INTEGER PRIMARY KEY, room_id TEXT NOT NULL,"
                " name TEXT NOT NULL, price REAL NOT NULL, qty INTEGER NOT NULL, status TEXT NOT"
                " NULL DEFAULT 'pending', created REAL NOT NULL);"
                "CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, room_id TEXT NOT NULL,"
                " kind TEXT NOT NULL, note TEXT NOT NULL DEFAULT '', created REAL NOT NULL,"
                " done INTEGER NOT NULL DEFAULT 0);"
                "CREATE TABLE IF NOT EXISTS bookings (id INTEGER PRIMARY KEY,"
                " room_id TEXT NOT NULL, starts REAL NOT NULL, minutes INTEGER,"
                " guest TEXT NOT NULL DEFAULT '',"
                " contact TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',"
                " status TEXT NOT NULL DEFAULT 'booked');"
                "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, room_id TEXT NOT NULL,"
                " room TEXT NOT NULL, guest TEXT NOT NULL, opened_at REAL NOT NULL,"
                " closed_at REAL NOT NULL, total REAL NOT NULL, bill TEXT NOT NULL,"
                " songs TEXT NOT NULL);"
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
            self._db.execute(
                "INSERT INTO rooms (id, name, key, last_seen) VALUES (?, ?, ?, ?)",
                (room_id, name, key, now),
            )
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
                " s.ends_at, COALESCE(s.opened_at, 0), r.rate, r.room_type, r.capacity, r.state"
                " FROM rooms r LEFT JOIN sessions s ON s.room_id = r.id ORDER BY r.rowid"
            )
            return [
                Room(a, b, c, bool(d), e, f, g, h, i, j, k)
                for a, b, c, d, e, f, g, h, i, j, k in rows
            ]

    def room(self, room_id: str) -> Room | None:
        return next((r for r in self.rooms() if r.room_id == room_id), None)

    def open_room(
        self, room_id: str, guest: str, minutes: int | None, now: float | None = None
    ) -> None:
        now = time.time() if now is None else now
        ends_at = None if minutes is None else now + minutes * 60
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO sessions (room_id, guest, ends_at, opened_at)"
                " VALUES (?, ?, ?, ?)",
                (room_id, guest, ends_at, now),
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

    def close_room(self, room_id: str, bill: Any = None, now: float | None = None) -> None:
        """End the session; its orders and calls are settled with it.

        With *bill* (a billing.Bill) the session is kept in the records.
        """
        room = self.room(room_id)
        with self._lock:
            if bill is not None and room is not None and room.is_open:
                songs = self._db.execute(
                    "SELECT songs FROM sessions WHERE room_id=?", (room_id,)
                ).fetchone()
                self._db.execute(
                    "INSERT INTO history (room_id, room, guest, opened_at, closed_at, total, bill,"
                    " songs) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        room_id,
                        room.name,
                        room.guest,
                        room.opened_at,
                        time.time() if now is None else now,
                        bill.total,
                        json.dumps(bill.lines),
                        songs[0] if songs else "[]",
                    ),
                )
            self._db.execute("DELETE FROM sessions WHERE room_id=?", (room_id,))
            self._db.execute("DELETE FROM orders WHERE room_id=?", (room_id,))
            self._db.execute("UPDATE rooms SET state='cleaning' WHERE id=?", (room_id,))
            self._db.execute("UPDATE calls SET done=1 WHERE room_id=?", (room_id,))
            self._db.commit()

    def note_song(self, room_id: str, title: str) -> None:
        """Remember what an open room sang, once per song."""
        title = title.strip()[:200]
        if not title:
            return
        with self._lock:
            row = self._db.execute(
                "SELECT songs FROM sessions WHERE room_id=?", (room_id,)
            ).fetchone()
            if row is None:
                return
            songs = json.loads(row[0] or "[]")
            if not songs or songs[-1] != title:
                songs.append(title)
                self._db.execute(
                    "UPDATE sessions SET songs=? WHERE room_id=?", (json.dumps(songs), room_id)
                )
                self._db.commit()

    def now_singing(self, room_id: str) -> str:
        with self._lock:
            row = self._db.execute(
                "SELECT songs FROM sessions WHERE room_id=?", (room_id,)
            ).fetchone()
        songs = json.loads(row[0]) if row and row[0] else []
        return str(songs[-1]) if songs else ""

    def history(self, start: float, end: float) -> list[Visit]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, room, guest, opened_at, closed_at, total, bill, songs FROM history"
                " WHERE closed_at >= ? AND closed_at < ? ORDER BY closed_at",
                (start, end),
            ).fetchall()
        return [
            Visit(a, b, c, d, e, f, [tuple(x) for x in json.loads(g)], json.loads(h))
            for a, b, c, d, e, f, g, h in rows
        ]

    # -- bookings ---------------------------------------------------------------

    def book(self, booking: Booking) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO bookings (room_id, starts, minutes, guest, contact, note)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    booking.room_id,
                    booking.starts,
                    booking.minutes,
                    booking.guest[:80],
                    booking.contact[:80],
                    booking.note[:200],
                ),
            )
            self._db.commit()
            return int(cursor.lastrowid or 0)

    def bookings(self, start: float, end: float, live_only: bool = False) -> list[Booking]:
        """Bookings that start between *start* and *end*."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, room_id, starts, minutes, guest, contact, note, status FROM bookings"
                " WHERE starts >= ? AND starts < ?"
                + (" AND status='booked'" if live_only else "")
                + " ORDER BY starts",
                (start, end),
            ).fetchall()
        return [Booking(*row) for row in rows]

    def set_booking_status(self, booking_id: int, status: str) -> None:
        with self._lock:
            self._db.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
            self._db.commit()

    def clashes(
        self, room_id: str, starts: float, minutes: int | None, skip: int = 0
    ) -> list[Booking]:
        """Live bookings for *room_id* that overlap a stay from *starts* (open-ended: 12 h)."""
        end = starts + (minutes or 12 * 60) * 60
        found = []
        for booking in self.bookings(starts - 24 * 3600, end, live_only=True):
            if booking.room_id != room_id or booking.booking_id == skip:
                continue
            other_end = booking.starts + (booking.minutes or 12 * 60) * 60
            if booking.starts < end and starts < other_end:
                found.append(booking)
        return found

    def set_state(self, room_id: str, state: str) -> None:
        """ready, cleaning or maintenance."""
        with self._lock:
            self._db.execute("UPDATE rooms SET state=? WHERE id=?", (state, room_id))
            self._db.commit()

    def set_type(self, room_id: str, room_type: str, capacity: int) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE rooms SET room_type=?, capacity=? WHERE id=?",
                (room_type, capacity, room_id),
            )
            self._db.commit()

    def change_room(self, from_id: str, to_id: str) -> None:
        """Move a party, with its time, orders, calls and songs, to another room."""
        with self._lock:
            busy = self._db.execute("SELECT 1 FROM sessions WHERE room_id=?", (to_id,)).fetchone()
            if busy is not None:
                raise ValueError("that room is in use")
            for table in ("sessions", "orders", "calls"):
                self._db.execute(f"UPDATE {table} SET room_id=? WHERE room_id=?", (to_id, from_id))
            self._db.execute("UPDATE rooms SET state='cleaning' WHERE id=?", (from_id,))
            self._db.execute("UPDATE rooms SET state='ready' WHERE id=?", (to_id,))
            self._db.commit()

    def set_rate(self, room_id: str, rate: float | None) -> None:
        with self._lock:
            self._db.execute("UPDATE rooms SET rate=? WHERE id=?", (rate, room_id))
            self._db.commit()

    # -- desk settings --------------------------------------------------------

    def setting(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._db.execute("SELECT v FROM meta WHERE k=?", (f"set:{key}",)).fetchone()
        return default if row is None else str(row[0])

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"set:{key}", value))
            self._db.commit()

    # -- products, orders and service calls -----------------------------------

    def products(self, active_only: bool = False) -> list[Product]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, name, category, price, active, stock FROM products"
                + (" WHERE active=1" if active_only else "")
                + " ORDER BY category, name"
            ).fetchall()
        return [Product(a, b, c, d, bool(e), f) for a, b, c, d, e, f in rows]

    def save_product(self, product: Product) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT OR REPLACE INTO products (id, name, category, price, active, stock)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    product.product_id or None,
                    product.name,
                    product.category,
                    product.price,
                    int(product.active),
                    product.stock,
                ),
            )
            self._db.commit()
            return int(cursor.lastrowid or product.product_id)

    def remove_product(self, product_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM products WHERE id=?", (product_id,))
            self._db.commit()

    def add_order(
        self, room_id: str, items: list[tuple[int, int]], now: float | None = None
    ) -> int:
        """Order (product id, quantity) pairs for a room; unknown or hidden products are skipped."""
        now = time.time() if now is None else now
        known = {p.product_id: p for p in self.products(active_only=True)}
        added = 0
        with self._lock:
            for product_id, qty in items:
                product = known.get(product_id)
                if product is None or not 0 < qty <= 99:
                    continue
                if product.stock is not None:
                    if product.stock < qty:
                        continue  # not enough left
                    product.stock -= qty
                    # Sold out: take it off the menu until it is restocked.
                    self._db.execute(
                        "UPDATE products SET stock=?, active=? WHERE id=?",
                        (product.stock, int(product.stock > 0), product_id),
                    )
                self._db.execute(
                    "INSERT INTO orders (room_id, name, price, qty, created)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (room_id, product.name, product.price, qty, now),
                )
                added += 1
            self._db.commit()
        return added

    def orders(self, room_id: str | None = None) -> list[Order]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, room_id, name, price, qty, status, created FROM orders"
                + (" WHERE room_id=?" if room_id else "")
                + " ORDER BY created",
                (room_id,) if room_id else (),
            ).fetchall()
        return [Order(*row) for row in rows]

    def set_order_status(self, order_id: int, status: str) -> None:
        with self._lock:
            if status == "cancelled":  # put cancelled items back on the shelf
                row = self._db.execute(
                    "SELECT name, qty, status FROM orders WHERE id=?", (order_id,)
                ).fetchone()
                if row is not None and row[2] != "cancelled":
                    self._db.execute(
                        "UPDATE products SET stock = stock + ?, active = 1"
                        " WHERE name=? AND stock IS NOT NULL",
                        (row[1], row[0]),
                    )
            self._db.execute("UPDATE orders SET status=? WHERE id=?", (status, order_id))
            self._db.commit()

    def add_call(self, room_id: str, kind: str, note: str, now: float | None = None) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO calls (room_id, kind, note, created) VALUES (?, ?, ?, ?)",
                (room_id, kind[:40], note[:200], time.time() if now is None else now),
            )
            self._db.commit()
            return int(cursor.lastrowid or 0)

    def calls(self) -> list[Call]:
        """Calls still waiting for the staff."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, room_id, kind, note, created FROM calls WHERE done=0 ORDER BY created"
            ).fetchall()
        return [Call(*row) for row in rows]

    def finish_call(self, call_id: int) -> str | None:
        """Mark a call handled; returns its room."""
        with self._lock:
            row = self._db.execute("SELECT room_id FROM calls WHERE id=?", (call_id,)).fetchone()
            self._db.execute("UPDATE calls SET done=1 WHERE id=?", (call_id,))
            self._db.commit()
        return None if row is None else str(row[0])
