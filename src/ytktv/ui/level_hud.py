"""The volume display that pops up when a level changes, like a TV's or a Mac's."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent
from PySide6.QtWidgets import QWidget

from ytktv.ui.support import fade_in, fade_out

SEGMENTS = 16
# What each level is called and its symbol.
KINDS = {
    "music_volume": ("Music", "🔊"),
    "mic_volume": ("Microphones", "🎤"),
    "guide_vocal": ("Guide vocal", "🎵"),
}


def to_segments(value: int) -> int:
    return max(0, min(SEGMENTS, round(value * SEGMENTS / 100)))


def from_segments(segments: int) -> int:
    return round(max(0, min(SEGMENTS, segments)) * 100 / SEGMENTS)


class LevelHud(QWidget):
    """A rounded panel with a symbol, a name and a row of segments; fades out by itself."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._kind = "music_volume"
        self._value = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: fade_out(self, 300))
        self.hide()

    @property
    def kind(self) -> str:
        return self._kind

    @property
    def value(self) -> int:
        return self._value

    def show_level(self, kind: str, value: int) -> None:
        self._kind, self._value = kind, value
        self.update()
        if not self.isVisible():
            fade_in(self, 150)
        self.raise_()
        self._timer.start(1600)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(20, 12, 44, 225))
        painter.drawRoundedRect(QRectF(0, 0, w, h), h * 0.3, h * 0.3)
        name, symbol = KINDS.get(self._kind, ("", ""))
        font = QFont()
        font.setPixelSize(int(h * 0.42))
        painter.setFont(font)
        painter.setPen(QColor("white"))
        icon = QRectF(h * 0.25, 0, h * 0.8, h)
        painter.drawText(icon, Qt.AlignmentFlag.AlignCenter, symbol)
        label = QFont()
        label.setPixelSize(max(10, int(h * 0.17)))
        label.setBold(True)
        painter.setFont(label)
        painter.setPen(QColor(169, 155, 214))
        left = icon.right() + h * 0.15
        painter.drawText(
            QRectF(left, h * 0.14, w - left, h * 0.3),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{name.upper()}   {self._value}",
        )
        # The segments.
        right = w - h * 0.35
        gap = h * 0.035
        width = (right - left - gap * (SEGMENTS - 1)) / SEGMENTS
        top, height = h * 0.55, h * 0.1
        lit = to_segments(self._value)
        for i in range(SEGMENTS):
            painter.setBrush(QColor("white") if i < lit else QColor(255, 255, 255, 60))
            x = left + i * (width + gap)
            painter.drawRoundedRect(QRectF(x, top, width, height), height / 3, height / 3)
