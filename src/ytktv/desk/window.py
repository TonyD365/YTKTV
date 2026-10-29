"""The YTKTV Desk window: a front desk that shows every room."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
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

from ytktv.desk import lock
from ytktv.desk.billing import bill
from ytktv.desk.pages import BookingsPage, MembersPage, RecordsPage, ShiftDialog
from ytktv.desk.panels import (
    MAX_PRICE,
    BillDialog,
    BroadcastDialog,
    OrdersBox,
    ReceiptSettings,
    SecuritySettings,
    ShopSettings,
)
from ytktv.desk.server import Hub, tell, tell_all_products, unbind
from ytktv.desk.store import CODE_SECONDS, Booking, DeskStore, Room
from ytktv.desk.update import DeskUpdater
from ytktv.rooms.state import format_left

COLUMNS = 4
ICON = Path(__file__).parent / "assets" / "icon.png"
TIPS = ("Skip the song", "Pause or resume", "Music volume", "Send a message", "Lock or unlock")
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
#roomTile { border-radius: 14px; text-align: left; }
#roomTile[selected="true"] { border: 3px solid #2ee6ff; }
#sideBar { background: #0e0920; border-right: 1px solid #3a2a5c; }
#sideHead { color: #6f6890; font-size: 10px; font-weight: 800; letter-spacing: 3px;
  padding: 12px 6px 4px 6px; }
#sideButton { background: transparent; color: #d9d4f2; border: 0; border-radius: 10px;
  padding: 9px 12px; text-align: left; font-size: 14px; font-weight: 600; }
#sideButton:hover { background: #1f1838; }
#sideButton:checked { background: #2a1d4d; color: white; border-left: 3px solid #ff3d9a; }
#sideButton:disabled { color: #4a4466; }
#legend { color: #c9c3e6; font-size: 13px; font-weight: 600; }
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: 0; }
QTableWidget, QListWidget, QTextBrowser { background: #120c22; color: white;
  alternate-background-color: #1a1430; gridline-color: #2a2445; border: 1px solid #33284f;
  border-radius: 10px; selection-background-color: #ff3d9a; selection-color: white; }
QHeaderView::section { background: #1a1430; color: #9a93b8; border: 0;
  border-bottom: 1px solid #33284f; padding: 6px; font-weight: 700; }
QTableCornerButton::section { background: #1a1430; border: 0; }
QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit { background: #1a1430; color: white;
  border: 1px solid #33284f; border-radius: 8px; padding: 6px 10px; min-height: 26px; }
QCalendarWidget QWidget { background: #120c22; color: white;
  alternate-background-color: #1a1430; }
QCalendarWidget QToolButton { background: transparent; color: white; font-weight: 700;
  padding: 6px; }
QCalendarWidget #qt_calendar_navigationbar { background: #1a1430; }
QCalendarWidget QAbstractItemView:enabled { color: white; selection-background-color: #ff3d9a;
  selection-color: white; }
QCalendarWidget QAbstractItemView:disabled { color: #4a4466; }
QCheckBox { color: white; }
QAbstractSpinBox QLineEdit { padding: 0; margin: 0; border: 0; border-radius: 0;
  background: transparent; font-size: 16px; }
"""
STATUS = {  # status: (label, tile colour, dot)
    "free": ("Free", "#24506b", "🟢"),
    "booked": ("Booked", "#5b3fa0", "📅"),
    "in_use": ("In use", "#1d7a55", "🎤"),
    "ending": ("Ending soon", "#a8781a", "⏳"),
    "over": ("Time's up", "#9c2f45", "⏰"),
    "calling": ("Calling", "#c2185b", "🛎"),
    "cleaning": ("Cleaning", "#6b5a2a", "🧹"),
    "maintenance": ("Maintenance", "#4a4a52", "🔧"),
    "offline": ("Offline", "#14111f", "⚫"),
}
LEGEND = ("free", "booked", "in_use", "ending", "calling", "cleaning", "maintenance", "offline")
ROOM_TYPES = ("Small", "Medium", "Large", "VIP", "Party")


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
        self._call_count = 0
        self._locked: set[str] = set()
        self._reminded: set[int] = set()
        self._calls_shown: list[int] = []
        self._code_until = 0.0
        self.setWindowTitle("YTKTV Desk")
        self.setWindowIcon(QIcon(str(ICON)))
        self.setStyleSheet(STYLE)
        self.resize(1280, 820)
        self.setMinimumWidth(1100)
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
        bar.addSpacing(28)
        legend = QHBoxLayout()
        legend.setSpacing(16)
        self.legend: dict[str, QLabel] = {}
        for key in LEGEND:
            label, colour, _ = STATUS[key]
            chip = QLabel()
            chip.setObjectName("legend")
            chip.setToolTip(label)
            self.legend[key] = chip
            legend.addWidget(chip)
        bar.addLayout(legend)
        bar.addStretch()
        money = QVBoxLayout()
        self.stat_today = QLabel("0")
        self.stat_today.setObjectName("deskClock")
        today_label = QLabel("TODAY")
        today_label.setObjectName("statLabel")
        money.addWidget(self.stat_today, alignment=Qt.AlignmentFlag.AlignRight)
        money.addWidget(today_label, alignment=Qt.AlignmentFlag.AlignRight)
        bar.addLayout(money)
        bar.addSpacing(16)
        self.update_button = QPushButton()
        self.update_button.setObjectName("accent")
        self.update_button.hide()
        bar.addWidget(self.update_button)
        bar.addSpacing(16)
        self.clock = QLabel()
        self.clock.setObjectName("deskClock")
        bar.addWidget(self.clock)
        page.addWidget(top)

        middle = QHBoxLayout()
        middle.setContentsMargins(0, 0, 0, 0)
        middle.setSpacing(0)
        middle.addWidget(self._side_bar())
        self.stack = QStackedWidget()
        middle.addWidget(self.stack, stretch=1)

        self.stack.addWidget(self._rooms_tab())
        self.bookings = BookingsPage(self.store, self.check_in)
        self.records = RecordsPage(self.store)
        self.stack.addWidget(self.bookings)
        self.stack.addWidget(self.records)
        self.members = MembersPage(self.store)
        self.stack.addWidget(self.members)
        settings = QScrollArea()  # taller than a laptop screen: let it scroll
        settings.setWidgetResizable(True)
        settings.setWidget(self._settings_tab())
        self.stack.addWidget(settings)
        page.addLayout(middle, stretch=1)

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
        self.call_chips = QHBoxLayout()
        call_row.addLayout(self.call_chips)
        call_row.addStretch()
        call_row.addWidget(hint)
        page.addWidget(calls)
        self.setCentralWidget(root)

        self.show_tab(0)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)
        self.refresh()
        self.lock_screen = lock.LockScreen(root, self.store)
        self.lock_screen.lock()  # asks for the password at start when one is set
        self.lock_screen.activity()

    # ----- layout

    def _rooms_tab(self) -> QWidget:
        tab = QWidget()
        column = QVBoxLayout(tab)
        column.setContentsMargins(24, 18, 24, 18)
        column.setSpacing(16)
        self.stat_rooms, self.stat_online = QLabel(), QLabel()
        self.stat_used, self.stat_calls = QLabel("0"), QLabel("0")

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
        panel.setFixedWidth(360)
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
        self.orders = OrdersBox(self.store)
        side.addWidget(self.orders)
        side.addStretch()
        remote = QGridLayout()
        remote.setSpacing(8)
        self.remote_buttons: list[QPushButton] = []
        for text, handler in (
            ("⏭", lambda: self._control("skip")),
            ("⏯", lambda: self._control("pause")),
            ("🔊", self._volume),
            ("💬", self._message_room),
            ("🔒", self._toggle_lock),
        ):
            button = QPushButton(text)
            button.clicked.connect(handler)
            button.setEnabled(False)
            button.setMinimumHeight(40)
            button.setToolTip(TIPS[len(self.remote_buttons)])
            remote.addWidget(button, 0, len(self.remote_buttons))
            self.remote_buttons.append(button)
        side.addLayout(remote)
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
        price = QPushButton("Set Price")
        price.clicked.connect(self.set_room_rate)
        kind = QPushButton("Room Type")
        kind.clicked.connect(self.set_room_type)
        buttons.addWidget(rename)
        buttons.addWidget(kind)
        buttons.addWidget(price)
        buttons.addWidget(self.unbind_button)
        buttons.addStretch()
        box.addWidget(head)
        box.addWidget(note)
        box.addWidget(self.room_list, stretch=1)
        box.addLayout(buttons)
        column.addWidget(panel, stretch=1)
        self.shop = ShopSettings(self.store, lambda: tell_all_products(self.store, self.hub))
        column.addWidget(self.shop, stretch=2)
        self.receipts = ReceiptSettings(self.store)
        column.addWidget(self.receipts)
        self.security = SecuritySettings(self.store)
        column.addWidget(self.security)
        return tab

    def watch_updates(self, updates: DeskUpdater) -> None:
        """Offer a downloaded update in the top bar; installing quits the desk."""

        def ready(version: str) -> None:
            self.update_button.setText(f"⬆  Update to {version}")
            self.update_button.setToolTip("Install the new version and restart the desk")
            self.update_button.show()

        def available(version: str, page: str) -> None:
            self.update_button.setText(f"⬆  {version} is out")
            self.update_button.setToolTip(page)
            self.update_button.show()

        def install() -> None:
            if updates.install():
                QApplication.quit()
            else:
                QDesktopServices.openUrl(QUrl(self.update_button.toolTip()))

        updates.ready.connect(ready)
        updates.available.connect(available)
        self.update_button.clicked.connect(install)

    def _side_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("sideBar")
        bar.setFixedWidth(210)
        column = QVBoxLayout(bar)
        column.setContentsMargins(10, 8, 10, 12)
        column.setSpacing(2)

        def head(text: str) -> None:
            label = QLabel(text)
            label.setObjectName("sideHead")
            column.addWidget(label)

        def button(text: str, handler: object, tip: str = "") -> QPushButton:
            item = QPushButton(text)
            item.setObjectName("sideButton")
            item.setToolTip(tip)
            item.clicked.connect(handler)
            column.addWidget(item)
            return item

        head("VIEW")
        self.nav: dict[str, QPushButton] = {}
        for index, (name, icon) in enumerate(
            (
                ("Rooms", "🏠"),
                ("Bookings", "📅"),
                ("Records", "📊"),
                ("Members", "💳"),
                ("Settings", "⚙️"),
            )
        ):
            self.nav[name] = button(f"{icon}  {name}", lambda _c=False, i=index: self.show_tab(i))
            self.nav[name].setCheckable(True)
        head("SELECTED ROOM")
        self.room_actions = {
            "open": button("🔑  Open Room", self.open_room),
            "extend": button("⏱  Extend Time", self.extend_room),
            "change": button("🔁  Change Room", self.change_room, "Move the party to another room"),
            "add_item": button("🛒  Add Item", lambda: self.orders.add_item()),
            "close": button("💳  Check Out", self.close_room, "Show the bill and close the room"),
            "cleaned": button("🧹  Cleaned", self.mark_cleaned, "The room is ready again"),
            "repair": button("🔧  Maintenance", self.toggle_maintenance),
        }
        head("FRONT DESK")
        button("📢  Broadcast", self.broadcast)
        button("＋  Add Room", self.add_room)
        button("📋  Shift Report", self.shift_report)
        column.addStretch()
        return bar

    def show_tab(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, item in enumerate(self.nav.values()):
            item.setChecked(i == index)

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
        self.stat_used.setText(str(sum(r.is_open for r in rooms)))
        counts = {key: 0 for key in LEGEND}
        for room in rooms:
            status = self._status(room, online)
            counts["in_use" if status == "over" else status] += 1
        for key, chip in self.legend.items():
            label, colour, _ = STATUS[key]
            chip.setText(f"<span style='color:{colour}'>●</span> {label} <b>{counts[key]}</b>")
        self._fill_wall(rooms, online)
        self._fill_panel(rooms, online)
        self._fill_settings(rooms)
        self._fill_calls(rooms)
        start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        today = sum(v.total for v in self.store.history(start, start + 86400))
        self.stat_today.setText(f"{self.store.setting('currency', '$')}{today:g}")

    def _fill_calls(self, rooms: list[Room]) -> None:
        calls = self.store.calls()
        if len(calls) > self._call_count:
            QApplication.beep()
        self._call_count = len(calls)
        self.stat_calls.setText(str(len(calls)))
        shown = [c.call_id for c in calls]
        if shown == self._calls_shown:
            return
        self._calls_shown = shown
        while self.call_chips.count():
            item = self.call_chips.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        names = {r.room_id: r.name for r in rooms}
        self.calls_label.setVisible(not calls)
        for call in calls[:6]:
            note = f": {call.note}" if call.note else ""
            chip = QPushButton(f"🛎 {names.get(call.room_id, '?')} · {call.kind}{note}  ✓")
            chip.setToolTip("Mark as handled; the room is told staff is on the way")
            chip.setStyleSheet("background: #9c2f45; color: white; border-radius: 14px;")
            chip.clicked.connect(lambda _c=False, c=call.call_id: self.finish_call(c))
            self.call_chips.addWidget(chip)

    # -- remote control -------------------------------------------------------

    def _control(self, action: str, value: int | None = None) -> None:
        if self.selected:
            self.hub.send_soon(self.selected, {"type": "control", "action": action, "value": value})

    def _volume(self) -> None:
        value, ok = QInputDialog.getInt(self, "Music volume", "Volume (0–100):", 60, 0, 100)
        if ok:
            self._control("volume", value)

    def _message_room(self) -> None:
        if self.selected:
            self.broadcast(rooms=[self.selected])

    def _toggle_lock(self) -> None:
        if not self.selected:
            return
        locking = self.selected not in self._locked
        (self._locked.add if locking else self._locked.discard)(self.selected)
        self.hub.send_soon(self.selected, {"type": "lock" if locking else "unlock"})
        self.refresh()

    def broadcast(self, _checked: bool = False, rooms: list[str] | None = None) -> None:
        dialog = BroadcastDialog(self.store, self.hub, rooms, self)
        dialog.exec()

    def finish_call(self, call_id: int) -> None:
        room_id = self.store.finish_call(call_id)
        if room_id:
            self.hub.send_soon(room_id, {"type": "call_done"})
        self.refresh()

    def set_room_rate(self) -> None:
        room_id = self._selected_setting()
        if room_id:
            rate, ok = QInputDialog.getDouble(
                self,
                "Price per hour",
                "This room's price per hour (0 = desk default):",
                0,
                0,
                MAX_PRICE,
                2,
            )
            if ok:
                self.store.set_rate(room_id, rate or None)

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
        now = time.time()
        upcoming: dict[str, Booking] = {}
        for booking in self.store.bookings(now - 3600, now + 12 * 3600, live_only=True):
            upcoming.setdefault(booking.room_id, booking)
            if booking.starts - now <= 15 * 60 and booking.booking_id not in self._reminded:
                self._reminded.add(booking.booking_id)
                QApplication.beep()  # a booked guest is due within 15 minutes
        for n, room in enumerate(rooms):
            label, colour, dot = STATUS[self._status(room, online)]
            left = room.ends_at - time.time() if room.is_open and room.ends_at else None
            tile = QPushButton()
            tile.setObjectName("roomTile")
            tile.setProperty("selected", room.room_id == self.selected)
            tile.setFixedHeight(204)  # one size, like a real room board
            extra = f"\n{room.guest}" if room.is_open and room.guest else ""
            if room.is_open:
                spend = bill(self.store, room.room_id)
                extra += f"\n{spend.currency}{spend.total:.2f}"
            if left is not None and left > 0:
                extra += f"\n{format_left(left)} left"
            singing = self.store.now_singing(room.room_id) if room.is_open else ""
            if singing:
                extra += f"\n♪ {singing[:28]}"
            booked = upcoming.get(room.room_id)
            if booked is not None and not room.is_open:
                at = time.strftime("%H:%M", time.localtime(booked.starts))
                extra += f"\n{at} · {booked.guest}"
            text = f"{room.name}\n{room.room_type} · {room.capacity} seats\n\n{dot}  {label}{extra}"
            tile.setText(text.replace("&", "&&"))  # a lone & would become a shortcut
            tile.setStyleSheet(
                f"#roomTile {{ background: {colour}; color: white; font-size: 15px;"
                " font-weight: 700; text-align: left; padding: 12px 16px; }"
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
            for action in self.room_actions.values():
                action.setEnabled(False)
            self.orders.show_room(None)
            return
        up = room.room_id in online
        seen = (
            "now"
            if up
            else time.strftime("%Y-%m-%d %H:%M", time.localtime(room.last_seen))
            if room.last_seen
            else "never"
        )
        self.panel_name.setText(room.name)
        self.panel_head.setText(f"{room.room_type.upper()} ROOM · {room.capacity} SEATS")
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
        enabled = {
            "open": not room.is_open and room.state != "maintenance",
            "extend": room.is_open and room.ends_at is not None,
            "change": room.is_open,
            "add_item": room.is_open,
            "close": room.is_open,
            "cleaned": not room.is_open and room.state == "cleaning",
            "repair": not room.is_open,
        }
        for key, action in self.room_actions.items():
            action.setEnabled(enabled[key])
        self.room_actions["repair"].setText(
            "✅  Back in Service" if room.state == "maintenance" else "🔧  Maintenance"
        )
        self.orders.show_room(room.room_id if room.is_open else None)
        for button in self.remote_buttons:
            button.setEnabled(room.is_open and up)
        self.remote_buttons[4].setText("🔓" if room.room_id in self._locked else "🔒")

    def _status(self, room: Room, online: set[str]) -> str:
        if room.is_open and any(c.room_id == room.room_id for c in self.store.calls()):
            return "calling"
        if room.is_open:
            if room.ends_at is not None:
                left = room.ends_at - time.time()
                if left <= 0:
                    return "over"
                if left <= 10 * 60:
                    return "ending"
            return "in_use"
        if room.state in ("cleaning", "maintenance"):
            return room.state
        if room.room_id not in online:
            return "offline"
        now = time.time()
        soon = self.store.bookings(now - 3600, now + 2 * 3600, live_only=True)
        return "booked" if any(b.room_id == room.room_id for b in soon) else "free"

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
        minutes = LENGTHS[length]
        room = self.store.room(self.selected)
        if room is not None and room.state == "cleaning":
            answer = QMessageBox.question(
                self, "Not cleaned yet", "This room has not been cleaned. Open it anyway?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        clashes = self.store.clashes(self.selected, time.time(), minutes)
        if clashes and not _checked_clash(self, clashes):
            return
        self.store.open_room(self.selected, guest.strip(), minutes)
        self.store.set_state(self.selected, "ready")
        tell(self.store, self.hub, self.selected)
        self.refresh()

    def check_in(self, booking: Booking) -> None:
        """A booked guest arrived: open their room as booked."""
        self.store.open_room(booking.room_id, booking.guest, booking.minutes)
        tell(self.store, self.hub, booking.room_id)
        self.selected = booking.room_id
        self.show_tab(0)
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
        result = bill(self.store, self.selected)
        if confirm and not BillDialog(result, self, self.store).exec():
            return
        self.store.close_room(self.selected, result)
        self.records.refresh()
        tell(self.store, self.hub, self.selected)
        self.refresh()

    def change_room(self, _checked: bool = False, target: str | None = None) -> None:
        if self.selected is None:
            return
        free = [
            r
            for r in self.store.rooms()
            if not r.is_open and r.room_id != self.selected and r.state == "ready"
        ]
        if target is None:
            if not free:
                QMessageBox.information(self, "Change room", "No other room is free and clean.")
                return
            names = [f"{r.name} · {r.room_type}, {r.capacity} seats" for r in free]
            choice, ok = QInputDialog.getItem(self, "Change room", "Move to:", names, 0, False)
            if not ok:
                return
            target = free[names.index(choice)].room_id
        old = self.selected
        self.store.change_room(old, target)
        tell(self.store, self.hub, old)  # closes the old room
        tell(self.store, self.hub, target)  # opens the new one with the same time
        self.selected = target
        self.refresh()

    def mark_cleaned(self) -> None:
        if self.selected:
            self.store.set_state(self.selected, "ready")
            self.refresh()

    def toggle_maintenance(self) -> None:
        room = self.store.room(self.selected) if self.selected else None
        if room is not None and not room.is_open:
            self.store.set_state(
                room.room_id, "ready" if room.state == "maintenance" else "maintenance"
            )
            self.refresh()

    def shift_report(self) -> None:
        ShiftDialog(self.store, self).exec()

    def set_room_type(self) -> None:
        room_id = self._selected_setting()
        room = self.store.room(room_id) if room_id else None
        if room is None:
            return
        kind, ok = QInputDialog.getItem(
            self,
            "Room type",
            "Type:",
            list(ROOM_TYPES),
            ROOM_TYPES.index(room.room_type) if room.room_type in ROOM_TYPES else 1,
            False,
        )
        if not ok:
            return
        seats, ok = QInputDialog.getInt(self, "Room type", "Seats:", room.capacity, 1, 99)
        if ok:
            self.store.set_type(room.room_id, kind, seats)
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

    def unbind_room(self, _checked: bool = False, password: str | None = None) -> None:
        room_id = self._selected_setting()
        if room_id and lock.has_password(self.store):
            if password is None:
                password, ok = QInputDialog.getText(
                    self, "Unbind room", "Desk password:", QLineEdit.EchoMode.Password
                )
                if not ok:
                    return
            if not lock.check(self.store, password):
                QMessageBox.warning(self, "Unbind room", "Wrong password.")
                return
        if room_id:
            unbind(self.store, self.hub, room_id)
            self.refresh()


def _checked_clash(parent: QWidget, clashes: list[Booking]) -> bool:
    """Ask before opening a room that is booked soon; True to open anyway."""
    when = ", ".join(time.strftime("%H:%M", time.localtime(c.starts)) for c in clashes)
    answer = QMessageBox.question(
        parent, "Room is booked", f"This room is booked at {when}. Open it anyway?"
    )
    return answer == QMessageBox.StandardButton.Yes
