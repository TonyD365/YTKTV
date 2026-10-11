"""Things drawn on top of the video: karaoke lyrics, danmaku, and edge lights."""

from __future__ import annotations

import colorsys
import random
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QPointF, QRect, QRectF, QSizeF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from ytktv.ui import theme
from ytktv.youtube.lyrics import LyricLine, line_at, sung_fraction

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


class _TextSprite:
    """Outlined text drawn once into a pixmap, so later frames only copy it.

    Drawing text this large takes milliseconds per call and the outline needs nine
    calls, which is far too slow to repeat on every animation frame. Even once is
    long enough to make the microphones click, so the drawing is cut into short
    steps (see steps) that can be spread over several frames.
    """

    def __init__(
        self,
        font: QFont,
        text: str,
        fill: QColor | tuple[QColor, QColor],  # one colour, or a left-to-right blend
        ratio: float,
        outline: bool = True,
    ) -> None:
        metrics = QFontMetricsF(font)
        self.width = metrics.horizontalAdvance(text)
        self._font, self._text, self._fill, self._ratio = font, text, fill, ratio
        self._edge = max(1.5, font.pixelSize() / 14.0) if outline else 0.0
        self._pad = max(1.5, font.pixelSize() / 14.0) + 2.0
        self._ascent = metrics.ascent()
        self._size = QSizeF(self.width + 2 * self._pad, metrics.height() + 2 * self._pad)
        self.pixmap = QPixmap()

    def _blank(self) -> QPixmap:
        pixmap = QPixmap((self._size * self._ratio).toSize())
        pixmap.setDevicePixelRatio(self._ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        return pixmap

    def _write(self, pixmap: QPixmap, pen: QPen | QColor) -> None:
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setFont(self._font)
        painter.setPen(pen)
        painter.drawText(QPointF(self._pad, self._pad + self._ascent), self._text)
        painter.end()

    def steps(self) -> Iterator[None]:
        """Draw the sprite, yielding between pieces of work of a few milliseconds each.

        No painter stays open across a yield: an unfinished run may simply be dropped,
        and a pixmap must not be destroyed while it is being painted on.
        """
        pixmap = self._blank()
        yield
        if self._edge:
            # One dark copy of the text, stamped around the origin, makes the outline.
            dark = self._blank()
            self._write(dark, QColor(6, 3, 16))
            yield
            for dx, dy in _OUTLINE:
                painter = QPainter(pixmap)
                painter.drawPixmap(QPointF(dx * self._edge, dy * self._edge), dark)
                painter.end()
                yield
        if isinstance(self._fill, tuple):
            blend = QLinearGradient(self._pad, 0, self._pad + self.width, 0)
            blend.setColorAt(0.0, self._fill[0])
            blend.setColorAt(1.0, self._fill[1])
            self._write(pixmap, QPen(QBrush(blend), 1))
        else:
            self._write(pixmap, self._fill)
        self.pixmap = pixmap

    def finish(self) -> _TextSprite:
        """Draw everything now."""
        for _ in self.steps():
            pass
        return self

    def draw(self, painter: QPainter, x: float, baseline: float) -> None:
        """Paint with the text starting at *x* on *baseline*."""
        painter.drawPixmap(QPointF(x - self._pad, baseline - self._pad - self._ascent), self.pixmap)


@dataclass(slots=True)
class _LineArt:
    """One lyric line, drawn and ready to be copied to the screen."""

    line: _TextSprite  # in white
    sung: _TextSprite  # the same text in the "sung" colours
    upcoming: _TextSprite | None  # the line after it, shown smaller underneath
    x: float  # where the line starts, so that it is centred


_DONE = object()


class LyricsOverlay(_Overlay):
    """Two lines at the bottom of the screen; the current one fills with colour as it is sung."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lines: list[LyricLine] = []
        self._position = 0.0
        self._shown: tuple[int, int] | None = None  # (line index, progress in 1/200ths)
        # Each line is drawn once (see _TextSprite) and frames in between only copy it.
        # The drawing is done a step per frame while the line before it is still being
        # sung, so nothing slow is left to do at the moment the lines change.
        self._art: dict[int, _LineArt] = {}
        # Per line, where each timed word begins as a share of the line's width.
        self._stops: dict[int, list[tuple[float, float]]] = {}
        self._job: tuple[int, Iterator[None]] | None = None
        self._geometry: tuple[int, int, float] | None = None

    def set_lines(self, lines: list[dict[str, Any]]) -> None:
        self._lines = [LyricLine.from_dict(d) for d in lines]
        self._stops.clear()
        self._shown = None
        self._art.clear()
        self._job = None
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
        return index, sung_fraction(line, self._position, self._word_stops(index))

    def _word_stops(self, index: int) -> list[tuple[float, float]]:
        """Turn the word positions of line *index* from characters into shares of its width."""
        if index not in self._stops:
            line = self._lines[index]
            stops: list[tuple[float, float]] = []
            if line.words:
                font = QFont()
                font.setWeight(QFont.Weight.Black)
                font.setPixelSize(40)  # only proportions matter here
                metrics = QFontMetricsF(font)
                width = metrics.horizontalAdvance(line.text) or 1.0
                stops = [
                    (time, metrics.horizontalAdvance(line.text[:offset]) / width)
                    for time, offset in line.words
                ]
            self._stops[index] = stops
        return self._stops[index]

    def set_time(self, position: float) -> None:
        self._position = position
        self._draw_ahead()
        current = self._current()
        shown = (current[0], int(current[1] * 200)) if current else None
        if shown == self._shown:  # repaint only when something visibly changed
            return
        previous, self._shown = self._shown, shown
        art = self._art.get(shown[0]) if shown else None
        if previous and shown and previous[0] == shown[0] and art is not None:
            # Same line, more of it sung: only the strip between the two positions changed.
            edges = [art.x + art.line.width * step / 200 for step in (previous[1], shown[1])]
            left, right = int(min(edges)) - 2, int(max(edges)) + 3
            self.update(QRect(left, 0, right - left, self.height()))
        else:
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

    def _check_geometry(self) -> None:
        geometry = (self.width(), self.height(), self.devicePixelRatioF())
        if geometry != self._geometry:  # another screen or size: everything is drawn again
            self._geometry = geometry
            self._art.clear()
            self._job = None

    def _build(self, index: int) -> Iterator[None]:
        """Draw line *index*, and the smaller preview of the line after it, in steps."""
        ratio = self.devicePixelRatioF()
        w, h = float(self.width()), float(self.height())
        line = self._lines[index]
        font, width = self._fitted_font(line.text, h * 0.36, w * 0.92)
        white = _TextSprite(font, line.text, QColor("white"), ratio)
        sung = _TextSprite(
            font, line.text, (QColor(theme.PINK), QColor(theme.CYAN)), ratio, outline=False
        )
        upcoming = None
        if index + 1 < len(self._lines):
            following = self._lines[index + 1]
            if following.start - line.end < 8.0:  # not across an instrumental break
                next_font, _width = self._fitted_font(following.text, h * 0.24, w * 0.88)
                upcoming = _TextSprite(next_font, following.text, QColor("white"), ratio)
        for sprite in (white, sung, upcoming):
            if sprite is not None:
                yield from sprite.steps()
                yield
        self._art[index] = _LineArt(white, sung, upcoming, (w - width) / 2)

    def _draw_ahead(self) -> None:
        """Do one step of drawing for the line on screen or the one that follows it."""
        self._check_geometry()
        first = line_at(self._lines, self._position)
        wanted = [i for i in (first, first + 1) if first >= 0 and i < len(self._lines)]
        for index in [i for i in self._art if i not in wanted]:
            del self._art[index]
        if self._job is not None and self._job[0] not in wanted:
            self._job = None
        if self._job is None:
            todo = next((i for i in wanted if i not in self._art), None)
            if todo is None:
                return
            self._job = (todo, self._build(todo))
        if next(self._job[1], _DONE) is _DONE:
            self._job = None

    def _ready(self, index: int) -> _LineArt:
        """The drawn line, finishing it now if playback got here before it was done."""
        self._check_geometry()
        if index not in self._art:
            job = self._job[1] if self._job and self._job[0] == index else self._build(index)
            for _ in job:
                pass
            if self._job and self._job[0] == index:
                self._job = None
        return self._art[index]

    def paintEvent(self, _event: QPaintEvent) -> None:
        current = self._current()
        if current is None:
            return
        index, progress = current
        art = self._ready(index)
        painter = QPainter(self)
        w, h = float(self.width()), float(self.height())
        baseline = h * 0.46
        art.line.draw(painter, art.x, baseline)
        if art.upcoming is not None:
            painter.setOpacity(0.6)
            art.upcoming.draw(painter, (w - art.upcoming.width) / 2, h * 0.84)
            painter.setOpacity(1.0)
        if progress > 0:
            painter.setClipRect(QRectF(art.x, 0, art.line.width * progress, h))
            art.sung.draw(painter, art.x, baseline)


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
                "sprite": None,  # drawn on first paint, redrawn if the screen size changes
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
        font = self._font()
        key = (font.pixelSize(), self.devicePixelRatioF())
        lane_height = self.height() / DANMAKU_LANES
        for item in self._items:
            if item["sprite"] is None or item["sprite"][0] != key:
                sprite = _TextSprite(font, item["text"], item["color"], key[1]).finish()
                item["sprite"] = (key, sprite)
            item["sprite"][1].draw(painter, item["x"], lane_height * (item["lane"] + 0.74))


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


class ScoreCard(_Overlay):
    """The big end-of-song score, in the middle of the screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points = 0
        self._grade = ""
        self._caption = ""

    def set_score(self, points: int, grade: str, caption: str) -> None:
        self._points, self._grade, self._caption = points, grade, caption
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        panel = QRectF(0, 0, w, h)
        painter.setPen(QPen(QColor(theme.PINK), max(2.0, h * 0.012)))
        painter.setBrush(QColor(8, 4, 20, 225))
        painter.drawRoundedRect(panel.adjusted(2, 2, -2, -2), h * 0.08, h * 0.08)

        def centred(
            text: str, pixel_size: float, y: float, fill: QBrush | QColor, weight: Any
        ) -> None:
            font = QFont()
            font.setWeight(weight)
            font.setPixelSize(max(8, int(pixel_size)))
            width = QFontMetricsF(font).horizontalAdvance(text)
            if width > w * 0.9:
                font.setPixelSize(max(8, int(pixel_size * w * 0.9 / width)))
                width = QFontMetricsF(font).horizontalAdvance(text)
            _outlined_text(painter, font, text, QPointF((w - width) / 2, y), fill)

        centred("SCORE", h * 0.09, h * 0.17, QColor(theme.CYAN), QFont.Weight.Bold)
        glow = QLinearGradient(w * 0.3, 0, w * 0.7, 0)
        glow.setColorAt(0.0, QColor(theme.PINK))
        glow.setColorAt(1.0, QColor(theme.CYAN))
        centred(str(self._points), h * 0.46, h * 0.62, QBrush(glow), QFont.Weight.Black)
        centred(self._grade, h * 0.12, h * 0.79, QColor(theme.GOLD), QFont.Weight.Black)
        if self._caption:
            centred(self._caption, h * 0.06, h * 0.92, QColor("white"), QFont.Weight.DemiBold)
