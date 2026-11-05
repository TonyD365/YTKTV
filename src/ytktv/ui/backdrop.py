"""The console's night-sky background: stars and soft coloured glows, drawn once and cached."""

from __future__ import annotations

import random
import tempfile
from pathlib import Path

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPaintEvent, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

VERSION = 1  # bump to redraw the cached picture after changing it


def draw(width: int = 1920, height: int = 1080, seed: int = 7) -> QImage:
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#0a0518"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    # Glows: magenta low on the left, violet in the middle, teal on the right.
    for x, y, radius, colour in (
        (0.1, 0.9, 0.7, QColor(255, 61, 154, 70)),
        (0.55, 0.35, 0.6, QColor(139, 92, 255, 80)),
        (0.95, 0.75, 0.55, QColor(46, 230, 255, 45)),
    ):
        centre = QPointF(width * x, height * y)
        glow = QRadialGradient(centre, width * radius)
        glow.setColorAt(0, colour)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        painter.setBrush(glow)
        painter.drawRect(image.rect())
    stars = random.Random(seed)
    for _ in range(700):
        point = QPointF(stars.random() * width, stars.random() * height)
        size = stars.choice((0.6, 0.8, 1.0, 1.0, 1.4, 2.2))
        painter.setBrush(QColor(255, 255, 255, stars.randint(60, 230)))
        painter.drawEllipse(point, size, size)
    for _ in range(14):  # a few bright stars with a halo
        point = QPointF(stars.random() * width, stars.random() * height)
        halo = QRadialGradient(point, 9)
        halo.setColorAt(0, QColor(255, 255, 255, 200))
        halo.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(halo)
        painter.drawEllipse(point, 9, 9)
    painter.end()
    return image


def path() -> str:
    """The picture as a file, for a style sheet's border-image."""
    file = Path(tempfile.gettempdir()) / f"ytktv-backdrop-{VERSION}.png"
    if not file.exists():
        draw().save(str(file))
    return file.as_posix()


class Backdrop(QWidget):
    """A widget whose background is the night sky, scaled to fill it."""

    def __init__(self) -> None:
        super().__init__()
        self._sky = QPixmap(path())

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802 (Qt)
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._sky)
