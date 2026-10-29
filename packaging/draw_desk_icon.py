"""Redraw the YTKTV Desk icon. Usage: python packaging/draw_desk_icon.py

Writes src/ytktv/desk/assets/icon.png (1024 px): the same rounded tile as the YTKTV
icon, with a front-desk service bell and the name, so the two apps look related but never get
mixed up in the Dock or the taskbar.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)


def draw(size: int = 1024) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    margin = size * 0.09
    body = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    background = QLinearGradient(body.topLeft(), body.bottomRight())
    background.setColorAt(0.0, QColor("#0f3a5c"))
    background.setColorAt(1.0, QColor("#0d0720"))
    p.setPen(QPen(QColor("#2ee6ff"), size * 0.018))
    p.setBrush(QBrush(background))
    p.drawRoundedRect(body, size * 0.2, size * 0.2)

    # A front-desk bell seen slightly from above: a round base, a shiny dome, and the
    # plunger on top that you press to ring it, with two "ding" marks beside it.
    p.save()
    p.translate(0, -size * 0.045)  # leave room below for the name
    cx = size * 0.5
    base = QRectF(cx - size * 0.3, size * 0.555, size * 0.6, size * 0.1)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#1b1236"))
    p.drawEllipse(base.translated(0, size * 0.018))
    plate = QLinearGradient(base.left(), 0, base.right(), 0)
    plate.setColorAt(0.0, QColor("#b8860b"))
    plate.setColorAt(0.5, QColor("#ffe7a0"))
    plate.setColorAt(1.0, QColor("#b8860b"))
    p.setBrush(QBrush(plate))
    p.drawEllipse(base)

    dome_rect = QRectF(cx - size * 0.24, size * 0.33, size * 0.48, size * 0.5)
    dome = QPainterPath()
    dome.moveTo(dome_rect.left(), size * 0.585)
    dome.arcTo(dome_rect, 180, -180)
    dome.closeSubpath()
    shade = QLinearGradient(dome_rect.left(), 0, dome_rect.right(), 0)
    shade.setColorAt(0.0, QColor("#ffd36b"))
    shade.setColorAt(0.35, QColor("#fff4cf"))
    shade.setColorAt(1.0, QColor("#ff3d9a"))
    p.setBrush(QBrush(shade))
    p.drawPath(dome)
    rim = QRectF(dome_rect.left(), size * 0.565, dome_rect.width(), size * 0.04)
    p.setBrush(QColor("#c9416f"))
    p.drawEllipse(rim)

    p.setBrush(QColor("#e8d9ff"))
    p.drawRoundedRect(
        QRectF(cx - size * 0.018, size * 0.26, size * 0.036, size * 0.08), size * 0.01, size * 0.01
    )
    button = QLinearGradient(0, size * 0.235, 0, size * 0.275)
    button.setColorAt(0.0, QColor("#ffffff"))
    button.setColorAt(1.0, QColor("#b9a8e6"))
    p.setBrush(QBrush(button))
    p.drawEllipse(QRectF(cx - size * 0.07, size * 0.235, size * 0.14, size * 0.045))

    p.setPen(QPen(QColor("#2ee6ff"), size * 0.022, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    for side in (-1, 1):
        for k, (dx, length) in enumerate(((0.17, 0.05), (0.23, 0.065))):
            x = cx + side * size * dx
            y = size * (0.25 + 0.035 * k)
            p.drawLine(QPointF(x, y), QPointF(x + side * size * length * 0.6, y - size * length))

    p.restore()
    glow = QLinearGradient(body.left(), 0, body.right(), 0)
    glow.setColorAt(0.0, QColor("#ff3d9a"))
    glow.setColorAt(1.0, QColor("#2ee6ff"))
    font = QFont()
    font.setWeight(QFont.Weight.Black)
    font.setPixelSize(int(size * 0.135))
    p.setFont(font)
    p.setPen(QPen(QBrush(glow), 1))
    p.drawText(QRectF(0, size * 0.63, size, size * 0.15), Qt.AlignmentFlag.AlignCenter, "YTKTV")
    small = QFont()
    small.setWeight(QFont.Weight.Bold)
    small.setPixelSize(int(size * 0.058))
    small.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.022)
    p.setFont(small)
    p.setPen(QColor("#f3eeff"))
    p.drawText(QRectF(0, size * 0.77, size, size * 0.08), Qt.AlignmentFlag.AlignCenter, "DESK")
    p.end()
    return image


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "src" / "ytktv" / "desk" / "assets"
    out.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])  # fonts need an application object
    draw().save(str(out / "icon.png"))
    del app
    print(out / "icon.png")


if __name__ == "__main__":
    main()
