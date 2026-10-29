"""Call the staff: ask for help, or order from its menu."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ytktv.rooms.client import RoomClient

KINDS = ("Drinks", "Snacks", "Equipment problem", "Other")


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
        self.quantities: dict[int, QSpinBox] = {}
        for row, item in enumerate(client.products):
            name = QLabel(f"{item['name']}  ·  {client.currency}{float(item['price']):g}")
            qty = QSpinBox()
            qty.setRange(0, 20)
            grid.addWidget(name, row, 0)
            grid.addWidget(qty, row, 1)
            self.quantities[int(item["product_id"])] = qty
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
