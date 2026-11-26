"""Draw the installers' pictures from the app icons. Usage: python packaging/draw_installer_art.py

Writes packaging/installer/art/:
  <app>-wizard.bmp, <app>-wizard@2x.bmp              Windows setup, the tall picture on the
                                                      Welcome and Finished pages (164x314)
  <app>-wizard-small.bmp, <app>-wizard-small@2x.bmp  Windows setup, top right of other pages
  <app>-pkg-background.png                            macOS installer, bottom left, faint, so
                                                      the text stays readable in light and dark
for app = ytktv and desk. The results are committed; run this again after the icon changes.
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QRadialGradient,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "packaging" / "installer" / "art"
APPS = {
    "ytktv": ("YTKTV", ROOT / "src/ytktv/ui/assets/icon.png", "Karaoke"),
    "desk": ("YTKTV Desk", ROOT / "src/ytktv/desk/assets/icon.png", "Front desk"),
}
# The Neon theme (src/ytktv/ui/theme.py).
BG_TOP, BG, BG_BOTTOM = QColor("#1b0b3d"), QColor("#0d0720"), QColor("#07101f")
PINK, CYAN, TEXT, MUTED = QColor("#ff3d9a"), QColor("#2ee6ff"), QColor("#f3eeff"), QColor("#a99bd6")


def _glow(p: QPainter, centre: QPointF, radius: float, colour: QColor, alpha: int) -> None:
    g = QRadialGradient(centre, radius)
    c = QColor(colour)
    c.setAlpha(alpha)
    g.setColorAt(0, c)
    c.setAlpha(0)
    g.setColorAt(1, c)
    p.fillRect(QRectF(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2), g)


def _background(p: QPainter, w: float, h: float) -> None:
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, BG_TOP)
    g.setColorAt(0.5, BG)
    g.setColorAt(1, BG_BOTTOM)
    p.fillRect(QRectF(0, 0, w, h), g)
    _glow(p, QPointF(w * 0.15, h * 0.1), w * 0.9, PINK, 70)
    _glow(p, QPointF(w * 0.95, h * 0.85), w * 0.9, CYAN, 45)


def _wizard(icon: QImage, name: str, tagline: str, scale: int) -> QImage:
    w, h = 164 * scale, 314 * scale
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    _background(p, w, h)
    side = 104 * scale
    target = QRectF((w - side) / 2, 70 * scale, side, side)
    _glow(p, target.center(), side * 0.9, PINK, 90)
    p.drawImage(target, icon)
    font = QFont()
    font.setBold(True)
    font.setPixelSize(20 * scale)
    p.setFont(font)
    p.setPen(TEXT)
    p.drawText(QRectF(0, 196 * scale, w, 30 * scale), Qt.AlignmentFlag.AlignHCenter, name)
    font.setBold(False)
    font.setPixelSize(12 * scale)
    p.setFont(font)
    p.setPen(MUTED)
    p.drawText(QRectF(0, 226 * scale, w, 20 * scale), Qt.AlignmentFlag.AlignHCenter, tagline)
    line = QLinearGradient(w * 0.25, 0, w * 0.75, 0)
    line.setColorAt(0, PINK)
    line.setColorAt(1, CYAN)
    p.fillRect(QRectF(w * 0.25, 256 * scale, w * 0.5, 3 * scale), line)
    p.end()
    return img


def _small(icon: QImage, scale: int) -> QImage:
    side = 55 * scale
    img = QImage(side, side, QImage.Format.Format_RGB32)
    img.fill(QColor("#ffffff"))  # the page behind it is white in the classic look
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    pad = 3 * scale
    p.drawImage(QRectF(pad, pad, side - 2 * pad, side - 2 * pad), icon)
    p.end()
    return img


def _pkg_background(icon: QImage) -> QImage:
    # The Installer window's left side is about 620x418 pt; drawn at 2x for Retina.
    w, h = 1240, 836
    img = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    p.setOpacity(0.22)  # faint: the pages' text goes over it, in light and in dark mode
    side = 300
    p.drawImage(QRectF(40, h - side - 40, side, side), icon)
    p.end()
    return img


def _bmp(img: QImage, path: str) -> None:
    # 24-bit, the kind of bitmap every Inno Setup version takes.
    img.convertToFormat(QImage.Format.Format_RGB888).save(path, "BMP")


def main() -> None:
    app = QGuiApplication([])
    OUT.mkdir(parents=True, exist_ok=True)
    for key, (name, icon_path, tagline) in APPS.items():
        icon = QImage(str(icon_path))
        if icon.isNull():
            raise SystemExit(f"cannot read {icon_path}")
        for scale, suffix in ((1, ""), (2, "@2x")):
            _bmp(_wizard(icon, name, tagline, scale), str(OUT / f"{key}-wizard{suffix}.bmp"))
            _bmp(_small(icon, scale), str(OUT / f"{key}-wizard-small{suffix}.bmp"))
        _pkg_background(icon).save(str(OUT / f"{key}-pkg-background.png"))
        print(f"{name}: done")
    del app


if __name__ == "__main__":
    main()
