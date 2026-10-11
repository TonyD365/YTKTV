"""Things drawn on top of the video: karaoke lyrics, danmaku, and edge lights."""

from __future__ import annotations

import colorsys
import random
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
)
from PySide6.QtWidgets import QWidget

from ytktv.ui import theme
from ytktv.youtube.lyrics import LyricLine, line_at

# Show the next line this long before it starts, so singers can read ahead.
LEAD_SECONDS = 3.0
DANMAKU_SECONDS = 9.0
DANMAKU_LANES = 6
DANMAKU_LIMIT = 40
DANMAKU_COLORS = ("#ffffff", "#ff8ad0", "#7df3ff", "#ffe27a", "#9dffb0", "#c9a6ff")


class _Overlay(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet("background: transparent;")
        self.hide()


# Offsets for a hand-made outline. Text is drawn with drawText rather than as a path
# so colour emoji (which have no outline to trace) still appear.
_OUTLINE = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]


def _outlined_text(
    painter: QPainter,
    font: QFont,
    text: str,
    origin: QPointF,
    fill: QBrush | QColor,
    alpha: float = 1.0,
) -> None:
    """Draw *text* with a dark outline so it reads over any video."""
    painter.setFont(font)
    painter.setOpacity(alpha)
    width = max(1.5, font.pixelSize() / 14.0)
    painter.setPen(QColor(6, 3, 16))
    for dx, dy in _OUTLINE:
        painter.drawText(QPointF(origin.x() + dx * width, origin.y() + dy * width), text)
    painter.setPen(QPen(fill, 1))
    painter.drawText(origin, text)
    painter.setOpacity(1.0)


class LyricsOverlay(_Overlay):
    """Two lines at the bottom of the screen; the current one fills with colour as it is sung."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lines: list[LyricLine] = []
        self._position = 0.0
        self._shown: tuple[int, int] | None = None  # (line index, progress in 1/200ths)

    def set_lines(self, lines: list[dict[str, Any]]) -> None:
        self._lines = [LyricLine(float(d["start"]), float(d["end"]), str(d["text"])) for d in lines]
        self._shown = None
        self.setVisible(bool(self._lines))
        self.update()

    def has_lines(self) -> bool:
        return bool(self._lines)

    def _current(self) -> tuple[int, float] | None:
        """(index, progress 0..1) of the line to show now, or None during a long break."""
        index = line_at(self._lines, self._position)
        if index < 0:
            return None
        line = self._lines[index]
        if self._position < line.start - LEAD_SECONDS:
            return None
        span = max(0.05, line.end - line.start)
        return index, max(0.0, min(1.0, (self._position - line.start) / span))

    def set_time(self, position: float) -> None:
        self._position = position
        current = self._current()
        shown = (current[0], int(current[1] * 200)) if current else None
        if shown != self._shown:  # repaint only when something visibly changed
            self._shown = shown
            self.update()

    def _fitted_font(self, text: str, pixel_size: float, max_width: float) -> tuple[QFont, float]:
        font = QFont()
        font.setWeight(QFont.Weight.Black)
        font.setPixelSize(max(8, int(pixel_size)))
        width = QFontMetricsF(font).horizontalAdvance(text)
        if width > max_width:
            font.setPixelSize(max(8, int(pixel_size * max_width / width)))
            width = QFontMetricsF(font).horizontalAdvance(text)
        return font, width

    def paintEvent(self, _event: QPaintEvent) -> None:
        current = self._current()
        if current is None:
            return
        index, progress = current
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        line = self._lines[index]

        font, width = self._fitted_font(line.text, h * 0.36, w * 0.92)
        x, baseline = (w - width) / 2, h * 0.46
        _outlined_text(painter, font, line.text, QPointF(x, baseline), QColor("white"))
        if progress > 0:
            sung = QLinearGradient(x, 0, x + width, 0)
            sung.setColorAt(0.0, QColor(theme.PINK))
            sung.setColorAt(1.0, QColor(theme.CYAN))
            painter.save()
            painter.setClipRect(QRectF(x, 0, width * progress, h))
            painter.setFont(font)
            painter.setPen(QPen(QBrush(sung), 1))
            painter.drawText(QPointF(x, baseline), line.text)
            painter.restore()

        if index + 1 < len(self._lines):
            upcoming = self._lines[index + 1]
            if upcoming.start - line.end < 8.0:  # not across an instrumental break
                next_font, next_width = self._fitted_font(upcoming.text, h * 0.24, w * 0.88)
                origin = QPointF((w - next_width) / 2, h * 0.84)
                _outlined_text(painter, next_font, upcoming.text, origin, QColor("white"), 0.6)


class DanmakuOverlay(_Overlay):
    """Messages from the room flying right to left across the top of the screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._lane_free_at = [0.0] * DANMAKU_LANES
        self._clock = 0.0

    def active(self) -> bool:
        return bool(self._items)

    def _font(self) -> QFont:
        font = QFont()
        font.setWeight(QFont.Weight.Bold)
        font.setPixelSize(max(12, int(self.height() / DANMAKU_LANES * 0.56)))
        return font

    def add(self, text: str) -> None:
        if len(self._items) >= DANMAKU_LIMIT:
            return
        width = QFontMetricsF(self._font()).horizontalAdvance(text)
        speed = (self.width() + width) / DANMAKU_SECONDS
        # Take the lane whose last message has moved clear of the right edge the longest.
        lane = min(range(DANMAKU_LANES), key=lambda i: self._lane_free_at[i])
        self._lane_free_at[lane] = self._clock + (width + self.width() * 0.08) / max(1.0, speed)
        self._items.append(
            {
                "text": text,
                "x": float(self.width()),
                "lane": lane,
                "speed": speed,
                "width": width,
                "color": QColor(random.choice(DANMAKU_COLORS)),
            }
        )
        self.show()
        self.raise_()
        self.update()

    def advance(self, seconds: float) -> None:
        if not self._items:
            return
        self._clock += seconds
        for item in self._items:
            item["x"] -= item["speed"] * seconds
        self._items = [item for item in self._items if item["x"] + item["width"] > 0]
        if not self._items:
            self.hide()
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = self._font()
        lane_height = self.height() / DANMAKU_LANES
        for item in self._items:
            baseline = lane_height * (item["lane"] + 0.74)
            _outlined_text(painter, font, item["text"], QPointF(item["x"], baseline), item["color"])


