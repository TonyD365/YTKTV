"""Parts of the desk window: a room's orders, the bill, and the shop settings."""

from __future__ import annotations

import time
from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QTextDocument
from PySide6.QtPrintSupport import QPrintDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
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

from ytktv import __version__
from ytktv.desk import lock, receipt
from ytktv.desk.billing import DEFAULT_RATE, PAYMENTS, ROUNDING, Bill
from ytktv.desk.server import Hub
from ytktv.desk.store import LOW_STOCK, DeskStore, Member, Product


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
    """The till: the bill, a member, a discount, dropping small change and how it is paid.

    It can be printed or saved as a PDF. Pressing Close Room takes a member's balance when
    they pay with it and adds their points; the caller then closes the room.
    """

    def __init__(
        self, bill: Bill, parent: QWidget | None = None, store: DeskStore | None = None
    ) -> None:
        super().__init__(parent)
        self.bill = bill
        self.store = store
        self.member: Member | None = None
        self.setWindowTitle(f"Bill · {bill.room}")
        self.resize(560, 720)
        column = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setStyleSheet("background: white; color: black; border-radius: 10px;")
        column.addWidget(self.view, stretch=1)

        form = QFormLayout()
        member_row = QHBoxLayout()
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("Member's phone number")
        self.phone.returnPressed.connect(self.find_member)
        find = QPushButton("Find")
        find.clicked.connect(self.find_member)
        member_row.addWidget(self.phone, stretch=1)
        member_row.addWidget(find)
        self.member_label = QLabel("No member")
        self.member_label.setObjectName("muted")
        self.discount = QSpinBox()
        self.discount.setRange(0, 100)
        self.discount.setSuffix(" %")
        self.round_to = QComboBox()
        for label, value in (
            ("Keep", 0.0),
            ("To a whole number", 1.0),
            ("To the nearest 10 below", 10.0),
        ):
            self.round_to.addItem(label, value)
        self.payment = QComboBox()
        self.payment.addItems(list(PAYMENTS))
        for field in (self.discount, self.round_to, self.payment):
            steady(field)
        self.discount.valueChanged.connect(self.update_bill)
        self.round_to.currentIndexChanged.connect(self.update_bill)
        self.payment.currentIndexChanged.connect(self.update_bill)
        if store is not None:
            form.addRow("Member", member_row)
            form.addRow("", self.member_label)
        form.addRow("Discount", self.discount)
        if store is not None:
            coupon_row = QHBoxLayout()
            self.coupon = QLineEdit()
            self.coupon.setPlaceholderText("Coupon code")
            self.coupon.returnPressed.connect(self.apply_coupon)
            apply = QPushButton("Apply")
            apply.clicked.connect(self.apply_coupon)
            coupon_row.addWidget(self.coupon, stretch=1)
            coupon_row.addWidget(apply)
            form.addRow("Coupon", coupon_row)
        form.addRow("Drop small change", self.round_to)
        form.addRow("Paid by", self.payment)
        column.addLayout(form)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #ff6b8b;")
        column.addWidget(self.error)

        buttons = QHBoxLayout()
        print_button = QPushButton("Print…")
        print_button.clicked.connect(self.print_bill)
        pdf = QPushButton("Save PDF…")
        pdf.clicked.connect(self.save_pdf)
        receipt_button = QPushButton("🧾 Receipt")
        receipt_button.setToolTip("Print a receipt on the receipt printer (Settings → Receipts)")
        receipt_button.clicked.connect(lambda: self.print_receipt())
        close = QPushButton("Close Room")
        close.setObjectName("accent")
        close.clicked.connect(self.settle)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        for button in (print_button, pdf, receipt_button):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(close)
        column.addLayout(buttons)
        self.update_bill()

    def print_receipt(self, printer: QPrinter | None = None) -> bool:
        """Print a receipt; asks which printer when none is set in Settings."""
        if self.store is None:
            return False
        self.update_bill()
        if printer is None:
            width = int(self.store.setting("receipt_width", "58"))
            printer = receipt.receipt_printer(
                self.store.setting("receipt_printer", receipt.ASK), width
            )
            if (
                self.store.setting("receipt_printer", receipt.ASK) == receipt.ASK
                and not QPrintDialog(printer, self).exec()
            ):
                return False
            receipt.fit_paper(printer, width)  # the dialog may pick another printer
        receipt.print_receipt(self.store, self.bill, printer)
        return True

    def find_member(self) -> None:
        if self.store is None:
            return
        self.member = self.store.member_by_phone(self.phone.text())
        self.update_bill()

    def apply_coupon(self, code: str | None = None) -> bool:
        """Take a coupon off the bill; False (and the reason shown) when it cannot be used."""
        if self.store is None:
            return False
        code = (self.coupon.text() if code is None else code).strip()
        self.bill.coupon, self.bill.coupon_percent, self.bill.coupon_amount = "", 0.0, 0.0
        if code:
            try:
                coupon = self.store.coupon(code)
            except ValueError as exc:
                self.update_bill()
                self.error.setText(str(exc))
                return False
            self.bill.coupon = coupon.code
            if coupon.kind == "percent":
                self.bill.coupon_percent = coupon.value
            else:
                self.bill.coupon_amount = coupon.value
        self.update_bill()
        return bool(code)

    def update_bill(self) -> None:
        bill, store, member = self.bill, self.store, self.member
        bill.member = member.name if member else ""
        bill.member_off = float(store.setting("member_discount", "10")) if member and store else 0
        today = time.strftime("%m-%d")
        birthday = member is not None and store is not None and member.birthday == today
        bill.birthday_off = (
            float(store.setting("birthday_discount", "0")) if birthday and store else 0
        )
        bill.discount = float(self.discount.value())
        bill.round_to = float(self.round_to.currentData() or 0)
        bill.payment = self.payment.currentText()
        if member is not None:
            self.member_label.setText(
                f"{member.name} · balance {bill.currency}{member.balance:.2f}"
                f" · {member.points} points · members save {bill.member_off:g}%"
            )
        elif self.phone.text().strip():
            self.member_label.setText("No member with that phone number")
        self.view.setHtml(bill.html())
        self.error.clear()

    def settle(self) -> None:
        """Take payment from the member's balance if that is how they pay, then close."""
        self.update_bill()
        bill, store, member = self.bill, self.store, self.member
        if bill.payment == "Member balance":
            if member is None or store is None:
                self.error.setText("Find the member first to pay from their balance.")
                return
            try:
                store.pay_from_balance(member.member_id, bill.total)
            except ValueError:
                self.error.setText(
                    f"Not enough balance: {bill.currency}{member.balance:.2f}. Top up first."
                )
                return
        if member is not None and store is not None:
            per_unit = float(store.setting("points_per_unit", "1"))
            store.add_points(member.member_id, int(bill.total * per_unit))
        if store is not None and store.setting("receipt_auto", "0") == "1":
            self.print_receipt()
        self.accept()

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


