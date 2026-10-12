"""Scrollable lists of song cards used by every browsing page."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QMouseEvent, QPixmap
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


class _Grip(QLabel):
    """The handle on a row that is dragged to move the row within its list."""

    def __init__(self, row: SongRow) -> None:
        super().__init__("\u2261")  # three stacked lines
        self.setObjectName("grip")
        self.setFixedWidth(26)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to change the order")
        self._row = row

    def _list(self) -> SongList | None:
        parent = self._row.parentWidget()
        while parent is not None and not isinstance(parent, SongList):
            parent = parent.parentWidget()
        return parent

    def mousePressEvent(self, event: QMouseEvent) -> None:
        song_list = self._list()
        if song_list is not None and event.button() == Qt.MouseButton.LeftButton:
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            song_list.drag_start(self._row)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        song_list = self._list()
        if song_list is not None:
            song_list.drag_to(event.globalPosition().toPoint())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        song_list = self._list()
        if song_list is not None:
            song_list.drag_end(event.globalPosition().toPoint())


class SongRow(QFrame):
    def __init__(
        self,
        song: Song,
        actions: list[Action],
        thumbnails: ThumbnailLoader,
        tags: list[QLabel] | None = None,
        index: int | None = None,
        key: str = "",
        grip: bool = False,
    ) -> None:
        super().__init__()
        self.setObjectName("songRow")
        self.key = key  # what the list reports when this row is dragged somewhere else
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 12, 8)
        layout.setSpacing(12)

        if grip:
            layout.addWidget(_Grip(self))

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
        self._rows: list[SongRow] = []
        # Reordering by dragging a row's grip: called with (row key, new position).
        self.on_move: Callable[[str, int], Any] | None = None
        self._dragged: SongRow | None = None
        self._marker = QFrame(self._body)
        self._marker.setObjectName("dropMarker")
        self._marker.setFixedHeight(4)
        self._marker.hide()
        self.show_message(empty_text)

    def _slot(self, where: QPoint) -> int:
        """Between which rows the point (global) falls: 0 is above the first row."""
        y = self._body.mapFromGlobal(where).y()
        return sum(1 for row in self._rows if row.geometry().center().y() < y)

    def drag_start(self, row: SongRow) -> None:
        if row in self._rows and self.on_move is not None:
            self._dragged = row
            row.setProperty("dragging", True)
            row.style().unpolish(row)
            row.style().polish(row)

    def drag_to(self, where: QPoint) -> None:
        if self._dragged is None:
            return
        slot = self._slot(where)
        if slot < len(self._rows):
            y = self._rows[slot].geometry().top() - self._layout.spacing() // 2 - 2
        else:
            y = self._rows[-1].geometry().bottom() + self._layout.spacing() // 2 - 1
        self._marker.setGeometry(0, max(0, y), self._body.width() - 8, 4)
        self._marker.show()
        self._marker.raise_()
        self.ensureVisible(0, self._body.mapFromGlobal(where).y(), 0, 60)

    def drag_end(self, where: QPoint) -> None:
        row, self._dragged = self._dragged, None
        self._marker.hide()
        if row is None or row not in self._rows:
            return
        row.setProperty("dragging", False)
        row.style().unpolish(row)
        row.style().polish(row)
        old = self._rows.index(row)
        slot = self._slot(where)
        new = slot if slot <= old else slot - 1  # its own place no longer counts
        if new != old and self.on_move is not None:
            self.on_move(row.key, new)

    def _clear(self) -> None:
        self._rows = []
        self._dragged = None
        self._marker.hide()
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
        self._rows = list(rows)
        for i, row in enumerate(rows):
            self._layout.insertWidget(i, row)
        fade(self._body, 1.0, 180, start=0.0)
