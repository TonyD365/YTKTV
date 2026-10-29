"""The desk's Bookings and Records tabs."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QDateTime, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent
from PySide6.QtWidgets import (
    QCalendarWidget,
    QComboBox,
    QDateEdit,
    QDateTimeEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ytktv.desk.store import Booking, DeskStore

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


class RecordsPage(QWidget):
    COLUMNS = ("Closed", "Room", "Guest", "Time", "Songs", "Total")

    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 18, 24, 18)
        top = QHBoxLayout()
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.day.dateChanged.connect(self.refresh)
        self.summary = QLabel()
        self.summary.setStyleSheet("color: white; font-size: 18px; font-weight: 700;")
        top.addWidget(QLabel("Day"))
        top.addWidget(self.day)
        top.addSpacing(24)
        top.addWidget(self.summary, stretch=1)
        column.addLayout(top)
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

    def refresh(self) -> None:
        visits = self.store.history(*day_bounds(self.day.date()))
        currency = self.store.setting("currency", "$")
        hours = sum(v.closed_at - v.opened_at for v in visits) / 3600
        revenue = sum(v.total for v in visits)
        self.summary.setText(
            f"{len(visits)} sessions  ·  {hours:.1f} hours  ·  {currency}{revenue:.2f}"
        )
        self.table.setRowCount(0)
        for v in visits:
            row = self.table.rowCount()
            self.table.insertRow(row)
            minutes = int((v.closed_at - v.opened_at) // 60)
            cells = (
                time.strftime("%H:%M", time.localtime(v.closed_at)),
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
        f"<tr><td>Rooms still open</td><td align='right'>{', '.join(open_now) or 'none'}</td></tr>"
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
