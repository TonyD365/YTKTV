"""Parts of the desk window: a room's orders, the bill, and the shop settings."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ytktv.desk.billing import DEFAULT_RATE, ROUNDING, Bill
from ytktv.desk.store import DeskStore, Product


class OrdersBox(QWidget):
    """The selected room's orders, with the staff's buttons."""

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        self.room_id: str | None = None
        self._shown: list[tuple[int, str]] = []
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(0, 8, 0, 8)
        head = QLabel("ORDERS")
        head.setObjectName("panelHead")
        self.rows = QVBoxLayout()
        add = QPushButton("＋ Add Item")
        add.clicked.connect(self.add_item)
        self.column.addWidget(head)
        self.column.addLayout(self.rows)
        self.column.addWidget(add, alignment=Qt.AlignmentFlag.AlignLeft)

    def show_room(self, room_id: str | None) -> None:
        orders = self.store.orders(room_id) if room_id else []
        shown = [(o.order_id, o.status) for o in orders]
        if room_id == self.room_id and shown == self._shown:
            return  # unchanged: keep the buttons under the mouse
        self.room_id, self._shown = room_id, shown
        while self.rows.count():
            item = self.rows.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        currency = self.store.setting("currency", "$")
        for order in orders:
            row = QWidget()
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            mark = {"pending": "🕒", "delivered": "✓", "cancelled": "✕"}[order.status]
            text = QLabel(
                f"{mark} {order.name} × {order.qty}  {currency}{order.price * order.qty:g}"
            )
            if order.status == "cancelled":
                text.setObjectName("muted")
            line.addWidget(text, stretch=1)
            if order.status == "pending":
                for label, status in (("Delivered", "delivered"), ("Cancel", "cancelled")):
                    button = QPushButton(label)
                    button.clicked.connect(
                        lambda _c=False, o=order.order_id, s=status: self._set(o, s)
                    )
                    line.addWidget(button)
            self.rows.addWidget(row)
        if not orders:
            empty = QLabel("No orders")
            empty.setObjectName("muted")
            self.rows.addWidget(empty)

    def _set(self, order_id: int, status: str) -> None:
        self.store.set_order_status(order_id, status)
        self.show_room(self.room_id)

    def add_item(self) -> None:
        products = self.store.products(active_only=True)
        if self.room_id is None or not products:
            return
        names = [f"{p.name} ({p.price:g})" for p in products]
        choice, ok = QInputDialog.getItem(self, "Add item", "Item:", names, 0, False)
        if not ok:
            return
        qty, ok = QInputDialog.getInt(self, "Add item", "How many?", 1, 1, 99)
        if ok:
            product = products[names.index(choice)]
            self.store.add_order(self.room_id, [(product.product_id, qty)])
            self.store.set_order_status(self.store.orders(self.room_id)[-1].order_id, "delivered")
            self.show_room(self.room_id)


class BillDialog(QDialog):
    """The bill shown when a room closes; it can be printed or saved as a PDF."""

    def __init__(self, bill: Bill, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bill = bill
        self.setWindowTitle(f"Bill · {bill.room}")
        self.resize(480, 560)
        column = QVBoxLayout(self)
        view = QTextBrowser()
        view.setHtml(bill.html())
        column.addWidget(view, stretch=1)
        buttons = QHBoxLayout()
        print_button = QPushButton("Print…")
        print_button.clicked.connect(self.print_bill)
        pdf = QPushButton("Save PDF…")
        pdf.clicked.connect(self.save_pdf)
        close = QPushButton("Close Room")
        close.setObjectName("accent")
        close.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for button in (print_button, pdf):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(close)
        column.addLayout(buttons)

    def _document(self) -> QTextDocument:
        document = QTextDocument()
        document.setHtml(self.bill.html())
        return document

    def print_bill(self) -> None:
        printer = QPrinter()
        if QPrintDialog(printer, self).exec():
            self._document().print_(printer)

    def save_pdf(self, path: str = "") -> None:
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save bill", f"{self.bill.room} bill.pdf", "PDF (*.pdf)"
            )
        if path:
            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(path)
            self._document().print_(printer)


class ShopSettings(QFrame):
    """The menu rooms can order from, and how rooms are charged."""

    COLUMNS = ("Name", "Category", "Price", "On menu")

    def __init__(self, store: DeskStore, changed: object = None) -> None:
        super().__init__()
        self.store = store
        self.changed = changed  # called after the menu changes, to tell the rooms
        self.setObjectName("panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        head = QLabel("MENU AND PRICES")
        head.setObjectName("panelHead")
        column.addWidget(head)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        column.addWidget(self.table, stretch=1)
        buttons = QHBoxLayout()
        for text, action in (
            ("Add Item", self.add_row),
            ("Remove", self.remove_row),
            ("Save Menu", self.save),
        ):
            button = QPushButton(text)
            button.clicked.connect(action)
            buttons.addWidget(button)
        buttons.addStretch()
        column.addLayout(buttons)

        form = QFormLayout()
        self.currency = QLineEdit(store.setting("currency", "$"))
        self.currency.setMaxLength(4)
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 100000)
        self.rate.setValue(float(store.setting("rate", DEFAULT_RATE)))
        self.minimum = QDoubleSpinBox()
        self.minimum.setRange(0, 100000)
        self.minimum.setValue(float(store.setting("minimum", "0")))
        self.rounding = QComboBox()
        for key, text in ROUNDING.items():
            self.rounding.addItem(text, key)
        self.rounding.setCurrentIndex(list(ROUNDING).index(store.setting("rounding", "minute")))
        self.block = QSpinBox()
        self.block.setRange(5, 120)
        self.block.setValue(int(store.setting("block", "15")))
        form.addRow("Currency", self.currency)
        form.addRow("Price per hour", self.rate)
        form.addRow("Minimum spend", self.minimum)
        form.addRow("Rooms without a time limit", self.rounding)
        form.addRow("Block minutes", self.block)
        column.addLayout(form)
        self.load()

    def load(self) -> None:
        products = self.store.products()
        self.table.setRowCount(0)
        for product in products:
            self._row(product)

    def _row(self, product: Product) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        name = QTableWidgetItem(product.name)
        name.setData(Qt.ItemDataRole.UserRole, product.product_id)
        self.table.setItem(row, 0, name)
        self.table.setItem(row, 1, QTableWidgetItem(product.category))
        self.table.setItem(row, 2, QTableWidgetItem(f"{product.price:g}"))
        active = QCheckBox()
        active.setChecked(product.active)
        self.table.setCellWidget(row, 3, active)

    def add_row(self) -> None:
        self._row(Product(0, "New item", "Drinks", 0.0))

    def remove_row(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            item = self.table.item(row, 0)
            product_id = int(item.data(Qt.ItemDataRole.UserRole) or 0) if item else 0
            if product_id:
                self.store.remove_product(product_id)
            self.table.removeRow(row)

    def save(self) -> None:
        for row in range(self.table.rowCount()):
            cells = [self.table.item(row, c) for c in range(3)]
            name = cells[0].text().strip() if cells[0] else ""
            if not name:
                continue
            try:
                price = float(cells[2].text()) if cells[2] else 0.0
            except ValueError:
                price = 0.0
            active = self.table.cellWidget(row, 3)
            product_id = int(cells[0].data(Qt.ItemDataRole.UserRole) or 0) if cells[0] else 0
            new_id = self.store.save_product(
                Product(
                    product_id,
                    name,
                    cells[1].text().strip() if cells[1] else "",
                    max(0.0, price),
                    isinstance(active, QCheckBox) and active.isChecked(),
                )
            )
            if cells[0] is not None:
                cells[0].setData(Qt.ItemDataRole.UserRole, new_id)
        self.store.set_setting("currency", self.currency.text().strip() or "$")
        self.store.set_setting("rate", f"{self.rate.value():g}")
        self.store.set_setting("minimum", f"{self.minimum.value():g}")
        self.store.set_setting("rounding", str(self.rounding.currentData()))
        self.store.set_setting("block", str(self.block.value()))
        if callable(self.changed):
            self.changed()