MAX_PRICE = 99_999_999  # room for currencies like yen, won or dong


class _IgnoreWheel(QObject):
    """Scrolling the settings page must not change the number or choice under the mouse."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if (
            event.type() == QEvent.Type.Wheel
            and isinstance(watched, QWidget)
            and not watched.hasFocus()
        ):
            parent = watched.parentWidget()
            if parent is not None:  # hand the scroll to the page instead of the value
                QApplication.sendEvent(parent, event)
            return True
        return False


_IGNORE_WHEEL = _IgnoreWheel()


def steady(widget: QWidget) -> QWidget:
    """Only take the mouse wheel once clicked into."""
    widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    widget.installEventFilter(_IGNORE_WHEEL)
    if isinstance(widget, QAbstractSpinBox):
        widget.setMinimumWidth(140)
    return widget


class OnMenu(QCheckBox):
    """The On menu switch in the menu table: says what it means, not just a colour."""

    def __init__(self, on: bool) -> None:
        super().__init__()
        self.toggled.connect(self._label)
        self.setChecked(on)
        self._label(on)

    def _label(self, on: bool) -> None:
        self.setText("On menu" if on else "Hidden")


class ShopSettings(QFrame):
    """The menu rooms can order from, and how rooms are charged."""

    COLUMNS = ("Name", "Category", "Price", "Stock", "On menu")

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
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        # The console's big text fields do not fit in a table cell: edit in a plain one.
        self.table.setStyleSheet(
            "QTableWidget QLineEdit { padding: 0 8px; margin: 0; border: 1px solid #2ee6ff;"
            " border-radius: 4px; min-height: 0; font-size: 14px; background: #1a1430; }"
            " QCheckBox { padding-left: 10px; }"
        )
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
        self.rate.setGroupSeparatorShown(True)
        self.rate.setRange(0, MAX_PRICE)
        self.rate.setValue(float(store.setting("rate", DEFAULT_RATE)))
        self.minimum = QDoubleSpinBox()
        self.minimum.setGroupSeparatorShown(True)
        self.minimum.setRange(0, MAX_PRICE)
        self.minimum.setValue(float(store.setting("minimum", "0")))
        self.rounding = QComboBox()
        for key, text in ROUNDING.items():
            self.rounding.addItem(text, key)
        self.rounding.setCurrentIndex(list(ROUNDING).index(store.setting("rounding", "minute")))
        self.block = QSpinBox()
        self.block.setRange(5, 120)
        self.block.setValue(int(store.setting("block", "15")))
        for field in (self.rate, self.minimum, self.rounding, self.block):
            steady(field)
        form.addRow("Currency", self.currency)
        form.addRow("Price per hour", self.rate)
        form.addRow("Minimum spend", self.minimum)
        form.addRow("Rooms without a time limit", self.rounding)
        form.addRow("Block minutes", self.block)
        self.member_discount = QSpinBox()
        self.member_discount.setRange(0, 100)
        self.member_discount.setSuffix(" %")
        self.member_discount.setValue(int(float(store.setting("member_discount", "10"))))
        self.points_per_unit = QSpinBox()
        self.points_per_unit.setRange(0, 100)
        self.points_per_unit.setValue(int(float(store.setting("points_per_unit", "1"))))
        steady(self.member_discount)
        steady(self.points_per_unit)
        form.addRow("Members save", self.member_discount)
        form.addRow("Member points per 1 spent", self.points_per_unit)
        self.low_stock = QSpinBox()
        self.low_stock.setRange(0, 999)
        self.low_stock.setSpecialValueText("Never")
        self.low_stock.setValue(int(store.setting("low_stock", str(LOW_STOCK))))
        self.low_stock.setToolTip("Warn in the service bar when this many or fewer are left")
        steady(self.low_stock)
        form.addRow("Warn when stock is down to", self.low_stock)
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
        stock = QTableWidgetItem("" if product.stock is None else str(product.stock))
        stock.setToolTip("Leave empty if it never runs out")
        self.table.setItem(row, 3, stock)
        self.table.setCellWidget(row, 4, OnMenu(product.active))

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
            active = self.table.cellWidget(row, 4)
            stock_cell = self.table.item(row, 3)
            stock_text = stock_cell.text().strip() if stock_cell else ""
            stock = int(stock_text) if stock_text.isdigit() else None
            product_id = int(cells[0].data(Qt.ItemDataRole.UserRole) or 0) if cells[0] else 0
            new_id = self.store.save_product(
                Product(
                    product_id,
                    name,
                    cells[1].text().strip() if cells[1] else "",
                    max(0.0, price),
                    isinstance(active, QCheckBox) and active.isChecked(),
                    stock,
                )
            )
            if cells[0] is not None:
                cells[0].setData(Qt.ItemDataRole.UserRole, new_id)
        self.store.set_setting("currency", self.currency.text().strip() or "$")
        self.store.set_setting("rate", f"{self.rate.value():g}")
        self.store.set_setting("minimum", f"{self.minimum.value():g}")
        self.store.set_setting("rounding", str(self.rounding.currentData()))
        self.store.set_setting("block", str(self.block.value()))
        self.store.set_setting("member_discount", str(self.member_discount.value()))
        self.store.set_setting("points_per_unit", str(self.points_per_unit.value()))
        self.store.set_setting("low_stock", str(self.low_stock.value()))
        if callable(self.changed):
            self.changed()


class BroadcastDialog(QDialog):
    """Send a message to every open room, or to some of them."""

    def __init__(
        self,
        store: DeskStore,
        hub: Hub,
        rooms: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.store, self.hub = store, hub
        self.setWindowTitle("Broadcast" if rooms is None else "Message")
        self.resize(460, 480)
        column = QVBoxLayout(self)
        self.text = QLineEdit()
        self.text.setPlaceholderText("e.g. Dinner is ready!")
        self.text.setMaxLength(300)
        column.addWidget(QLabel("Message"))
        column.addWidget(self.text)
        column.addWidget(QLabel("Rooms"))
        self.checks: dict[str, QCheckBox] = {}
        for room in store.rooms():
            if room.is_open:
                box = QCheckBox(room.name)
                box.setChecked(rooms is None or room.room_id in rooms)
                column.addWidget(box)
                self.checks[room.room_id] = box
        if not self.checks:
            column.addWidget(QLabel("No room is open."))
        self.length = QComboBox()
        for label, seconds in (
            ("10 seconds", 10),
            ("30 seconds", 30),
            ("Until they press Got it", None),
        ):
            self.length.addItem(label, seconds)
        self.pause = QCheckBox("Pause the music")
        self.sound = QCheckBox("Play a sound")
        self.sound.setChecked(True)
        form = QFormLayout()
        form.addRow("Show for", self.length)
        column.addLayout(form)
        column.addWidget(self.pause)
        column.addWidget(self.sound)
        column.addStretch()
        send = QPushButton("Send")
        send.setObjectName("accent")
        send.clicked.connect(self.send)
        column.addWidget(send)

    def send(self) -> int:
        """Send to the ticked rooms; returns how many."""
        text = self.text.text().strip()
        targets = [room_id for room_id, box in self.checks.items() if box.isChecked()]
        if not text or not targets:
            return 0
        message = {
            "type": "message",
            "text": text,
            "seconds": self.length.currentData(),
            "pause": self.pause.isChecked(),
            "sound": self.sound.isChecked(),
        }
        for room_id in targets:
            self.hub.send_soon(room_id, message)
        self.accept()
        return len(targets)


class SecuritySettings(QFrame):
    """The desk password, and when the desk locks itself."""

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        self.setObjectName("panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        head = QLabel("DESK PASSWORD")
        head.setObjectName("panelHead")
        column.addWidget(head)
        self.status = QLabel()
        self.status.setObjectName("muted")
        column.addWidget(self.status)
        row = QHBoxLayout()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("New password")
        set_button = QPushButton("Set Password")
        set_button.clicked.connect(self.set_password)
        off = QPushButton("Turn Off")
        off.clicked.connect(lambda: self.turn_off())
        row.addWidget(self.password, stretch=1)
        row.addWidget(set_button)
        row.addWidget(off)
        column.addLayout(row)
        form = QFormLayout()
        self.lock_after = QComboBox()
        self.lock_after.addItems(list(lock.LOCK_AFTER))
        self.lock_after.setCurrentText(store.setting("lock_after", "Never"))
        steady(self.lock_after)
        self.lock_after.currentTextChanged.connect(lambda v: store.set_setting("lock_after", v))
        form.addRow("Lock when idle for", self.lock_after)
        column.addLayout(form)
        self.refresh()

    def refresh(self) -> None:
        on = lock.has_password(self.store)
        self.status.setText(
            "On: the desk asks for the password when it starts, after being idle, and"
            " before unbinding a room."
            if on
            else "Off: anyone at this computer can use the desk."
        )
        self.lock_after.setEnabled(on)

    def set_password(self) -> None:
        if len(self.password.text()) >= 4:
            lock.set_password(self.store, self.password.text())
            self.password.clear()
        self.refresh()

    def turn_off(self, password: str | None = None) -> None:
        if lock.has_password(self.store):
            if password is None:
                password, ok = QInputDialog.getText(
                    self, "Turn off password", "Current password:", QLineEdit.EchoMode.Password
                )
                if not ok:
                    return
            if not lock.check(self.store, password):
                return
        lock.set_password(self.store, None)
        self.refresh()


class ReceiptSettings(QFrame):
    """The receipt printer: which one, the paper, the shop's name and a closing line."""

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        self.setObjectName("panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        head = QLabel("RECEIPTS")
        head.setObjectName("panelHead")
        note = QLabel(
            "Any 58 mm or 80 mm receipt printer installed on this computer works through its"
            " driver (set the driver to cut the paper after each receipt if it can)."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        column.addWidget(head)
        column.addWidget(note)
        form = QFormLayout()
        self.printer = QComboBox()
        self.printer.addItems(receipt.printers())
        self.printer.setCurrentText(store.setting("receipt_printer", receipt.ASK))
        self.paper = QComboBox()
        for mm in receipt.WIDTHS:
            self.paper.addItem(f"{mm} mm", mm)
        self.paper.setCurrentIndex(receipt.WIDTHS.index(int(store.setting("receipt_width", "58"))))
        self.shop = QLineEdit(store.setting("shop_name", "YTKTV"))
        self.footer = QLineEdit(store.setting("receipt_footer", "Thank you! See you again."))
        self.auto = QCheckBox("Print a receipt when a room checks out")
        self.auto.setChecked(store.setting("receipt_auto", "0") == "1")
        self.copies = QSpinBox()
        self.copies.setRange(1, 3)
        self.copies.setValue(int(store.setting("receipt_copies", "1")))
        for field in (self.printer, self.paper, self.copies):
            steady(field)
        form.addRow("Printer", self.printer)
        form.addRow("Paper", self.paper)
        form.addRow("Shop name", self.shop)
        form.addRow("Closing line", self.footer)
        form.addRow("Copies", self.copies)
        form.addRow("", self.auto)
        column.addLayout(form)
        save = QPushButton("Save Receipt Settings")
        save.clicked.connect(self.save)
        column.addWidget(save, alignment=Qt.AlignmentFlag.AlignLeft)

    def save(self) -> None:
        self.store.set_setting("receipt_printer", self.printer.currentText())
        self.store.set_setting("receipt_width", str(self.paper.currentData()))
        self.store.set_setting("shop_name", self.shop.text().strip() or "YTKTV")
        self.store.set_setting("receipt_footer", self.footer.text().strip())
        self.store.set_setting("receipt_auto", "1" if self.auto.isChecked() else "0")
        self.store.set_setting("receipt_copies", str(self.copies.value()))


class UpdateSettings(QFrame):
    """The desk's version, whether it updates itself, and a button to check right now."""

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        self.check_now: Callable[[], None] | None = None
        self.setObjectName("panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        head = QLabel("UPDATES")
        head.setObjectName("panelHead")
        version = QLabel(f"YTKTV Desk {__version__}")
        self.auto = QCheckBox("Check for updates automatically and download them in the background")
        self.auto.setChecked(store.setting("auto_update", "1") == "1")
        self.auto.toggled.connect(lambda on: store.set_setting("auto_update", "1" if on else "0"))
        self.state = QLabel("Updates install only when you press Update, never by themselves.")
        self.state.setObjectName("muted")
        self.state.setWordWrap(True)
        self.check_button = QPushButton("Check Now")
        self.check_button.clicked.connect(lambda: self.check_now and self.check_now())
        for widget in (head, version, self.auto, self.state):
            column.addWidget(widget)
        column.addWidget(self.check_button, alignment=Qt.AlignmentFlag.AlignLeft)

    def automatic(self) -> bool:
        return self.store.setting("auto_update", "1") == "1"
