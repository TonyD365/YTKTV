"""The Games page: party games whose results show big on the MV screen."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QLabel, QPushButton, QSizePolicy

from ytktv.ui.pages import Context, Page

GAMES = (
    ("dice", "🎲\nRoll the dice", "#d4537e"),
    ("spin", "🎡\nWho sings next?", "#7f77dd"),
    ("truth", "💬\nTruth", "#1d9e75"),
    ("dare", "🔥\nDare", "#ba7517"),
)


class GamesPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Games", ctx)
        grid = QGridLayout()
        grid.setSpacing(14)
        for index, (game, label, colour) in enumerate(GAMES):
            tile = QPushButton(label)
            tile.setObjectName("tile")
            tile.setStyleSheet(f"#tile {{ background: {colour}; }}")
            tile.setMinimumHeight(140)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.clicked.connect(lambda _c=False, g=game: self.play(g))
            grid.addWidget(tile, index // 2, index % 2)
        self.body.addLayout(grid, stretch=1)
        self.result = QLabel("Pick a game. The result shows on the MV screen too.")
        self.result.setObjectName("homeTitle")
        self.result.setWordWrap(True)
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.result)

    def play(self, game: str) -> dict[str, Any]:
        result = self.ctx.controller.play_game(game)
        self.result.setText(
            "  ".join(p for p in (result["title"], result["text"], result["detail"]) if p)
        )
        return result
