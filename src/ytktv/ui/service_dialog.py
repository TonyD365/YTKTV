"""Call the staff: ask for help, or order from its menu."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ytktv.rooms.client import RoomClient

KINDS = ("Drinks", "Snacks", "Equipment problem", "Other")
MENU_KINDS = ("Drinks", "Snacks")  # not needed as calls once the menu can be ordered from
MAX_QTY = 20


class Stepper(QWidget):
    """− 0 +, big enough for a finger, readable on the dark theme."""

    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.less = QPushButton("−")
        self.more = QPushButton("+")
        self.count = QLabel("0")
        self.count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count.setMinimumWidth(36)
        self.count.setStyleSheet("font-size: 18px; font-weight: 700;")
        for button in (self.less, self.more):
            button.setFixedSize(44, 40)
        self.less.clicked.connect(lambda: self.setValue(self.value() - 1))
        self.more.clicked.connect(lambda: self.setValue(self.value() + 1))
        row.addWidget(self.less)
        row.addWidget(self.count)
        row.addWidget(self.more)
        self._value = 0
        self.setValue(0)

    def value(self) -> int:
        return self._value

    def setValue(self, value: int) -> None:  # noqa: N802 - named like Qt's spin boxes
        self._value = max(0, min(MAX_QTY, value))
        self.count.setText(str(self._value))
        self.less.setEnabled(self._value > 0)
        self.more.setEnabled(self._value < MAX_QTY)


class ServiceDialog(QDialog):
    def __init__(self, client: RoomClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.client = client
        self.sent = ""
        self.setWindowTitle("Service")
        self.resize(560, 620)
        column = QVBoxLayout(self)
        head = QLabel("CALL THE STAFF")
        head.setObjectName("settingsHead")
        column.addWidget(head)
        kinds = QHBoxLayout()
        for kind in KINDS:
            if client.products and kind in MENU_KINDS:
                continue  # drinks and snacks are ordered from the menu below
            button = QPushButton(kind)
            button.setMinimumHeight(48)
            button.clicked.connect(lambda _c=False, k=kind: self.call(k))
            kinds.addWidget(button)
        column.addLayout(kinds)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Add a note (optional)")
        self.note.setMaxLength(200)
        column.addWidget(self.note)

        menu_head = QLabel("ORDER")
        menu_head.setObjectName("settingsHead")
        column.addWidget(menu_head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        grid = QGridLayout(holder)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        grid.setColumnStretch(0, 1)
        self.quantities: dict[int, Stepper] = {}
        row = 0
        category = None
        for item in sorted(client.products, key=lambda i: str(i.get("category") or "")):
            if (item.get("category") or "") != category:
                category = item.get("category") or ""
                heading = QLabel(category or "Other")
                heading.setObjectName("caption")
                grid.addWidget(heading, row, 0, 1, 2)
                row += 1
            name = QLabel(f"{item['name']}  ·  {client.currency}{float(item['price']):g}")
            name.setWordWrap(True)
            qty = Stepper()
            grid.addWidget(name, row, 0)
            grid.addWidget(qty, row, 1)
            self.quantities[int(item["product_id"])] = qty
            row += 1
        if not client.products:
            grid.addWidget(QLabel("The staff terminal has no menu yet."), 0, 0)
        scroll.setWidget(holder)
        column.addWidget(scroll, stretch=1)
        order = QPushButton("Send Order")
        order.setObjectName("accent")
        order.setMinimumHeight(48)
        order.clicked.connect(self.order)
        column.addWidget(order)

    def call(self, kind: str) -> None:
        if self.client.call(kind, self.note.text()):
            self.sent = f"Asked the staff: {kind}"
            self.accept()

    def order(self) -> None:
        items = [(pid, box.value()) for pid, box in self.quantities.items() if box.value()]
        if self.client.order(items):
            self.sent = "Order sent to the staff"
            self.accept()
