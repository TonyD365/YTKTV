"""Redraw the app icon. Usage: python packaging/draw_icon.py

Writes src/ytktv/ui/assets/icon.png (1024 px), the one picture every platform's
icon is made from. Run this on a Mac: the lettering uses the system font, and build
machines without fonts (the Windows one) produced an icon with no letters when each
platform drew its own.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPen,
)


def draw(size: int = 1024) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.09
    body = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    background = QLinearGradient(body.topLeft(), body.bottomRight())
    background.setColorAt(0.0, QColor("#3a1a7a"))
    background.setColorAt(1.0, QColor("#0d0720"))
    painter.setPen(QPen(QColor("#ff3d9a"), size * 0.018))
    painter.setBrush(QBrush(background))
    painter.drawRoundedRect(body, size * 0.2, size * 0.2)

    glow = QLinearGradient(body.left(), 0, body.right(), 0)
    glow.setColorAt(0.0, QColor("#ff3d9a"))
    glow.setColorAt(1.0, QColor("#2ee6ff"))
    font = QFont()
    font.setWeight(QFont.Weight.Black)
    font.setPixelSize(int(size * 0.3))
    painter.setFont(font)
    painter.setPen(QPen(QBrush(glow), 1))
    painter.drawText(QRectF(0, size * 0.2, size, size * 0.34), Qt.AlignmentFlag.AlignCenter, "YT")
    painter.setPen(QColor("#f3eeff"))
    painter.drawText(QRectF(0, size * 0.48, size, size * 0.34), Qt.AlignmentFlag.AlignCenter, "KTV")
    painter.end()
    return image


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "src" / "ytktv" / "ui" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])  # fonts need an application object
    draw().save(str(out / "icon.png"))
    del app
    print(out / "icon.png")


if __name__ == "__main__":
    main()
