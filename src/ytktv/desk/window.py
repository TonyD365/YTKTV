"""The YTKTV Desk window: a front desk that shows every room."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ytktv.desk.server import Hub, unbind
from ytktv.desk.store import DeskStore

COLUMNS = 4


class DeskWindow(QMainWindow):
    def __init__(self, store: DeskStore, hub: Hub, address: str) -> None:
        super().__init__()
        self.store, self.hub = store, hub
        self.setWindowTitle("YTKTV Desk")
        self.resize(1400, 860)
        root = QWidget()
        column = QVBoxLayout(root)
        top = QHBoxLayout()
        title = QLabel("YTKTV  FRONT DESK")
        title.setObjectName("logo")
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.code_label = QLabel()
        self.code_label.setObjectName("homeTitle")
        add = QPushButton("＋ Add Room")
        add.setObjectName("accent")
        add.clicked.connect(self.add_room)
        top.addWidget(title)
        top.addSpacing(24)
        top.addWidget(self.summary)
        top.addStretch()
        top.addWidget(self.code_label)
        top.addWidget(add)
        column.addLayout(top)
        address_label = QLabel(f"Rooms connect to this desk at {address}")
        address_label.setObjectName("muted")
        column.addWidget(address_label)

        tabs = QTabWidget()
        tabs.setStyleSheet(
            "QTabWidget::pane { border: 0; } QScrollArea, QScrollArea > QWidget > QWidget"
            " { background: transparent; }"
        )
        wall = QScrollArea()
        wall.setWidgetResizable(True)
        self.grid_holder = QWidget()
        self.grid = QGridLayout(self.grid_holder)
        self.grid.setSpacing(14)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        wall.setWidget(self.grid_holder)
        tabs.addTab(wall, "Rooms")

        settings = QWidget()
        s = QVBoxLayout(settings)
        head = QLabel("ROOM SETTINGS")
        head.setObjectName("settingsHead")
        self.room_list = QListWidget()
        buttons = QHBoxLayout()
        rename = QPushButton("Rename")
        rename.clicked.connect(self.rename_room)
        self.unbind_button = QPushButton("Unbind")
        self.unbind_button.clicked.connect(self.unbind_room)
        buttons.addWidget(rename)
        buttons.addWidget(self.unbind_button)
        buttons.addStretch()
        s.addWidget(head)
        s.addWidget(self.room_list, stretch=1)
        s.addLayout(buttons)
        tabs.addTab(settings, "Settings")
        column.addWidget(tabs, stretch=1)
        self.setCentralWidget(root)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        self.refresh()

    def add_room(self) -> None:
        self.code_label.setText(f"Pairing code: {self.store.new_code()}  (5 min)")

    def refresh(self) -> None:
        rooms = self.store.rooms()
        online = self.hub.online()
        while self.grid.count():
            old = self.grid.takeAt(0)
            widget = old.widget() if old is not None else None
            if widget is not None:
                widget.deleteLater()
        for n, room in enumerate(rooms):
            up = room.room_id in online
            tile = QLabel(
                f"<b style='font-size:22px'>{room.name}</b><br><br>"
                + ("🟢 Online · Free" if up else "⚫ Offline")
            )
            tile.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tile.setMinimumHeight(150)
            colour = "#3b3f4a" if up else "#1c1a26"
            tile.setStyleSheet(f"background:{colour};border-radius:14px;color:white;")
            self.grid.addWidget(tile, n // COLUMNS, n % COLUMNS)
        if not rooms:
            hint = QLabel("No rooms yet. Press “Add Room”, then bind a YTKTV in its Settings.")
            hint.setObjectName("muted")
            self.grid.addWidget(hint, 0, 0, 1, COLUMNS)
        self.summary.setText(f"{len(rooms)} rooms · {len(online)} online")
        current = self.room_list.currentRow()
        self.room_list.clear()
        for room in rooms:
            entry = QListWidgetItem(room.name)
            entry.setData(Qt.ItemDataRole.UserRole, room.room_id)
            self.room_list.addItem(entry)
        self.room_list.setCurrentRow(min(current, len(rooms) - 1))

    def _selected(self) -> str | None:
        item = self.room_list.currentItem()
        return None if item is None else str(item.data(Qt.ItemDataRole.UserRole))

    def rename_room(self) -> None:
        room_id = self._selected()
        if room_id:
            name, ok = QInputDialog.getText(self, "Rename room", "New name:")
            if ok and name.strip():
                self.store.rename(room_id, name.strip())
                self.refresh()

    def unbind_room(self) -> None:
        room_id = self._selected()
        if room_id:
            unbind(self.store, self.hub, room_id)
            self.refresh()
