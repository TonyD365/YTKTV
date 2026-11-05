"""The home screen: big colour tiles like a KTV room's song console, with the room beside them."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ytktv.ui import icons
from ytktv.ui.pages import Context, Page

# (page, label, icon, colour): one tile each, in reading order.
TILES = (
    ("search", "Search", "search", "#d4537e"),
    ("artists", "Artists", "star", "#7f77dd"),
    ("hot", "Hot Songs", "fire", "#1d9e75"),
    ("playlists", "Playlists", "list", "#ba7517"),
    ("favorites", "Favorites", "heart", "#b0365f"),
    ("queue", "Selected", "mic", "#534ab7"),
    ("history", "Sung", "check", "#378add"),
    ("mixer", "Mixer", "sliders", "#5f5e5a"),
)


class Tile(QPushButton):
    """A big touch tile: its icon and name together in the middle."""

    def __init__(self, icon: str, text: str) -> None:
        super().__init__()
        column = QVBoxLayout(self)
        column.setSpacing(10)
        column.addStretch()
        picture = QLabel()
        picture.setPixmap(icons.pixmap(icon, "#ffffff", 64))
        self.label = QLabel(text)
        self.label.setStyleSheet("font-size: 22px; font-weight: 800; color: white;")
        for widget in (picture, self.label):
            widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            widget.setStyleSheet(widget.styleSheet() + "background: transparent;")
            column.addWidget(widget)
        column.addStretch()

    def setText(self, text: str) -> None:  # noqa: N802 (Qt)
        self.label.setText(text)

    def text(self) -> str:
        return self.label.text()


class HomePage(Page):
    """Tiles that open every part of the console, and what is playing and coming up."""

    def __init__(self, ctx: Context, open_page: Callable[[str], None]) -> None:
        super().__init__("", ctx)
        while self.header.count():  # no page title on the home screen
            item = self.header.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.body.setContentsMargins(20, 6, 20, 14)
        columns = QHBoxLayout()
        columns.setSpacing(18)
        self.body.addLayout(columns, stretch=1)

        # The room: now playing, up next, how many songs are waiting.
        room = QVBoxLayout()
        room.setSpacing(10)
        now = QFrame()
        now.setObjectName("homeNow")
        now_box = QVBoxLayout(now)
        now_box.setContentsMargins(14, 14, 14, 14)
        now_box.setSpacing(8)
        self.cover = QLabel()
        self.cover.setObjectName("homeCover")
        self.cover.setMinimumHeight(110)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.cover.setScaledContents(True)
        now_box.addWidget(self.cover, stretch=1)
        caption = QLabel("NOW PLAYING")
        caption.setObjectName("caption")
        now_box.addWidget(caption)
        self.now_title = QLabel("Pick a song to start the party")
        self.now_title.setObjectName("homeTitle")
        self.now_title.setWordWrap(True)
        self.now_title.setTextFormat(Qt.TextFormat.PlainText)
        now_box.addWidget(self.now_title)
        self.now_singer = QLabel("")
        self.now_singer.setObjectName("songSub")
        now_box.addWidget(self.now_singer)
        room.addWidget(now, stretch=1)

        up_next = QLabel("UP NEXT")
        up_next.setObjectName("caption")
        room.addWidget(up_next)
        self.next_rows: list[QLabel] = []
        for _ in range(3):
            row = QLabel("")
            row.setObjectName("homeRow")
            row.setTextFormat(Qt.TextFormat.PlainText)
            room.addWidget(row)
            self.next_rows.append(row)
        self.more = QPushButton("See the whole queue")
        self.more.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more.clicked.connect(lambda: open_page("queue"))
        room.addWidget(self.more)
        side = QWidget()
        side.setLayout(room)
        columns.addWidget(side, stretch=38)

        # The tile wall.
        grid = QGridLayout()
        grid.setSpacing(14)
        self.tiles: dict[str, Tile] = {}
        for index, (key, label, icon, colour) in enumerate(TILES):
            tile = Tile(icon, label)
            tile.setObjectName("tile")
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setMinimumSize(150, 120)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            # A glossy tile: lighter at the top, with a bright edge, like a KTV touch screen.
            top = QColor(colour).lighter(135).name()
            tile.setStyleSheet(
                "#tile { background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
                f" stop:0 {top}, stop:0.5 {colour}, stop:1 {QColor(colour).darker(125).name()});"
                " border: 1px solid rgba(255, 255, 255, 0.35); }"
            )
            tile.clicked.connect(lambda _checked=False, k=key: open_page(k))
            grid.addWidget(tile, index // 4, index % 4)
            self.tiles[key] = tile
        wall = QWidget()
        wall.setLayout(grid)
        columns.addWidget(wall, stretch=62)
        self._cover_url = ""

    def on_state(self, state: dict[str, Any]) -> None:
        current = state.get("current")
        if current:
            song = current["song"]
            self.now_title.setText(song["title"])
            self.now_singer.setText(current.get("singer") or song.get("channel") or "")
            url = song.get("thumbnail") or ""
            if url and url != self._cover_url:
                self._cover_url = url
                self.ctx.thumbnails.load(url, self._set_cover)
        else:
            self.now_title.setText("Pick a song to start the party")
            self.now_singer.setText("Scan the QR code to queue songs from a phone")
            self._cover_url = ""
            self.cover.clear()
        queue = state.get("queue") or []
        for row, item in zip(self.next_rows, [*queue[:3], None, None, None], strict=False):
            if item is None:
                row.setText("")
                row.setVisible(False)
                continue
            singer = f"   ·   {item['singer']}" if item.get("singer") else ""
            row.setText(item["song"]["title"] + singer)
            row.setVisible(True)
        if not queue:
            self.next_rows[0].setText("Nothing queued yet")
            self.next_rows[0].setVisible(True)
        self.more.setText(f"See the whole queue ({len(queue)})" if queue else "See the whole queue")
        self.tiles["queue"].setText(f"Selected ({len(queue)})" if queue else "Selected")

    def _set_cover(self, pixmap: QPixmap) -> None:
        self.cover.setPixmap(pixmap)
