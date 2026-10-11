"""Draw the app icon. Usage: python packaging/make_icon.py OUT_DIR

Writes icon.png (1024 px) and icon.ico; the macOS build turns the PNG into an
.icns with iconutil.
"""

from __future__ import annotations

import os
import sys
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
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "build/icon")
    out.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication([])  # fonts need an application object
    image = draw()
    image.save(str(out / "icon.png"))
    small = image.scaled(
        256, 256, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    small.save(str(out / "icon.ico"))
    del app


if __name__ == "__main__":
    main()
