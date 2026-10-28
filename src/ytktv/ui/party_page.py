"""The Party page: danmaku, emoji reactions and crowd sounds in one place."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from ytktv.core.controller import REACTIONS
from ytktv.ui.pages import Context, Page

SOUNDS = (
    ("applause", "👏  Applause"),
    ("cheer", "🙌  Cheer"),
    ("airhorn", "📣  Air Horn"),
    ("drumroll", "🥁  Drum Roll"),
)


class PartyPage(Page):
    def __init__(self, ctx: Context, send_danmaku: Callable[[str], bool]) -> None:
        super().__init__("Party", ctx)
        self._send = send_danmaku

        self.body.addWidget(self._caption("DANMAKU: A MESSAGE THAT FLIES ACROSS THE MV SCREEN"))
        row = QHBoxLayout()
        self.danmaku_input = QLineEdit()
        self.danmaku_input.setPlaceholderText("Say something...")
        self.danmaku_input.setMaxLength(60)
        self.danmaku_input.returnPressed.connect(self.send)
        send = QPushButton("Send")
        send.setProperty("accent", True)
        send.clicked.connect(self.send)
        row.addWidget(self.danmaku_input, stretch=1)
        row.addWidget(send)
        self.body.addLayout(row)

        self.body.addWidget(self._caption("CHEER THE SINGER"))
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, emoji in enumerate(REACTIONS):
            button = QPushButton(emoji)
            button.setObjectName("reaction")
            button.setMinimumHeight(84)
            button.setStyleSheet("font-size: 40px;")
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _c=False, e=emoji: ctx.controller.send_reaction(e))
            grid.addWidget(button, index // 4, index % 4)
        self.body.addLayout(grid)

        self.body.addWidget(self._caption("CROWD SOUNDS"))
        sounds = QHBoxLayout()
        for name, label in SOUNDS:
            button = QPushButton(label)
            button.setMinimumHeight(64)
            button.setProperty("gold", True)
            button.clicked.connect(lambda _c=False, n=name: ctx.controller.play_sfx(n))
            sounds.addWidget(button)
        self.body.addLayout(sounds)
        self.body.addStretch()

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("caption")
        return label

    def send(self) -> None:
        if self._send(self.danmaku_input.text()):
            self.danmaku_input.clear()
