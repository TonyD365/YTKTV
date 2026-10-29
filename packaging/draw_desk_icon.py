"""Redraw the YTKTV Desk icon. Usage: python packaging/draw_desk_icon.py

Writes src/ytktv/desk/assets/icon.png (1024 px): the same rounded tile as the YTKTV
icon, with a front-desk service bell, so the two apps look related but never get
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

    # The bell: a dome on a flat base, with a small knob on top.
    gold = QLinearGradient(0, size * 0.25, 0, size * 0.62)
    gold.setColorAt(0.0, QColor("#ffe08a"))
    gold.setColorAt(1.0, QColor("#ff3d9a"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(gold))
    cx, base_y, radius = size * 0.5, size * 0.6, size * 0.25
    dome = QPainterPath()
    dome.moveTo(cx - radius, base_y)
    dome.arcTo(QRectF(cx - radius, base_y - radius, 2 * radius, 2 * radius), 180, -180)
    dome.closeSubpath()
    p.drawPath(dome)
    p.drawEllipse(QPointF(cx, base_y - radius - size * 0.03), size * 0.045, size * 0.045)
    p.setBrush(QColor("#f3eeff"))
    p.drawRoundedRect(QRectF(cx - radius * 1.25, base_y + size * 0.015, radius * 2.5, size * 0.06),
                      size * 0.03, size * 0.03)
    shine = QPainterPath()
    shine.addEllipse(QRectF(cx - radius * 0.62, base_y - radius * 0.78, radius * 0.32, radius * 0.5))
    p.setBrush(QColor(255, 255, 255, 110))
    p.drawPath(shine)

    font = QFont()
    font.setWeight(QFont.Weight.Black)
    font.setPixelSize(int(size * 0.13))
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, size * 0.02)
    p.setFont(font)
    p.setPen(QColor("#2ee6ff"))
    p.drawText(QRectF(0, size * 0.69, size, size * 0.16), Qt.AlignmentFlag.AlignCenter, "DESK")
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
