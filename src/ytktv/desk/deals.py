"""Settings → Packages and Coupons: bundles sold at one price, codes that take money off,
and the members' birthday discount."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ytktv.desk.store import Coupon, DeskStore, Package

MAX_PRICE = 99_999_999


def end_of_day(day: QDate) -> float:
    start = datetime(day.year(), day.month(), day.day())
    return (start + timedelta(days=1)).timestamp() - 1


class PackageDialog(QDialog):
    def __init__(self, package: Package, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Package")
        form = QFormLayout(self)
        self.name = QLineEdit(package.name)
        self.name.setPlaceholderText("e.g. Party 3 hours")
        self.price = QDoubleSpinBox()
        self.price.setRange(0, MAX_PRICE)
        self.price.setValue(package.price)
        self.hours = QDoubleSpinBox()
        self.hours.setRange(0.5, 24)
        self.hours.setSingleStep(0.5)
        self.hours.setSuffix(" h")
        self.hours.setValue(package.minutes / 60 or 3)
        self.includes = QLineEdit(package.includes)
        self.includes.setPlaceholderText("e.g. 1 × Beer tower, 1 × Fruit plate")
        self.active = QCheckBox("Offered when a room opens")
        self.active.setChecked(package.active)
        form.addRow("Name", self.name)
        form.addRow("Price", self.price)
        form.addRow("Room time", self.hours)
        form.addRow("Comes with", self.includes)
        form.addRow("", self.active)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.package_id = package.package_id

    def package(self) -> Package:
        return Package(
            self.package_id,
            self.name.text().strip() or "Package",
            self.price.value(),
            round(self.hours.value() * 60),
            self.includes.text().strip(),
            self.active.isChecked(),
        )


class CouponDialog(QDialog):
    def __init__(self, coupon: Coupon, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coupon")
        form = QFormLayout(self)
        self.code = QLineEdit(coupon.code)
        self.code.setPlaceholderText("e.g. SUMMER20")
        self.kind = QComboBox()
        self.kind.addItem("Percent off the bill", "percent")
        self.kind.addItem("Amount off the bill", "amount")
        self.kind.setCurrentIndex(0 if coupon.kind == "percent" else 1)
        self.value = QDoubleSpinBox()
        self.value.setRange(0.01, MAX_PRICE)
        self.value.setValue(coupon.value or 10)
        self.uses = QSpinBox()
        self.uses.setRange(0, 100_000)
        self.uses.setSpecialValueText("Any number")
        self.uses.setValue(coupon.uses_left or 0)
        self.expires = QCheckBox("Expires after")
        self.until = QDateEdit(QDate.currentDate().addMonths(1))
        self.until.setCalendarPopup(True)
        if coupon.expires is not None:
            self.expires.setChecked(True)
            day = time.localtime(coupon.expires)
            self.until.setDate(QDate(day.tm_year, day.tm_mon, day.tm_mday))
        self.active = QCheckBox("Can be used")
        self.active.setChecked(coupon.active)
        expiry = QHBoxLayout()
        expiry.addWidget(self.expires)
        expiry.addWidget(self.until)
        form.addRow("Code", self.code)
        form.addRow("Type", self.kind)
        form.addRow("Value", self.value)
        form.addRow("Uses left", self.uses)
        form.addRow("", expiry)
        form.addRow("", self.active)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def coupon(self) -> Coupon:
        return Coupon(
            self.code.text().strip().upper(),
            str(self.kind.currentData()),
            self.value.value(),
            self.uses.value() or None,
            end_of_day(self.until.date()) if self.expires.isChecked() else None,
            self.active.isChecked(),
        )


class DealsSettings(QFrame):
    """Packages, coupons and the birthday discount."""

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        self.setObjectName("panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        head = QLabel("PACKAGES AND COUPONS")
        head.setObjectName("panelHead")
        column.addWidget(head)
        note = QLabel(
            "A package sells room time and items at one price; pick it when you open a room."
            " Time beyond it is charged by the hour. Coupons are typed in at the till."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        column.addWidget(note)
        lists = QHBoxLayout()
        self.package_list = QListWidget()
        self.coupon_list = QListWidget()
        for title, widget, add, edit, remove in (
            ("Packages", self.package_list, self.add_package, self.edit_package,
             self.remove_package),
            ("Coupons", self.coupon_list, self.add_coupon, self.edit_coupon, self.remove_coupon),
        ):  # fmt: skip
            box = QVBoxLayout()
            box.addWidget(QLabel(title))
            widget.setMaximumHeight(150)
            widget.itemDoubleClicked.connect(lambda _item, e=edit: e())
            box.addWidget(widget)
            row = QHBoxLayout()
            for text, action in (("Add…", add), ("Edit…", edit), ("Remove", remove)):
                button = QPushButton(text)
                button.clicked.connect(lambda _c=False, a=action: a())
                row.addWidget(button)
            row.addStretch()
            box.addLayout(row)
            lists.addLayout(box)
        column.addLayout(lists)
        form = QFormLayout()
        self.birthday = QSpinBox()
        self.birthday.setRange(0, 100)
        self.birthday.setSuffix(" %")
        self.birthday.setSpecialValueText("None")
        self.birthday.setValue(int(float(store.setting("birthday_discount", "0"))))
        self.birthday.valueChanged.connect(lambda v: store.set_setting("birthday_discount", str(v)))
        form.addRow("Members' birthday discount", self.birthday)
        column.addLayout(form)
        self.load()

    def load(self) -> None:
        currency = self.store.setting("currency", "$")
        self.package_list.clear()
        for package in self.store.packages():
            off = "" if package.active else "  (off)"
            item = QListWidgetItem(
                f"{package.name} · {package.minutes / 60:g} h · {currency}{package.price:g}{off}"
            )
            item.setData(Qt.ItemDataRole.UserRole, package)
            self.package_list.addItem(item)
        self.coupon_list.clear()
        for coupon in self.store.coupons():
            uses = "any uses" if coupon.uses_left is None else f"{coupon.uses_left} left"
            until = (
                time.strftime(" · until %Y-%m-%d", time.localtime(coupon.expires))
                if coupon.expires
                else ""
            )
            off = "" if coupon.active else "  (off)"
            item = QListWidgetItem(f"{coupon.code} · {coupon.label(currency)} · {uses}{until}{off}")
            item.setData(Qt.ItemDataRole.UserRole, coupon)
            self.coupon_list.addItem(item)

    def _picked(self, widget: QListWidget) -> object:
        item = widget.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def add_package(self, package: Package | None = None) -> None:
        if package is None:
            dialog = PackageDialog(Package(0, "", 0.0, 180), self)
            if not dialog.exec():
                return
            package = dialog.package()
        self.store.save_package(package)
        self.load()

    def edit_package(self) -> None:
        package = self._picked(self.package_list)
        if isinstance(package, Package):
            dialog = PackageDialog(package, self)
            if dialog.exec():
                self.store.save_package(dialog.package())
                self.load()

    def remove_package(self) -> None:
        package = self._picked(self.package_list)
        if isinstance(package, Package):
            self.store.remove_package(package.package_id)
            self.load()

    def add_coupon(self, coupon: Coupon | None = None) -> None:
        if coupon is None:
            dialog = CouponDialog(Coupon("", "percent", 10.0), self)
            if not dialog.exec():
                return
            coupon = dialog.coupon()
        if not coupon.code:
            return
        try:
            self.store.save_coupon(coupon)
        except ValueError as exc:
            QMessageBox.warning(self, "Coupon", str(exc))
        self.load()

    def edit_coupon(self) -> None:
        coupon = self._picked(self.coupon_list)
        if isinstance(coupon, Coupon):
            dialog = CouponDialog(coupon, self)
            if dialog.exec():
                if dialog.coupon().code != coupon.code:
                    self.store.remove_coupon(coupon.code)
                self.add_coupon(dialog.coupon())

    def remove_coupon(self) -> None:
        coupon = self._picked(self.coupon_list)
        if isinstance(coupon, Coupon):
            self.store.remove_coupon(coupon.code)
            self.load()
