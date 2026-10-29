"""The desk's Bookings and Records tabs."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from datetime import date, datetime, timedelta

from PySide6.QtCore import QDate, QDateTime, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ytktv.desk import reports
from ytktv.desk.store import Booking, DeskStore, Member, Visit

LENGTHS = {"1 hour": 60, "2 hours": 120, "3 hours": 180, "No time limit": None}
STATUS_TEXT = {
    "booked": "Booked",
    "arrived": "Arrived",
    "cancelled": "Cancelled",
    "no_show": "No-show",
}


def day_bounds(day: QDate) -> tuple[float, float]:
    start = datetime(day.year(), day.month(), day.day())
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


class Timeline(QWidget):
    """One row per room across the day; each booking is a bar."""

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        self.day = QDate.currentDate()
        self.setMinimumHeight(140)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        rooms = self.store.rooms()
        start, end = day_bounds(self.day)
        bookings = [b for b in self.store.bookings(start, end) if b.status in ("booked", "arrived")]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        label_w, top = 130, 22
        width = self.width() - label_w - 10
        row_h = max(24, min(44, (self.height() - top) // max(1, len(rooms))))
        p.setPen(QColor("#9a93b8"))
        for hour in range(0, 25, 3):
            x = label_w + width * hour / 24
            p.drawText(QRectF(x - 20, 0, 40, 18), Qt.AlignmentFlag.AlignCenter, f"{hour:02d}")
            p.setPen(QColor("#2a2445"))
            p.drawLine(int(x), top, int(x), top + row_h * len(rooms))
            p.setPen(QColor("#9a93b8"))
        for row, room in enumerate(rooms):
            y = top + row * row_h
            p.setPen(QColor("white"))
            p.drawText(QRectF(4, y, label_w - 8, row_h), Qt.AlignmentFlag.AlignVCenter, room.name)
            for b in bookings:
                if b.room_id != room.room_id:
                    continue
                x0 = label_w + width * max(0.0, (b.starts - start) / 86400)
                length = (b.minutes or 180) * 60
                x1 = label_w + width * min(1.0, (b.starts + length - start) / 86400)
                colour = QColor("#ff3d9a" if b.status == "booked" else "#1d9e75")
                p.setBrush(colour)
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(x0, y + 4, max(6.0, x1 - x0), row_h - 8), 6, 6)
                p.setPen(QColor("white"))
                p.drawText(
                    QRectF(x0 + 6, y, max(6.0, x1 - x0) - 8, row_h),
                    Qt.AlignmentFlag.AlignVCenter,
                    b.guest or "Booked",
                )
        p.end()


class BookingDialog(QDialog):
    def __init__(self, store: DeskStore, day: QDate, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("New booking")
        form = QFormLayout(self)
        self.room = QComboBox()
        for room in store.rooms():
            self.room.addItem(room.name, room.room_id)
        self.when = QDateTimeEdit(QDateTime(day, QDateTime.currentDateTime().time()))
        self.when.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.when.setCalendarPopup(True)
        self.length = QComboBox()
        self.length.addItems(list(LENGTHS))
        self.length.setCurrentIndex(1)
        self.guest, self.contact, self.note = QLineEdit(), QLineEdit(), QLineEdit()
        for label, widget in (
            ("Room", self.room),
            ("Starts", self.when),
            ("Length", self.length),
            ("Guest", self.guest),
            ("Contact", self.contact),
            ("Note", self.note),
        ):
            form.addRow(label, widget)
        save = QPushButton("Save Booking")
        save.setObjectName("accent")
        save.clicked.connect(lambda: self.save())
        form.addRow(save)

    def booking(self) -> Booking:
        return Booking(
            0,
            str(self.room.currentData()),
            float(self.when.dateTime().toSecsSinceEpoch()),
            LENGTHS[self.length.currentText()],
            self.guest.text().strip(),
            self.contact.text().strip(),
            self.note.text().strip(),
        )

    def save(self, confirm_clash: bool = True) -> int:
        booking = self.booking()
        if not booking.room_id or booking.room_id == "None":
            return 0
        clashes = self.store.clashes(booking.room_id, booking.starts, booking.minutes)
        if clashes and confirm_clash:
            when = ", ".join(time.strftime("%H:%M", time.localtime(c.starts)) for c in clashes)
            answer = QMessageBox.question(
                self, "Room already booked", f"This room is booked at {when}. Book it anyway?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return 0
        booking_id = self.store.book(booking)
        self.accept()
        return booking_id


class BookingsPage(QWidget):
    COLUMNS = ("Time", "Room", "Guest", "Length", "Contact", "Note", "Status")

    def __init__(self, store: DeskStore, check_in: Callable[[Booking], None]) -> None:
        super().__init__()
        self.store, self.check_in = store, check_in
        row = QHBoxLayout(self)
        row.setContentsMargins(24, 18, 24, 18)
        left = QVBoxLayout()
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(False)
        self.calendar.selectionChanged.connect(self.refresh)
        left.addWidget(self.calendar)
        new = QPushButton("＋ New Booking")
        new.setObjectName("accent")
        new.clicked.connect(self.new_booking)
        left.addWidget(new)
        left.addStretch()
        row.addLayout(left)
        right = QVBoxLayout()
        self.timeline = Timeline(store)
        right.addWidget(self.timeline, stretch=1)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        right.addWidget(self.table, stretch=2)
        buttons = QHBoxLayout()
        for text, status in (
            ("Check In", "arrived"),
            ("Cancel Booking", "cancelled"),
            ("No-show", "no_show"),
        ):
            button = QPushButton(text)
            button.clicked.connect(lambda _c=False, s=status: self.set_status(s))
            buttons.addWidget(button)
        buttons.addStretch()
        right.addLayout(buttons)
        row.addLayout(right, stretch=1)
        self._shown: list[Booking] = []
        self.refresh()

    def refresh(self) -> None:
        day = self.calendar.selectedDate()
        self.timeline.day = day
        self.timeline.update()
        names = {r.room_id: r.name for r in self.store.rooms()}
        self._shown = self.store.bookings(*day_bounds(day))
        self.table.setRowCount(0)
        for b in self._shown:
            row = self.table.rowCount()
            self.table.insertRow(row)
            length = (
                "No limit" if b.minutes is None else f"{b.minutes // 60}h {b.minutes % 60:02d}m"
            )
            for column, text in enumerate(
                (
                    time.strftime("%H:%M", time.localtime(b.starts)),
                    names.get(b.room_id, "?"),
                    b.guest,
                    length,
                    b.contact,
                    b.note,
                    STATUS_TEXT.get(b.status, b.status),
                )
            ):
                self.table.setItem(row, column, QTableWidgetItem(text))

    def new_booking(self) -> None:
        if BookingDialog(self.store, self.calendar.selectedDate(), self).exec():
            self.refresh()

    def selected(self) -> Booking | None:
        row = self.table.currentRow()
        return self._shown[row] if 0 <= row < len(self._shown) else None

    def set_status(self, status: str) -> None:
        booking = self.selected()
        if booking is None or booking.status != "booked":
            return
        self.store.set_booking_status(booking.booking_id, status)
        if status == "arrived":
            self.check_in(booking)
        self.refresh()


class TakingsChart(QWidget):
    """Bars of takings: per hour of a day, or per day of a week or month."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumHeight(150)
        self.bars: list[tuple[str, float]] = []

    def set_bars(self, bars: list[tuple[str, float]]) -> None:
        self.bars = bars
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 - Qt's name
        if not self.bars:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = max(amount for _, amount in self.bars) or 1.0
        width = self.width() / len(self.bars)
        chart = self.height() - 20
        every = max(1, len(self.bars) // 16)  # label every bar only when they fit
        for i, (label, amount) in enumerate(self.bars):
            height = chart * amount / top
            bar = QRectF(i * width + width * 0.15, chart - height, width * 0.7, height)
            painter.fillRect(bar, QColor("#e0409b" if amount else "#3a3352"))
            if i % every == 0:
                painter.setPen(QColor("#9a93b8"))
                painter.drawText(
                    QRectF(i * width, chart + 2, width * every, 18),
                    int(Qt.AlignmentFlag.AlignLeft),
                    label,
                )
        painter.end()


class RecordsPage(QWidget):
    COLUMNS = ("Closed", "Room", "Guest", "Time", "Songs", "Total")

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 18, 24, 18)
        top = QHBoxLayout()
        self.period = QComboBox()
        self.period.addItems(reports.PERIODS)
        self.period.currentIndexChanged.connect(self.refresh)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.dateChanged.connect(self.refresh)
        self.summary = QLabel()
        self.summary.setStyleSheet("color: white; font-size: 18px; font-weight: 700;")
        export = QPushButton("Export CSV")
        export.setToolTip("Every session in this period, as a spreadsheet Excel can open")
        export.clicked.connect(self.export)
        top.addWidget(self.period)
        top.addWidget(self.day)
        top.addSpacing(24)
        top.addWidget(self.summary, stretch=1)
        top.addWidget(export)
        column.addLayout(top)
        self.chart = TakingsChart()
        column.addWidget(self.chart)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        column.addWidget(self.table, stretch=1)
        self.top_songs = QLabel()
        self.top_songs.setObjectName("muted")
        self.top_songs.setWordWrap(True)
        column.addWidget(self.top_songs)
        self.refresh()

    def picked_day(self) -> date:
        picked = self.day.date()
        return date(picked.year(), picked.month(), picked.day())

    def visits(self) -> list[Visit]:
        return reports.visits_in(self.store, self.picked_day(), self.period.currentText())

    def export(self, _checked: bool = False, path: str | None = None) -> None:
        if path is None:
            day = self.day.date().toString("yyyy-MM-dd")
            name = f"ytktv-{self.period.currentText().lower()}-{day}.csv"
            path, _ = QFileDialog.getSaveFileName(self, "Export CSV", name, "CSV (*.csv)")
        if path:
            reports.export_csv(self.visits(), path)

    def refresh(self) -> None:
        period = self.period.currentText()
        buckets = reports.period_buckets(self.picked_day(), period)
        visits = self.visits()
        amounts = reports.takings(visits, buckets)
        self.chart.set_bars([(b[0], a) for b, a in zip(buckets, amounts, strict=True)])
        currency = self.store.setting("currency", "$")
        hours = sum(v.closed_at - v.opened_at for v in visits) / 3600
        revenue = sum(v.total for v in visits)
        self.summary.setText(
            f"{len(visits)} sessions  ·  {hours:.1f} hours  ·  {currency}{revenue:.2f}"
        )
        self.table.setRowCount(0)
        stamp = "%H:%M" if period == "Day" else "%m-%d %H:%M"
        for v in visits:
            row = self.table.rowCount()
            self.table.insertRow(row)
            minutes = int((v.closed_at - v.opened_at) // 60)
            cells = (
                time.strftime(stamp, time.localtime(v.closed_at)),
                v.room,
                v.guest,
                f"{minutes // 60}h {minutes % 60:02d}m",
                str(len(v.songs)),
                f"{currency}{v.total:.2f}",
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setToolTip(
                    "\n".join(f"{t}: {currency}{a:.2f}" for t, a in v.lines)
                    + ("\n\nSongs:\n" + "\n".join(v.songs) if v.songs else "")
                )
                self.table.setItem(row, column, item)
        songs = Counter(song for v in visits for song in v.songs).most_common(5)
        self.top_songs.setText(
            "Most sung: " + ", ".join(f"{s} ({n})" for s, n in songs) if songs else ""
        )


def shift_report(store: DeskStore, now: float | None = None) -> str:
    """Everything since the last hand-over, as HTML for the screen or the printer."""
    now = time.time() if now is None else now
    started = float(store.setting("shift_started", "0") or 0) or day_bounds(QDate.currentDate())[0]
    # Strictly after the hand-over: Windows' clock can give both the same time.
    visits = [v for v in store.history(started, now + 1) if v.closed_at > started]
    currency = store.setting("currency", "$")
    rooms_fee = sum(a for v in visits for t, a in v.lines if t.startswith("Room ·"))
    sold: Counter[str] = Counter()
    for v in visits:
        for text, _amount in v.lines:
            if not text.startswith("Room ·") and " × " in text:
                name, qty = text.rsplit(" × ", 1)
                sold[name] += int(qty) if qty.isdigit() else 1
    open_now = [r.name for r in store.rooms() if r.is_open]
    still_open = ", ".join(open_now) or "none"
    by_payment: dict[str, float] = {}
    for v in visits:
        by_payment[v.payment] = by_payment.get(v.payment, 0.0) + v.total
    rows = "".join(
        f"<tr><td>{n}</td><td align='right'>{q}</td></tr>" for n, q in sold.most_common()
    )
    return (
        "<div style='color:#111'>"
        "<h2>YTKTV · Shift report</h2>"
        f"<p>{time.strftime('%Y-%m-%d %H:%M', time.localtime(started))} – "
        f"{time.strftime('%H:%M', time.localtime(now))}</p>"
        "<table width='100%' cellpadding='4'>"
        f"<tr><td>Sessions closed</td><td align='right'>{len(visits)}</td></tr>"
        f"<tr><td>Room fees</td><td align='right'>{currency}{rooms_fee:.2f}</td></tr>"
        f"<tr><td>Items</td><td align='right'>"
        f"{currency}{sum(v.total for v in visits) - rooms_fee:.2f}</td></tr>"
        f"<tr><td><b>Takings</b></td><td align='right'><b>{currency}"
        f"{sum(v.total for v in visits):.2f}</b></td></tr>"
        + "".join(
            f"<tr><td>· {method}</td><td align='right'>{currency}{amount:.2f}</td></tr>"
            for method, amount in sorted(by_payment.items())
        )
        + f"<tr><td>Rooms still open</td><td align='right'>{still_open}</td></tr>"
        "</table>"
        + (f"<h3>Items sold</h3><table width='100%' cellpadding='4'>{rows}</table>" if rows else "")
        + "</div>"
    )


class ShiftDialog(QDialog):
    """The shift report, with printing and the hand-over that starts a new shift."""

    def __init__(self, store: DeskStore, parent: QWidget | None = None) -> None:
        from PySide6.QtWidgets import QTextBrowser

        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Shift report")
        self.resize(480, 600)
        column = QVBoxLayout(self)
        self.view = QTextBrowser()
        self.view.setStyleSheet("background: white; color: black; border-radius: 10px;")
        self.view.setHtml(shift_report(store))
        column.addWidget(self.view, stretch=1)
        buttons = QHBoxLayout()
        print_button = QPushButton("Print…")
        print_button.clicked.connect(self.print_report)
        hand_over = QPushButton("Hand Over")
        hand_over.setObjectName("accent")
        hand_over.setToolTip("End this shift: the next report starts from now")
        hand_over.clicked.connect(self.hand_over)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        buttons.addWidget(print_button)
        buttons.addStretch()
        buttons.addWidget(close)
        buttons.addWidget(hand_over)
        column.addLayout(buttons)

    def print_report(self) -> None:
        from PySide6.QtGui import QTextDocument
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter

        printer = QPrinter()
        if QPrintDialog(printer, self).exec():
            document = QTextDocument()
            document.setHtml(shift_report(self.store))
            document.print_(printer)

    def hand_over(self) -> None:
        self.store.set_setting("shift_started", repr(time.time()))
        self.accept()


class MembersPage(QWidget):
    """Members: their stored balance and points. Members save at the till."""

    COLUMNS = ("Name", "Phone", "Balance", "Points")

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 18, 24, 18)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a member by name or phone")
        self.search.textChanged.connect(self.refresh)
        top.addWidget(self.search, stretch=1)
        for text, handler in (("＋ New Member", self.new_member), ("💰 Top Up", self.top_up)):
            button = QPushButton(text)
            button.clicked.connect(handler)
            top.addWidget(button)
        column.addLayout(top)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        column.addWidget(self.table, stretch=1)
        self.note = QLabel()
        self.note.setObjectName("muted")
        column.addWidget(self.note)
        self._shown: list[Member] = []
        self.refresh()

    def refresh(self) -> None:
        currency = self.store.setting("currency", "$")
        self._shown = self.store.members(self.search.text())
        self.table.setRowCount(0)
        for m in self._shown:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, text in enumerate(
                (m.name, m.phone, f"{currency}{m.balance:,.2f}", str(m.points))
            ):
                self.table.setItem(row, col, QTableWidgetItem(text))
        off = self.store.setting("member_discount", "10")
        self.note.setText(f"{len(self._shown)} members · members save {off}% at the till")

    def selected(self) -> Member | None:
        row = self.table.currentRow()
        return self._shown[row] if 0 <= row < len(self._shown) else None

    def new_member(
        self, _checked: bool = False, name: str | None = None, phone: str | None = None
    ) -> int:
        if name is None:
            name, ok = QInputDialog.getText(self, "New member", "Name:")
            if not ok:
                return 0
        if phone is None:
            phone, ok = QInputDialog.getText(self, "New member", "Phone number:")
            if not ok:
                return 0
        try:
            member_id = self.store.add_member(name, phone)
        except ValueError as exc:
            QMessageBox.warning(self, "New member", str(exc).capitalize() + ".")
            return 0
        self.refresh()
        return member_id

    def top_up(self, _checked: bool = False, amount: float | None = None) -> None:
        member = self.selected()
        if member is None:
            return
        if amount is None:
            amount, ok = QInputDialog.getDouble(
                self, "Top up", f"Add to {member.name}'s balance:", 100, 0.01, 99_999_999, 2
            )
            if not ok:
                return
        self.store.top_up(member.member_id, amount)
        self.refresh()