class EdgeLight(_Overlay):
    """A strip of coloured light along one edge of the screen that pulses with the music."""

    def __init__(self, side: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.side = side  # "left", "right", "top" or "bottom"
        self._alpha = 0
        self._hue = 0.0

    def set_light(self, intensity: float, hue: float) -> None:
        alpha = int(max(0.0, min(1.0, intensity)) * 215)
        if alpha == self._alpha and (alpha == 0 or abs(hue - self._hue) < 0.004):
            return
        self._alpha, self._hue = alpha, hue
        self.setVisible(alpha > 0)
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        w, h = float(self.width()), float(self.height())
        start, end = {
            "left": (QPointF(0, 0), QPointF(w, 0)),
            "right": (QPointF(w, 0), QPointF(0, 0)),
            "top": (QPointF(0, 0), QPointF(0, h)),
            "bottom": (QPointF(0, h), QPointF(0, 0)),
        }[self.side]
        red, green, blue = colorsys.hsv_to_rgb(self._hue % 1.0, 0.85, 1.0)
        color = QColor.fromRgbF(red, green, blue)
        glow = QLinearGradient(start, end)
        for stop, share in ((0.0, 1.0), (0.35, 0.38), (1.0, 0.0)):
            shade = QColor(color)
            shade.setAlpha(int(self._alpha * share))
            glow.setColorAt(stop, shade)
        painter.fillRect(self.rect(), QBrush(glow))


class LightShow:
    """Turns the music's level into hue and brightness for the four edge strips."""

    # Each side sits at a different point on the colour wheel.
    _OFFSETS = {"left": 0.0, "right": 0.5, "top": 0.25, "bottom": 0.75}

    def __init__(self) -> None:
        self._level = 0.0
        self._average = 0.0
        self._hue = random.random()
        self._flash = 0.0

    def step(self, peak: float, seconds: float) -> dict[str, tuple[float, float]]:
        """Advance by *seconds* at output level *peak* (0..1); gives side -> (intensity, hue)."""
        peak = max(0.0, min(1.0, peak))
        # Fast attack, slow release: lights jump with a hit and glow out after it.
        self._level = (
            peak
            if peak > self._level
            else self._level + (peak - self._level) * min(1.0, seconds * 5)
        )
        self._average += (peak - self._average) * min(1.0, seconds * 0.8)
        if peak > self._average * 1.5 + 0.03:  # a beat: nudge the colour and flash
            self._flash = 1.0
            self._hue += 0.012
        self._flash = max(0.0, self._flash - seconds * 4.0)
        self._hue = (self._hue + seconds * 0.05) % 1.0
        # A perceptual curve: quiet passages still glow, loud ones do not just clip.
        intensity = (
            min(1.0, (self._level**0.5) * 0.85 + self._flash * 0.25) if self._level > 0.004 else 0.0
        )
        return {side: (intensity, self._hue + offset) for side, offset in self._OFFSETS.items()}
