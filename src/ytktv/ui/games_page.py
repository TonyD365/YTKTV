"""The Games page: party games whose results show big on the MV screen."""

from __future__ import annotations

import random
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
)

from ytktv.ui.pages import Context, Page
from ytktv.ui.support import run_async
from ytktv.youtube.search import HOT_CATEGORIES

GAMES = (
    ("dice", "🎲\nRoll the dice", "#d4537e"),
    ("spin", "🎡\nWho sings next?", "#7f77dd"),
    ("truth", "💬\nTruth", "#1d9e75"),
    ("dare", "🔥\nDare", "#ba7517"),
    ("bomb", "💣\nNumber bomb", "#c2410c"),
    ("liar_roll", "🎲\nLiar's dice: roll", "#5b3fa0"),
    ("liar_reveal", "👀\nLiar's dice: reveal", "#3f2a7a"),
    ("random", "🎰\nRandom song", "#0e7490"),
    ("challenge", "🎤\nChallenge card", "#be185d"),
    ("lots", "🥢\nDraw lots", "#4d7c0f"),
    ("highlow", "⚖️\nHigh or low", "#7c2d12"),
    ("sevens", "7️⃣\nSevens: next", "#1e40af"),
    ("countdown", "⏱\n10-second countdown", "#9d174d"),
    ("coin", "🪙\nFlip a coin", "#a16207"),
)
COLUMNS = 4


class GamesPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Games", ctx)
        grid = QGridLayout()
        grid.setSpacing(12)
        for index, (game, label, colour) in enumerate(GAMES):
            tile = QPushButton(label)
            tile.setObjectName("tile")
            tile.setStyleSheet(f"#tile {{ background: {colour}; }}")
            tile.setMinimumHeight(96)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.clicked.connect(lambda _c=False, g=game: self.play(g))
            grid.addWidget(tile, index // COLUMNS, index % COLUMNS)
        self.body.addLayout(grid, stretch=1)

        guess_row = QHBoxLayout()
        guess_row.addWidget(QLabel("💣 Your guess"))
        self.guess = QSpinBox()
        self.guess.setRange(1, 100)
        self.guess.setValue(50)
        self.guess.setMinimumWidth(110)
        self.guess.setStyleSheet(
            "QSpinBox { background: #1a1430; color: white; border: 1px solid #33284f;"
            " border-radius: 8px; padding: 6px 10px; font-size: 16px; }"
        )
        guess = QPushButton("Guess")
        guess.clicked.connect(lambda: self.play("bomb_guess"))
        guess_row.addWidget(self.guess)
        guess_row.addWidget(guess)
        guess_row.addStretch()
        self.body.addLayout(guess_row)

        self.result = QLabel("Pick a game. The result shows on the MV screen too.")
        self.result.setObjectName("homeTitle")
        self.result.setWordWrap(True)
        self.result.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body.addWidget(self.result)

    def play(self, game: str) -> dict[str, Any] | None:
        controller = self.ctx.controller
        if game == "random":
            self.result.setText("🎰 Drawing a random song…")
            category = random.choice(list(HOT_CATEGORIES))
            run_async(
                lambda: self.ctx.youtube.hot(category),
                lambda songs: self._show(controller.random_song(songs)),
                lambda _exc: self.result.setText("Could not load a song list."),
            )
            return None
        if game == "countdown":
            controller.countdown(10)
            self.result.setText("⏱ Counting down on the TV")
            return None
        value = self.guess.value() if game == "bomb_guess" else None
        result = controller.play_game(game, value=value, player="Console")
        if game == "liar_roll":
            # Only the person at the console should look at this.
            result = dict(result, text=f"Your dice: {controller.liars.hand('Console')}")
        self._show(result)
        return result

    def _show(self, result: dict[str, Any] | None) -> None:
        if result:
            parts = (result["title"], result["text"], result.get("detail", ""))
            self.result.setText("  ".join(p for p in parts if p))
