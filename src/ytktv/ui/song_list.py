"""Scrollable lists of song cards used by every browsing page."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ytktv.core.models import Song
from ytktv.ui.support import ThumbnailLoader, fade, format_time

THUMB_W, THUMB_H = 128, 72

STEM_TAGS = {
    "queued": ("busy", "Instrumental queued"),
    "downloading": ("busy", "Preparing instrumental"),
    "separating": ("busy", "Separating vocals"),
    "ready": ("ready", "Instrumental ready"),
    "failed": ("", "No instrumental"),
}

# (button text, style property or "", callback)
Action = tuple[str, str, Callable[[], Any]]


def tag(text: str, kind: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("tag")
    label.setProperty("kind", kind)
    label.setTextFormat(Qt.TextFormat.PlainText)
    return label


class SongRow(QFrame):
    def __init__(
        self,
        song: Song,
        actions: list[Action],
        thumbnails: ThumbnailLoader,
        tags: list[QLabel] | None = None,
        index: int | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("songRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(12)

        if index is not None:
            number = QLabel(f"{index:02d}")
            number.setObjectName("readout")
            layout.addWidget(number)

        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setStyleSheet("background: #000; border-radius: 8px;")
        self.thumb.setScaledContents(True)
        layout.addWidget(self.thumb)
        thumbnails.load(song.thumbnail, self._set_thumbnail)

        text = QVBoxLayout()
        text.setSpacing(4)
        title = QLabel(song.title)
        title.setObjectName("songTitle")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(title)
        sub_row = QHBoxLayout()
        sub_row.setSpacing(8)
        details = "  ·  ".join(
            p for p in (song.channel, format_time(song.duration) if song.duration else "") if p
        )
        sub = QLabel(details)
        sub.setObjectName("songSub")
        sub.setTextFormat(Qt.TextFormat.PlainText)
        sub_row.addWidget(sub)
        for label in tags or []:
            sub_row.addWidget(label)
        sub_row.addStretch()
        text.addLayout(sub_row)
        layout.addLayout(text, stretch=1)

        for caption, style, callback in actions:
            button = QPushButton(caption)
            button.setProperty("small", True)
            if style:
                button.setProperty(style, True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, cb=callback: cb())
            layout.addWidget(button)

    def _set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumb.setPixmap(pixmap)


class SongList(QScrollArea):
    """A vertical list of rows; call :meth:`set_rows` to replace the content."""

    def __init__(self, empty_text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._empty_text = empty_text
        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(0, 0, 8, 0)
        self._layout.setSpacing(8)
        self._layout.addStretch()
        self.setWidget(self._body)
        self.show_message(empty_text)

    def _clear(self) -> None:
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            widget: Any = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()

    def show_message(self, text: str) -> None:
        self._clear()
        if text:
            label = QLabel(text)
            label.setObjectName("hint")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setMinimumHeight(160)
            self._layout.insertWidget(0, label)

    def set_rows(self, rows: list[SongRow]) -> None:
        if not rows:
            self.show_message(self._empty_text)
            return
        self._clear()
        for i, row in enumerate(rows):
            self._layout.insertWidget(i, row)
        fade(self._body, 1.0, 180, start=0.0)
