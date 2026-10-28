"""The YTKTV Desk window: a front desk that shows every room."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ytktv.desk.server import Hub, tell, unbind
from ytktv.desk.store import CODE_SECONDS, DeskStore, Room
from ytktv.rooms.state import format_left

COLUMNS = 3
LENGTHS = {"1 hour": 60, "2 hours": 120, "3 hours": 180, "No time limit": None}
EXTRA = {"30 minutes": 30, "1 hour": 60}
STYLE = """
#deskTop { background: rgba(10, 6, 24, 0.85); border-bottom: 1px solid #3a2a5c; }
#deskLogo { color: #ff3d9a; font-size: 30px; font-weight: 900; letter-spacing: 4px; }
#deskSub { color: #2ee6ff; font-size: 11px; font-weight: 700; letter-spacing: 5px; }
#deskClock { color: white; font-size: 26px; font-weight: 300; }
#navButton { background: transparent; color: #c9c3e6; border: 0; border-radius: 0;
  padding: 10px 18px; font-size: 15px; font-weight: 600; }
#navButton:checked { color: white; border-bottom: 3px solid #ff3d9a; }
#stat { background: #1a1430; border: 1px solid #33284f; border-radius: 14px; }
#statValue { color: white; font-size: 34px; font-weight: 800; }
#statLabel { color: #9a93b8; font-size: 11px; font-weight: 700; letter-spacing: 3px; }
#panel { background: #150f28; border: 1px solid #33284f; border-radius: 16px; }
#panelHead { color: #2ee6ff; font-size: 12px; font-weight: 800; letter-spacing: 4px; }
#bigName { color: white; font-size: 28px; font-weight: 800; }
#muted { color: #9a93b8; }
#codeDigits { color: #ff3d9a; font-size: 56px; font-weight: 900; letter-spacing: 12px; }
#callBar { background: #120c22; border-top: 1px solid #3a2a5c; }
#roomTile { border-radius: 18px; }
#roomTile[selected="true"] { border: 3px solid #2ee6ff; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
"""
STATUS = {  # status: (label, tile colour, dot)
    "free": ("Free", "#2b2f3d", "🟢"),
    "in_use": ("In use", "#1d7a55", "🎤"),
    "ending": ("Ending soon", "#a8781a", "⏳"),
    "over": ("Time's up", "#9c2f45", "⏰"),
    "offline": ("Offline", "#14111f", "⚫"),
}


def stat(value_label: QLabel, title: str) -> QFrame:
    frame = QFrame()
    frame.setObjectName("stat")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 12, 18, 12)
    value_label.setObjectName("statValue")
    label = QLabel(title.upper())
    label.setObjectName("statLabel")
    layout.addWidget(value_label)
    layout.addWidget(label)
    return frame


class DeskWindow(QMainWindow):
    def __init__(self, store: DeskStore, hub: Hub, address: str) -> None:
        super().__init__()
        self.store, self.hub, self.address = store, hub, address
        self.selected: str | None = None
        self._code_until = 0.0
        self.setWindowTitle("YTKTV Desk")
        self.setStyleSheet(STYLE)
        self.resize(1440, 900)
        root = QWidget()
        page = QVBoxLayout(root)
        page.setContentsMargins(0, 0, 0, 0)
        page.setSpacing(0)

        top = QFrame()
        top.setObjectName("deskTop")
        bar = QHBoxLayout(top)
        bar.setContentsMargins(24, 12, 24, 0)
        brand = QVBoxLayout()
        brand.setContentsMargins(0, 0, 0, 14)  # keep the subtitle off the bottom line
        brand.setSpacing(2)
        logo = QLabel("YTKTV")
        logo.setObjectName("deskLogo")
        sub = QLabel("KARAOKE SYSTEM  ·  FRONT DESK")
        sub.setObjectName("deskSub")
        brand.addWidget(logo)
        brand.addWidget(sub)
        bar.addLayout(brand)
        bar.addSpacing(36)
        self.stack = QStackedWidget()
        self.nav: dict[str, QPushButton] = {}
        for index, name in enumerate(("Rooms", "Settings")):
            button = QPushButton(name)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.clicked.connect(lambda _c=False, i=index: self.show_tab(i))
            self.nav[name] = button
            bar.addWidget(button, alignment=Qt.AlignmentFlag.AlignBottom)
        bar.addStretch()
        self.clock = QLabel()
        self.clock.setObjectName("deskClock")
        bar.addWidget(self.clock)
        bar.addSpacing(20)
        add = QPushButton("＋  Add Room")
        add.setObjectName("accent")
        add.setMinimumHeight(44)
        add.clicked.connect(self.add_room)
        bar.addWidget(add)
        page.addWidget(top)

        self.stack.addWidget(self._rooms_tab())
        self.stack.addWidget(self._settings_tab())
        page.addWidget(self.stack, stretch=1)

        calls = QFrame()
        calls.setObjectName("callBar")
        call_row = QHBoxLayout(calls)
        call_row.setContentsMargins(24, 10, 24, 10)
        head = QLabel("SERVICE CALLS")
        head.setObjectName("panelHead")
        self.calls_label = QLabel("No calls right now")
        self.calls_label.setObjectName("muted")
        hint = QLabel(f"Rooms connect to this desk at {address} · {store.fingerprint}")
        hint.setObjectName("muted")
        call_row.addWidget(head)
        call_row.addSpacing(16)
        call_row.addWidget(self.calls_label)
        call_row.addStretch()
        call_row.addWidget(hint)
        page.addWidget(calls)
        self.setCentralWidget(root)

        self.show_tab(0)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()

    # ----- layout

    def _rooms_tab(self) -> QWidget:
        tab = QWidget()
        column = QVBoxLayout(tab)
        column.setContentsMargins(24, 18, 24, 18)
        column.setSpacing(16)
        stats = QHBoxLayout()
        stats.setSpacing(14)
        self.stat_rooms, self.stat_online = QLabel(), QLabel()
        self.stat_used, self.stat_calls = QLabel("0"), QLabel("0")
        for label, title in (
            (self.stat_rooms, "Rooms"),
            (self.stat_online, "Online"),
            (self.stat_used, "In use"),
            (self.stat_calls, "Calls"),
        ):
            stats.addWidget(stat(label, title))
        column.addLayout(stats)

        body = QHBoxLayout()
        body.setSpacing(18)
        wall = QScrollArea()
        wall.setWidgetResizable(True)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setSpacing(16)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        wall.setWidget(holder)
        body.addWidget(wall, stretch=3)

        panel = QFrame()
        panel.setObjectName("panel")
        panel.setFixedWidth(400)
        side = QVBoxLayout(panel)
        side.setContentsMargins(24, 20, 24, 20)
        side.setSpacing(10)
        self.panel_head = QLabel("ROOM")
        self.panel_head.setObjectName("panelHead")
        self.panel_name = QLabel()
        self.panel_name.setObjectName("bigName")
        self.panel_name.setWordWrap(True)
        self.panel_info = QLabel()
        self.panel_info.setObjectName("muted")
        self.panel_info.setWordWrap(True)
        self.code_label = QLabel()
        self.code_label.setObjectName("codeDigits")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addWidget(self.panel_head)
        side.addWidget(self.panel_name)
        side.addWidget(self.code_label)
        side.addWidget(self.panel_info)
        side.addStretch()
        self.room_actions: list[QPushButton] = []
        for text, action in (
            ("Open Room", self.open_room),
            ("Extend Time", self.extend_room),
            ("Close Room", self.close_room),
        ):
            button = QPushButton(text)
            button.setMinimumHeight(46)
            button.setEnabled(False)
            button.clicked.connect(action)
            side.addWidget(button)
            self.room_actions.append(button)
        self.room_actions[0].setObjectName("accent")
        body.addWidget(panel)
        column.addLayout(body, stretch=1)
        return tab

    def _settings_tab(self) -> QWidget:
        tab = QWidget()
        column = QVBoxLayout(tab)
        column.setContentsMargins(24, 18, 24, 18)
        panel = QFrame()
        panel.setObjectName("panel")
        box = QVBoxLayout(panel)
        box.setContentsMargins(24, 20, 24, 20)
        head = QLabel("ROOM SETTINGS")
        head.setObjectName("panelHead")
        note = QLabel(
            "Rename a room, or unbind it. An unbound room turns back into a stand-alone YTKTV."
        )
        note.setObjectName("muted")
        self.room_list = QListWidget()
        buttons = QHBoxLayout()
        rename = QPushButton("Rename")
        rename.clicked.connect(self.rename_room)
        self.unbind_button = QPushButton("Unbind")
        self.unbind_button.clicked.connect(self.unbind_room)
        buttons.addWidget(rename)
        buttons.addWidget(self.unbind_button)
        buttons.addStretch()
        box.addWidget(head)
        box.addWidget(note)
        box.addWidget(self.room_list, stretch=1)
        box.addLayout(buttons)
        column.addWidget(panel)
        return tab

    def show_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, button in enumerate(self.nav.values()):
            button.setChecked(i == index)

    # ----- actions

    def add_room(self) -> None:
        code = self.store.new_code()
        self._code_until = time.monotonic() + CODE_SECONDS
        self.code_label.setText(code)
        self.selected = None
        self.show_tab(0)
        self.refresh()

    def select(self, room_id: str) -> None:
        self.selected = room_id
        self._code_until = 0.0
        self.refresh()

    def refresh(self) -> None:
        self.clock.setText(time.strftime("%H:%M"))
        rooms = self.store.rooms()
        online = self.hub.online()
        self.stat_rooms.setText(str(len(rooms)))
        self.stat_online.setText(str(len(online)))
        self._fill_wall(rooms, online)
        self._fill_panel(rooms, online)
        self._fill_settings(rooms)

    def _fill_wall(self, rooms: list[Room], online: set[str]) -> None:
        while self.grid.count():
            old = self.grid.takeAt(0)
            widget = old.widget() if old is not None else None
            if widget is not None:
                widget.deleteLater()
        if not rooms:
            empty = QLabel(
                "<div style='font-size:64px'>🎤</div>"
                "<div style='font-size:22px;font-weight:700;color:white'>No rooms yet</div>"
                "<div style='color:#9a93b8'>Press “Add Room”, then open Settings → Front Desk"
                " on a YTKTV and enter the code.</div>"
            )
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setMinimumHeight(360)
            self.grid.addWidget(empty, 0, 0, 1, COLUMNS)
            return
        for n, room in enumerate(rooms):
            label, colour, dot = STATUS[self._status(room, online)]
            left = room.ends_at - time.time() if room.is_open and room.ends_at else None
            tile = QPushButton()
            tile.setObjectName("roomTile")
            tile.setProperty("selected", room.room_id == self.selected)
            tile.setMinimumHeight(170)
            extra = f"\n{room.guest}" if room.is_open and room.guest else ""
            if left is not None and left > 0:
                extra += f"\n{format_left(left)} left"
            tile.setText(f"{room.name}\n\n{dot}  {label}{extra}")
            tile.setStyleSheet(
                f"#roomTile {{ background: {colour}; color: white; font-size: 20px;"
                " font-weight: 700; text-align: center; }"
            )
            tile.clicked.connect(lambda _c=False, r=room.room_id: self.select(r))
            self.grid.addWidget(tile, n // COLUMNS, n % COLUMNS)

    def _fill_panel(self, rooms: list[Room], online: set[str]) -> None:
        left = self._code_until - time.monotonic()
        if left > 0:
            self.panel_head.setText("PAIR A NEW ROOM")
            self.panel_name.setText("Enter this code on the room")
            self.panel_info.setText(
                f"On the YTKTV in that room: Settings → Front Desk.\n"
                f"Desk address: {self.address}\n\n"
                f"Security code: {self.store.fingerprint}\n"
                "The room must show the same four pictures; if not, do not confirm.\n\n"
                f"The code works once and expires in {int(left) // 60}:{int(left) % 60:02d}."
            )
            self.code_label.show()
            return
        self.code_label.hide()
        room = next((r for r in rooms if r.room_id == self.selected), None)
        if room is None:
            self.panel_head.setText("ROOM")
            self.panel_name.setText("Select a room")
            self.panel_info.setText("Click a room on the left to see it here.")
            for button in self.room_actions:
                button.setEnabled(False)
            return
        up = room.room_id in online
        seen = (
            "now"
            if up
            else time.strftime("%Y-%m-%d %H:%M", time.localtime(room.last_seen))
            if room.last_seen
            else "never"
        )
        self.panel_head.setText("ROOM")
        self.panel_name.setText(room.name)
        label, _, dot = STATUS[self._status(room, online)]
        lines = [f"{dot} {label}" + ("" if up else " · offline"), f"Last seen: {seen}"]
        if room.is_open:
            lines.append(f"Guest: {room.guest or '—'}")
            lines.append(
                "No time limit"
                if room.ends_at is None
                else f"Ends {time.strftime('%H:%M', time.localtime(room.ends_at))}"
                f" · {format_left(max(0.0, room.ends_at - time.time()))} left"
            )
        self.panel_info.setText("\n".join(lines))
        self.room_actions[0].setEnabled(not room.is_open)
        self.room_actions[1].setEnabled(room.is_open and room.ends_at is not None)
        self.room_actions[2].setEnabled(room.is_open)

    @staticmethod
    def _status(room: Room, online: set[str]) -> str:
        if room.is_open:
            if room.ends_at is not None:
                left = room.ends_at - time.time()
                if left <= 0:
                    return "over"
                if left <= 10 * 60:
                    return "ending"
            return "in_use"
        return "free" if room.room_id in online else "offline"

    # Each takes optional answers so tests can skip the dialogs.
    def open_room(
        self, _checked: bool = False, guest: str | None = None, length: str | None = None
    ) -> None:
        if self.selected is None:
            return
        if guest is None:
            guest, ok = QInputDialog.getText(self, "Open room", "Guest name (optional):")
            if not ok:
                return
        if length is None:
            length, ok = QInputDialog.getItem(
                self, "Open room", "How long?", list(LENGTHS), 1, False
            )
            if not ok:
                return
        self.store.open_room(self.selected, guest.strip(), LENGTHS[length])
        tell(self.store, self.hub, self.selected)
        self.refresh()

    def extend_room(self, _checked: bool = False, length: str | None = None) -> None:
        if self.selected is None:
            return
        if length is None:
            length, ok = QInputDialog.getItem(self, "Extend time", "Add:", list(EXTRA), 0, False)
            if not ok:
                return
        self.store.extend(self.selected, EXTRA[length])
        tell(self.store, self.hub, self.selected)
        self.refresh()

    def close_room(self, _checked: bool = False, confirm: bool = True) -> None:
        if self.selected is None:
            return
        if confirm:
            answer = QMessageBox.question(self, "Close room", "Close this room now?")
            if answer != QMessageBox.StandardButton.Yes:
                return
        self.store.close_room(self.selected)
        tell(self.store, self.hub, self.selected)
        self.refresh()

    def _fill_settings(self, rooms: list[Room]) -> None:
        current = self.room_list.currentRow()
        self.room_list.clear()
        for room in rooms:
            entry = QListWidgetItem(room.name)
            entry.setData(Qt.ItemDataRole.UserRole, room.room_id)
            self.room_list.addItem(entry)
        self.room_list.setCurrentRow(min(current, len(rooms) - 1))

    def _selected_setting(self) -> str | None:
        item = self.room_list.currentItem()
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def rename_room(self) -> None:
        room_id = self._selected_setting()
        if room_id:
            name, ok = QInputDialog.getText(self, "Rename room", "New name:")
            if ok and name.strip():
                self.store.rename(room_id, name.strip())
                self.refresh()

    def unbind_room(self) -> None:
        room_id = self._selected_setting()
        if room_id:
            unbind(self.store, self.hub, room_id)
            self.refresh()
