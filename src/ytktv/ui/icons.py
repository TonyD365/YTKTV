"""Our own icons for Qt: buttons, labels and rich text, in place of system emoji.

The drawings themselves are in ytktv.icon_set, shared with the phone page.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QObject, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QAbstractButton, QLabel, QWidget

from ytktv.icon_set import EMOJI, EMOJI_RE, split, svg


def html(text: str, colour: str = "#ffffff", size: int = 18) -> str:
    """Rich text with each emoji replaced by its icon, for labels that show HTML."""

    def image(match: re.Match[str]) -> str:
        path = png_file(EMOJI[match.group(1)], colour, size * 2)
        return f"<img src='{path}' width='{size}' height='{size}'> "

    return EMOJI_RE.sub(image, text)


_cache = Path(tempfile.gettempdir()) / "ytktv-icons"


def png_file(name: str, colour: str, size: int) -> str:
    """The icon drawn to a PNG file (rich text can show files but not SVG strings)."""
    key = hashlib.sha1(f"{name}{colour}{size}".encode()).hexdigest()[:12]
    path = _cache / f"{name}-{key}.png"
    if not path.exists():
        _cache.mkdir(parents=True, exist_ok=True)
        pixmap(name, colour, size).save(str(path))
    return str(path)


def pixmap(name: str, colour: str = "#ffffff", size: int = 48) -> QPixmap:
    image = QPixmap(size, size)
    image.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, colour).encode()))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter)
    painter.end()
    return image


def icon(name: str, colour: str = "#ffffff") -> QIcon:
    return QIcon(pixmap(name, colour, 96))


def set_text(button: QAbstractButton, text: str, colour: str = "#ffffff") -> None:
    """Set a button's text; an emoji in it becomes the button's icon instead."""
    name, rest = split(text)
    button.setText(rest)
    if name is not None:
        button.setIcon(icon(name, colour))


def _swap(widget: QAbstractButton | QLabel) -> None:
    text = widget.text()
    if not text or not EMOJI_RE.search(text):
        return
    if isinstance(widget, QAbstractButton):
        name, rest = split(text)
        widget.setText(rest)
        if name is not None:
            widget.setIcon(icon(name))
            if not rest:  # an icon-only button: let the icon fill it
                side = max(18, min(widget.minimumHeight() or 28, 40) - 12)
                widget.setIconSize(QSize(side, side))
    elif widget.textFormat() == Qt.TextFormat.PlainText:
        widget.setText(EMOJI_RE.sub("", text).strip())
    else:
        widget.setText(html(text))


def apply(root: QWidget) -> None:
    """Swap the emoji in every button and label under *root* for icons."""
    for widget in root.findChildren(QAbstractButton) + root.findChildren(QLabel):
        _swap(widget)


class _Swapper(QObject):
    """Swaps emoji for icons in every button and label the moment it is first shown."""

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt)
        if event.type() == QEvent.Type.Polish and isinstance(watched, QAbstractButton | QLabel):
            _swap(watched)
        return False


def install(app: QObject) -> None:
    """Use our icons in the whole app, dialogs and lists made later included."""
    swapper = _Swapper(app)
    app.installEventFilter(swapper)
