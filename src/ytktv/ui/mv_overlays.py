"""Things drawn on top of the video: karaoke lyrics, danmaku, and edge lights."""

from __future__ import annotations

import colorsys
import math
import random
from bisect import bisect_right
from collections import deque
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
from ytktv.youtube.lyrics import (
    PART_A,
    PART_B,
    PART_BOTH,
    LyricLine,
    duet_parts,
    line_at,
    sung_fraction,
)

# Show the next line this long before it starts, so singers can read ahead.
LEAD_SECONDS = 3.0
DANMAKU_SECONDS = 9.0
DANMAKU_LANES = 6
DANMAKU_LIMIT = 40
# The leaderboard under a score, as shares of the height of the card without it.
BOARD_HEAD, BOARD_ROW = 0.17, 0.09
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


# Per duet part: the line before it is sung, then the blend it fills with.
DUET_COLOURS = {
    PART_A: ("#bfe3ff", "#3da5ff", "#33e0ff"),
    PART_B: ("#ffc9e6", "#ff4fa8", "#ff8ad0"),
    PART_BOTH: ("#ffe9b0", "#ffb020", "#ffe066"),
}


class LyricsOverlay(_Overlay):
    """Two lines at the bottom of the screen; the current one fills with colour as it is sung."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._source: list[LyricLine] = []
        self._lines: list[LyricLine] = []
        self._parts: list[int] = []  # who sings each line, while it is a duet
        self._duet = False
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
        self._source = [LyricLine.from_dict(d) for d in lines]
        self._reset()

    def set_duet(self, enabled: bool) -> None:
        """Duet: colour each line by who sings it (see DUET_COLOURS)."""
        if enabled != self._duet:
            self._duet = enabled
            self._reset()

    def _reset(self) -> None:
        if self._duet:
            self._lines, self._parts = duet_parts(self._source)
        else:
            self._lines, self._parts = list(self._source), []
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
        waiting, fill = self._colours(index)
        white = _TextSprite(font, line.text, waiting, ratio)
        sung = _TextSprite(font, line.text, fill, ratio, outline=False)
        upcoming = None
        if index + 1 < len(self._lines):
            following = self._lines[index + 1]
            if following.start - line.end < 8.0:  # not across an instrumental break
                next_font, _width = self._fitted_font(following.text, h * 0.24, w * 0.88)
                next_colour = self._colours(index + 1)[0]
                upcoming = _TextSprite(next_font, following.text, next_colour, ratio)
        for sprite in (white, sung, upcoming):
            if sprite is not None:
                yield from sprite.steps()
                yield
        self._art[index] = _LineArt(white, sung, upcoming, (w - width) / 2)

    def _colours(self, index: int) -> tuple[QColor, tuple[QColor, QColor]]:
        """The colour of line *index* before it is sung, and the blend it fills with."""
        if not self._parts:
            return QColor("white"), (QColor(theme.PINK), QColor(theme.CYAN))
        waiting, left, right = DUET_COLOURS[self._parts[index]]
        return QColor(waiting), (QColor(left), QColor(right))

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


class ReactionOverlay(_Overlay):
    """Emoji that float up from the bottom of the screen and fade, a handful at a time."""

    RISE_SECONDS = 2.6
    PER_REACTION = 5
    LIMIT = 60

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, Any]] = []
        self._sprites: dict[tuple[str, int, float], _TextSprite] = {}

    def active(self) -> bool:
        return bool(self._items)

    def _sprite(self, emoji: str) -> _TextSprite:
        size = max(24, int(self.height() * 0.07))
        key = (emoji, size, self.devicePixelRatioF())
        if key not in self._sprites:
            font = QFont()
            font.setPixelSize(size)
            self._sprites[key] = _TextSprite(
                font, emoji, QColor("white"), key[2], outline=False
            ).finish()
        return self._sprites[key]

    def add(self, emoji: str) -> None:
        w, h = float(self.width()), float(self.height())
        for _ in range(self.PER_REACTION):
            if len(self._items) >= self.LIMIT:
                break
            self._items.append(
                {
                    "emoji": emoji,
                    "x": w * random.uniform(0.15, 0.85),
                    "y": h * random.uniform(0.95, 1.05),
                    "drift": w * random.uniform(-0.04, 0.04),
                    "age": -random.uniform(0.0, 0.5),  # not all at once
                }
            )
        self.show()
        self.raise_()

    def advance(self, seconds: float) -> None:
        if not self._items:
            return
        for item in self._items:
            item["age"] += seconds
        self._items = [item for item in self._items if item["age"] < self.RISE_SECONDS]
        if not self._items:
            self.hide()
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        h = float(self.height())
        for item in self._items:
            age = item["age"]
            if age < 0:
                continue
            share = age / self.RISE_SECONDS
            sprite = self._sprite(item["emoji"])
            painter.setOpacity(max(0.0, 1.0 - share) ** 0.7)
            x = item["x"] + item["drift"] * math.sin(share * math.pi * 2)
            sprite.draw(painter, x - sprite.width / 2, item["y"] - h * 0.75 * share)
        painter.setOpacity(1.0)


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


class PitchLane(_Overlay):
    """The tune as bars scrolling past a line, with the singer's voice drawn over them.

    Time runs left to right and the line marks now; higher notes are higher up. The
    voice is shown in the octave of the tune, because singing it an octave lower or
    higher counts just the same.
    """

    BEHIND, AHEAD = 2.0, 4.0  # seconds of the tune shown before and after now
    SPAN = 16.0  # semitones from the bottom of the lane to the top

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hop = 0.05
        self._bars: list[tuple[float, float, float]] = []  # (start, end, note) in seconds
        self._starts: list[float] = []
        self._transpose = 0.0
        self._position = 0.0
        self._voice: deque[tuple[float, float, bool]] = deque(maxlen=60)  # (time, note, on it)

    def set_melody(self, melody: dict[str, Any] | None) -> None:
        """Take the tune to show (see KTVController.melody), or None to hide the lane."""
        self._voice.clear()
        self._bars = []
        if melody is not None:
            self._hop = float(melody["hop"])
            self._transpose = float(melody["transpose"])
            start: int | None = None
            notes = list(melody["notes"]) + [None]
            for i, note in enumerate(notes):
                # A bar runs for as long as the tune stays on the same semitone.
                same = start is not None and note is not None and round(note) == round(notes[start])
                if start is not None and not same:
                    bar = (start * self._hop, i * self._hop, float(round(notes[start])))
                    self._bars.append(bar)
                    start = None
                if start is None and note is not None:
                    start = i
        self._starts = [bar[0] for bar in self._bars]
        self.setVisible(bool(self._bars))
        self.update()

    def has_melody(self) -> bool:
        return bool(self._bars)

    def _visible_bars(self, low: float, high: float) -> list[tuple[float, float, float]]:
        first = max(0, bisect_right(self._starts, low) - 1)
        last = bisect_right(self._starts, high)
        return [bar for bar in self._bars[first:last] if bar[1] > low]

    def _target(self, when: float) -> float | None:
        """The note of the tune at or nearest to *when* (within a third of a second)."""
        near = self._visible_bars(when - 0.35, when + 0.35)
        if not near:
            return None
        bar = min(
            near,
            key=lambda b: 0.0 if b[0] <= when < b[1] else min(abs(b[0] - when), abs(b[1] - when)),
        )
        return bar[2] + self._transpose

    def add_voice(self, position: float, note: float | None) -> None:
        """Record what was sung at *position*; None when nothing was heard."""
        if note is None or not self._bars:
            return
        target = self._target(position)
        centre = target if target is not None else self._centre(position)
        offset = (note - centre + 6.0) % 12.0 - 6.0  # nearest octave to the tune
        on_it = target is not None and abs(offset) <= 1.0
        self._voice.append((position, centre + offset, on_it))

    def _centre(self, when: float) -> float:
        """The middle of the lane: follows the tune slowly so that it stays in view."""
        around = self._visible_bars(when - 6.0, when + 6.0)
        if not around:
            return 60.0 + self._transpose
        notes = sorted(bar[2] for bar in around)
        return notes[len(notes) // 2] + self._transpose

    def set_time(self, position: float) -> None:
        if abs(position - self._position) > 1e-3:
            self._position = position
            self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        if not self._bars:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        now = self._position
        scale = w / (self.BEHIND + self.AHEAD)
        now_x = self.BEHIND * scale
        centre = self._centre(now)
        row = h / self.SPAN

        def y_of(note: float) -> float:
            return max(row, min(h - row, h / 2 - (note - centre) * row))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 4, 20, 120))
        painter.drawRoundedRect(QRectF(0, 0, w, h), row, row)
        for start, end, note in self._visible_bars(now - self.BEHIND, now + self.AHEAD):
            x0 = max(0.0, now_x + (start - now) * scale)
            x1 = min(w, now_x + (end - now) * scale)
            if x1 - x0 < 1.0:
                continue
            passed = end <= now
            painter.setBrush(QColor(255, 255, 255, 70 if passed else 150))
            y = y_of(note + self._transpose)
            painter.drawRoundedRect(
                QRectF(x0, y - row * 0.45, x1 - x0, row * 0.9), row * 0.4, row * 0.4
            )
        radius = row * 0.55
        for when, note, on_it in self._voice:
            if when < now - self.BEHIND:
                continue
            painter.setBrush(QColor(theme.GOLD) if on_it else QColor(theme.PINK))
            painter.drawEllipse(QPointF(now_x + (when - now) * scale, y_of(note)), radius, radius)
        painter.setPen(QPen(QColor(theme.CYAN), max(2.0, row * 0.25)))
        painter.drawLine(QPointF(now_x, 2), QPointF(now_x, h - 2))


class ScoreCard(_Overlay):
    """The big end-of-song score, in the middle of the screen."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points = 0
        self._grade = ""
        self._caption = ""
        self._rank = 0
        self._board: list[dict[str, Any]] = []

    def set_score(
        self,
        points: int,
        grade: str,
        caption: str,
        rank: int = 0,
        board: list[dict[str, Any]] | None = None,
    ) -> None:
        """Show a score; *board* is tonight's top scores and *rank* this one's place."""
        self._points, self._grade, self._caption = points, grade, caption
        self._rank = rank
        self._board = list(board or []) if len(board or []) > 1 else []
        self.update()

    def board_rows(self) -> int:
        """How many leaderboard lines the card will show (it is taller with them)."""
        return len(self._board)

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, full = float(self.width()), float(self.height())
        # The score takes the height the card has without a leaderboard; the rows of
        # the leaderboard are added underneath.
        rows = len(self._board)
        h = full / (1.0 + BOARD_HEAD + BOARD_ROW * rows) if rows else full
        panel = QRectF(0, 0, w, full)
        painter.setPen(QPen(QColor(theme.PINK), max(2.0, h * 0.012)))
        painter.setBrush(QColor(8, 4, 20, 225))
        painter.drawRoundedRect(panel.adjusted(2, 2, -2, -2), h * 0.08, h * 0.08)

        def sized(pixel_size: float, weight: Any, text: str, room: float) -> tuple[QFont, float]:
            font = QFont()
            font.setWeight(weight)
            font.setPixelSize(max(8, int(pixel_size)))
            width = QFontMetricsF(font).horizontalAdvance(text)
            if width > room:
                font.setPixelSize(max(8, int(pixel_size * room / width)))
                width = QFontMetricsF(font).horizontalAdvance(text)
            return font, width

        def centred(
            text: str, pixel_size: float, y: float, fill: QBrush | QColor, weight: Any
        ) -> None:
            font, width = sized(pixel_size, weight, text, w * 0.9)
            _outlined_text(painter, font, text, QPointF((w - width) / 2, y), fill)

        centred("SCORE", h * 0.09, h * 0.17, QColor(theme.CYAN), QFont.Weight.Bold)
        glow = QLinearGradient(w * 0.3, 0, w * 0.7, 0)
        glow.setColorAt(0.0, QColor(theme.PINK))
        glow.setColorAt(1.0, QColor(theme.CYAN))
        centred(str(self._points), h * 0.46, h * 0.62, QBrush(glow), QFont.Weight.Black)
        centred(self._grade, h * 0.12, h * 0.79, QColor(theme.GOLD), QFont.Weight.Black)
        if self._caption:
            centred(self._caption, h * 0.06, h * 0.92, QColor("white"), QFont.Weight.DemiBold)
        if not rows:
            return
        y = h * (1.0 + BOARD_HEAD * 0.45)
        centred("TONIGHT'S BEST", h * 0.05, y, QColor(theme.CYAN), QFont.Weight.Bold)
        left, right = w * 0.08, w * 0.92
        for entry in self._board:
            y += h * BOARD_ROW
            mine = entry["rank"] == self._rank
            colour = QColor(theme.GOLD) if mine else QColor("white")
            name = entry["singer"] or entry["title"]
            label = f"{entry['rank']}.  {name}"
            points = str(entry["points"])
            font, _width = sized(h * 0.055, QFont.Weight.Bold, label, (right - left) * 0.8)
            _outlined_text(painter, font, label, QPointF(left, y), colour)
            font, width = sized(h * 0.055, QFont.Weight.Black, points, w * 0.2)
            _outlined_text(painter, font, points, QPointF(right - width, y), colour)
