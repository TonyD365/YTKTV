"""Hand-painted hardware controls for the mixer: knobs, faders, LEDs, meters."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPolygonF,
    QRadialGradient,
    QWheelEvent,
)
from PySide6.QtWidgets import QWidget

SILK = QColor("#d8d8d8")  # the white "silkscreen" print on the panel


def _small_font(size: int = 8, bold: bool = True) -> QFont:
    font = QFont()
    font.setPixelSize(size)
    font.setBold(bold)
    return font


class Knob(QWidget):
    """A rotary pot: drag up/down or scroll to turn, double-click to reset."""

    valueChanged = Signal(float)
    _SWEEP = 270.0

    def __init__(
        self,
        label: str,
        minimum: float,
        maximum: float,
        default: float,
        cap_color: str,
        left_text: str = "",
        right_text: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.label = label
        self.minimum, self.maximum, self.default = minimum, maximum, default
        self.cap_color = QColor(cap_color)
        self.left_text, self.right_text = left_text, right_text
        self.ink = SILK  # print colour; dark on the light EQ zone
        self._value = default
        self._drag_origin: tuple[float, float] | None = None
        self.setCursor(Qt.CursorShape.SizeVerCursor)
        self.setToolTip(label)

    def sizeHint(self) -> QSize:
        return QSize(64, 52)

    def minimumSizeHint(self) -> QSize:
        return QSize(56, 50)

    def value(self) -> float:
        return self._value

    def set_value(self, value: float, notify: bool = False) -> None:
        value = max(self.minimum, min(self.maximum, value))
        if value == self._value:
            return
        self._value = value
        self.update()
        if notify:
            self.valueChanged.emit(value)

    def _fraction(self) -> float:
        span = self.maximum - self.minimum
        return (self._value - self.minimum) / span if span else 0.0

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self._drag_origin = (event.position().y(), self._value)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_origin is None:
            return
        start_y, start_value = self._drag_origin
        delta = (start_y - event.position().y()) / 140.0
        self.set_value(start_value + delta * (self.maximum - self.minimum), notify=True)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_origin = None

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:
        self.set_value(self.default, notify=True)

    def wheelEvent(self, event: QWheelEvent) -> None:
        step = (self.maximum - self.minimum) / 40.0
        self.set_value(self._value + (step if event.angleDelta().y() > 0 else -step), notify=True)
        event.accept()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        radius = min(w * 0.30, (h - 14) * 0.42)
        centre = QPointF(w / 2 - 4, h / 2 + 3)

        painter.setFont(_small_font(8))
        painter.setPen(self.ink)
        painter.drawText(
            QRectF(centre.x() + radius * 0.6, 0, w, 11),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.label,
        )

        # Scale ticks around the pot.
        painter.setPen(QPen(self.ink, 1))
        for i in range(11):
            angle = math.radians(225 - i * self._SWEEP / 10)
            inner, outer = radius + 3, radius + (7 if i % 5 == 0 else 5)
            painter.drawLine(
                QPointF(centre.x() + inner * math.cos(angle), centre.y() - inner * math.sin(angle)),
                QPointF(centre.x() + outer * math.cos(angle), centre.y() - outer * math.sin(angle)),
            )
        if self.left_text or self.right_text:
            painter.setFont(_small_font(7, bold=False))
            y = centre.y() + radius - 5
            painter.drawText(
                QRectF(centre.x() - radius - 22, y, 18, 9),
                Qt.AlignmentFlag.AlignCenter,
                self.left_text,
            )
            painter.drawText(
                QRectF(centre.x() + radius + 5, y, 18, 9),
                Qt.AlignmentFlag.AlignCenter,
                self.right_text,
            )

        # Knob body: black skirt with a soft highlight.
        body = QRadialGradient(centre.x() - radius * 0.3, centre.y() - radius * 0.4, radius * 1.6)
        body.setColorAt(0.0, QColor("#5a5a5e"))
        body.setColorAt(0.45, QColor("#1c1c1f"))
        body.setColorAt(1.0, QColor("#050506"))
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(QBrush(body))
        painter.drawEllipse(centre, radius, radius)

        # Coloured pointer cap.
        angle = math.radians(225 - self._fraction() * self._SWEEP)
        direction = QPointF(math.cos(angle), -math.sin(angle))
        normal = QPointF(-direction.y(), direction.x())
        tip = centre + direction * (radius * 0.98)
        base = centre - direction * (radius * 0.25)
        half = radius * 0.34
        pointer = QPolygonF([tip, base + normal * half, base - normal * half])
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.cap_color)
        painter.drawPolygon(pointer)
        painter.setBrush(self.cap_color.darker(135))
        painter.drawEllipse(centre, radius * 0.36, radius * 0.36)


class Fader(QWidget):
    """A long-throw channel fader with a printed dB scale."""

    valueChanged = Signal(float)
    _MARKS = (
        (1.0, "10"),
        (0.9, "5"),
        (0.8, "0"),
        (0.66, "5"),
        (0.52, "10"),
        (0.38, "20"),
        (0.24, "30"),
        (0.1, "40"),
        (0.0, "∞"),
    )

    def __init__(
        self, cap_color: str = "#e9e9e9", default: float = 0.8, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.cap_color = QColor(cap_color)
        self.default = default
        self._value = default
        self._grab_offset: float | None = None
        self.setMinimumSize(46, 96)
        self.setCursor(Qt.CursorShape.SizeVerCursor)

    def sizeHint(self) -> QSize:
        return QSize(56, 210)

    def value(self) -> float:
        return self._value

    def set_value(self, value: float, notify: bool = False) -> None:
        value = max(0.0, min(1.0, value))
        if value == self._value:
            return
        self._value = value
        self.update()
        if notify:
            self.valueChanged.emit(value)

    _CAP_H = 30.0

    def _track(self) -> tuple[float, float]:
        top = 8 + self._CAP_H / 2
        return top, self.height() - 8 - self._CAP_H / 2

    def _y_for(self, value: float) -> float:
        top, bottom = self._track()
        return bottom - value * (bottom - top)

    def _value_at(self, y: float) -> float:
        top, bottom = self._track()
        return (bottom - y) / (bottom - top)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        y = event.position().y()
        cap_y = self._y_for(self._value)
        if abs(y - cap_y) <= self._CAP_H / 2:
            self._grab_offset = y - cap_y
        else:
            self._grab_offset = 0.0
            self.set_value(self._value_at(y), notify=True)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._grab_offset is not None:
            self.set_value(self._value_at(event.position().y() - self._grab_offset), notify=True)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._grab_offset = None

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:
        self.set_value(self.default, notify=True)

    def wheelEvent(self, event: QWheelEvent) -> None:
        self.set_value(self._value + (0.02 if event.angleDelta().y() > 0 else -0.02), notify=True)
        event.accept()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        cx = w / 2 + 6
        top, bottom = self._track()

        painter.setFont(_small_font(7, bold=False))
        painter.setPen(QPen(SILK, 1))
        for value, text in self._MARKS:
            y = self._y_for(value)
            painter.drawLine(QPointF(cx - 13, y), QPointF(cx - 6, y))
            painter.drawText(
                QRectF(cx - 34, y - 5, 19, 10),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        # Slot.
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#000000"))
        painter.drawRoundedRect(QRectF(cx - 2.5, top - 6, 5, bottom - top + 12), 2.5, 2.5)

        # Cap.
        cap_w = 22.0
        y = self._y_for(self._value)
        rect = QRectF(cx - cap_w / 2, y - self._CAP_H / 2, cap_w, self._CAP_H)
        shade = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        shade.setColorAt(0.0, self.cap_color.lighter(118))
        shade.setColorAt(0.45, self.cap_color)
        shade.setColorAt(0.55, self.cap_color.darker(125))
        shade.setColorAt(1.0, self.cap_color.darker(160))
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(QBrush(shade))
        painter.drawRoundedRect(rect, 2.5, 2.5)
        painter.setPen(QPen(QColor(0, 0, 0, 170), 1.5))
        painter.drawLine(QPointF(rect.left() + 2, y), QPointF(rect.right() - 2, y))


class Led(QWidget):
    def __init__(self, color: str = "#ff2a2a", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = QColor(color)
        self._on = False
        self.setFixedSize(12, 12)

    def set_on(self, on: bool) -> None:
        if on != self._on:
            self._on = on
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(self.color if self._on else self.color.darker(420))
        painter.drawEllipse(QRectF(2, 2, 8, 8))


class LedMeter(QWidget):
    """Stereo LED ladder like the main meter on a hardware desk."""

    _LEVELS_DB = (6, 3, 0, -3, -6, -9, -12, -18, -24, -30)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._levels = [0.0, 0.0]
        self.setMinimumSize(70, 96)

    def sizeHint(self) -> QSize:
        return QSize(76, 180)

    def set_levels(self, left: float, right: float) -> None:
        # Fast attack, slow decay so short peaks stay visible.
        new = [max(left, self._levels[0] * 0.82), max(right, self._levels[1] * 0.82)]
        if new != self._levels:
            self._levels = new
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rows = len(self._LEVELS_DB)
        row_h = (self.height() - 8) / rows
        cx = self.width() / 2
        painter.setFont(_small_font(7, bold=False))
        for row, db in enumerate(self._LEVELS_DB):
            y = 4 + row * row_h
            threshold = 10.0 ** ((db - 6) / 20.0)  # +6 on the ladder is digital full scale
            if db > 0:
                color = QColor("#ff3030")
            elif db > -9:
                color = QColor("#ffd23a")
            else:
                color = QColor("#35e05a")
            for channel, x in enumerate((cx - 24, cx + 14)):
                lit = self._levels[channel] >= threshold
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color if lit else color.darker(480))
                painter.drawRoundedRect(QRectF(x, y + 1, 10, row_h - 3), 1.5, 1.5)
            painter.setPen(SILK)
            painter.drawText(
                QRectF(cx - 12, y, 24, row_h),
                Qt.AlignmentFlag.AlignCenter,
                f"{db:+d}" if db else "0",
            )


class XlrJack(QWidget):
    """Decorative XLR socket for the top of each channel strip."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 36)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        centre = QPointF(20, 18)
        ring = QRadialGradient(centre, 17)
        ring.setColorAt(0.0, QColor("#0a0a0a"))
        ring.setColorAt(0.72, QColor("#101012"))
        ring.setColorAt(0.8, QColor("#8d8f94"))
        ring.setColorAt(1.0, QColor("#3a3b3f"))
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.setBrush(QBrush(ring))
        painter.drawEllipse(centre, 16, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#b9bbc0"))
        for dx, dy in ((-5, -3), (5, -3), (0, 6)):
            painter.drawEllipse(QPointF(20 + dx, 18 + dy), 2.0, 2.0)
