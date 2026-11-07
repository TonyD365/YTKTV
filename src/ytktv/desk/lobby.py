"""The lobby screen: a TV outside the front desk showing the rooms and today's bookings."""

from __future__ import annotations

import time
from collections.abc import Callable
from html import escape

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ytktv.desk.store import Booking, DeskStore, Room

# Settings key: "" = off, "-1" = the first screen that is not the main one, "0"... = that screen
SETTING = "lobby_screen"

STYLE = """
#lobby { background: #0b0718; }
#lobby QLabel { color: #f3eeff; }
#lobby QLabel#title { font-size: 46px; font-weight: 900; color: #ff3d9a; }
#lobby QLabel#clock { font-size: 40px; font-weight: 700; }
#lobby QLabel#head { font-size: 22px; font-weight: 800; color: #2ee6ff; letter-spacing: 3px; }
#lobby QLabel#list { font-size: 28px; }
#lobby QFrame#card { background: #170f2e; border: 2px solid #2b1f50; border-radius: 18px; }
"""


def describe(
    rooms: list[Room], status: Callable[[Room], str], bookings: list[Booking], now: float
) -> tuple[list[str], list[str], list[str]]:
    """Lines for the first three columns: free rooms, rooms in use, today's bookings."""
    names = {room.room_id: room.name for room in rooms}
    free, busy = [], []
    for room in sorted(rooms, key=lambda r: r.name):
        state = status(room)
        if state == "free":
            free.append(f"{room.name} · {room.room_type}, {room.capacity} seats")
        elif room.is_open:
            if room.ends_at is None:
                busy.append(f"{room.name} · open")
            else:
                left = max(0, int(room.ends_at - now) // 60)
                busy.append(f"{room.name} · free in {left // 60}:{left % 60:02d}")
    later = [b for b in bookings if b.status == "booked" and b.starts >= now - 15 * 60]
    booked = [
        f"{time.strftime('%H:%M', time.localtime(b.starts))} · {names.get(b.room_id, b.room_id)}"
        for b in sorted(later, key=lambda b: b.starts)
    ]
    return free, busy, booked


class LobbyWindow(QWidget):
    """A borderless full-screen window, placed like a room's MV screen."""

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("YTKTV Desk · Lobby")
        self.setObjectName("lobby")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(STYLE)
        page = QVBoxLayout(self)
        page.setContentsMargins(48, 36, 48, 36)
        top = QHBoxLayout()
        title = QLabel("YTKTV")
        title.setObjectName("title")
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.clock)
        page.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(28)
        self.columns: list[QLabel] = []
        for text in ("FREE NOW", "IN USE", "BOOKED TODAY"):
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(28, 24, 28, 24)
            head = QLabel(text)
            head.setObjectName("head")
            body = QLabel()
            body.setObjectName("list")
            body.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            body.setWordWrap(True)
            box.addWidget(head)
            box.addWidget(body, stretch=1)
            row.addWidget(card)
            self.columns.append(body)
        page.addLayout(row, stretch=1)

    def fill(self, free: list[str], busy: list[str], booked: list[str]) -> None:
        # Only the rooms' state: what a room sings and its scores stay private.
        self.clock.setText(time.strftime("%H:%M"))
        empty = ("All rooms are taken", "—", "No more bookings today")
        columns = (free, busy, booked)
        for label, lines, nothing in zip(self.columns, columns, empty, strict=True):
            label.setText("<br>".join(escape(line) for line in lines[:12]) or escape(nothing))

    def place(self, screen_index: int) -> None:
        """Full screen on the chosen display (-1 = the first that is not the main one)."""
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        target = None
        if 0 <= screen_index < len(screens):
            target = screens[screen_index]
        elif screen_index < 0:
            target = next((s for s in screens if s is not primary), None)
        if target is None:
            # Only one display: a normal window, so the desk itself is not covered.
            self.showNormal()
            self.resize(1280, 720)
            return
        self.showNormal()
        self.setGeometry(target.geometry())
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(target)
        self.showFullScreen()


class LobbySettings(QFrame):
    """Turn the lobby screen on and choose its display."""

    def __init__(self, store: DeskStore, changed: Callable[[], None]) -> None:
        super().__init__()
        self.store = store
        self.changed = changed
        self.setObjectName("panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        head = QLabel("LOBBY SCREEN")
        head.setObjectName("panelHead")
        note = QLabel(
            "A TV outside the desk shows the free rooms, when busy rooms come free and today's"
            " bookings. It goes full screen on the chosen display, like a room's MV screen."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        value = store.setting(SETTING, "")
        self.enabled = QCheckBox("Show the lobby screen")
        self.enabled.setChecked(value != "")
        self.display = QComboBox()
        self.fill_screens()
        self.enabled.toggled.connect(lambda _on: self.save())
        self.display.activated.connect(lambda _i: self.save())
        row = QHBoxLayout()
        row.addWidget(self.enabled)
        row.addWidget(self.display)
        row.addStretch()
        for widget in (head, note):
            column.addWidget(widget)
        column.addLayout(row)

    def fill_screens(self) -> None:
        chosen = self.store.setting(SETTING, "") or "-1"
        self.display.clear()
        self.display.addItem("The second display", "-1")
        for index, screen in enumerate(QGuiApplication.screens()):
            self.display.addItem(f"Display {index + 1}: {screen.name()}", str(index))
        self.display.setCurrentIndex(max(0, self.display.findData(chosen)))

    def save(self) -> None:
        on = self.enabled.isChecked()
        self.store.set_setting(SETTING, str(self.display.currentData()) if on else "")
        self.changed()


class Lobby:
    """Owns the window: shows, places and fills it as the settings and screens change."""

    def __init__(self, store: DeskStore) -> None:
        self.store = store
        self.window: LobbyWindow | None = None
        app = QGuiApplication.instance()
        if isinstance(app, QGuiApplication):
            # Wireless displays take a moment to settle their size, as for the MV screen.
            app.screenAdded.connect(lambda _s: QTimer.singleShot(1500, self.apply))
            app.screenRemoved.connect(lambda _s: QTimer.singleShot(800, self.apply))

    def apply(self) -> None:
        value = self.store.setting(SETTING, "")
        if value == "":
            if self.window is not None:
                self.window.close()
                self.window = None
            return
        if self.window is None:
            self.window = LobbyWindow()
        self.window.place(int(value))

    def refresh(self, rooms: list[Room], status: Callable[[Room], str]) -> None:
        if self.window is None:
            return
        now = time.time()
        start = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
        bookings = self.store.bookings(start, start + 86400, live_only=True)
        self.window.fill(*describe(rooms, status, bookings, now))
