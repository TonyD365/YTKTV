"""The Party page: danmaku, emoji reactions and crowd sounds in one place."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton

from ytktv.core.controller import REACTIONS
from ytktv.core.scenes import SCENES
from ytktv.i18n import N_, t
from ytktv.ui.pages import Context, Page

SOUNDS = (
    ("applause", N_("👏  Applause")),
    ("cheer", N_("🙌  Cheer")),
    ("airhorn", N_("📣  Air Horn")),
    ("drumroll", N_("🥁  Drum Roll")),
)


class PartyPage(Page):
    def __init__(self, ctx: Context, send_danmaku: Callable[[str], bool]) -> None:
        super().__init__(t("Party"), ctx)
        self._send = send_danmaku

        self.body.addWidget(self._caption(t("DANMAKU: A MESSAGE THAT FLIES ACROSS THE MV SCREEN")))
        row = QHBoxLayout()
        self.danmaku_input = QLineEdit()
        self.danmaku_input.setPlaceholderText(t("Say something..."))
        self.danmaku_input.setMaxLength(60)
        self.danmaku_input.returnPressed.connect(self.send)
        send = QPushButton(t("Send"))
        send.setProperty("accent", True)
        send.clicked.connect(self.send)
        row.addWidget(self.danmaku_input, stretch=1)
        row.addWidget(send)
        self.body.addLayout(row)

        self.body.addWidget(self._caption(t("PK BATTLE: TWO MICROPHONES, ONE SONG, ONE WINNER")))
        self.pk_button = QPushButton(t("⚔️  PK Battle: Off"))
        self.pk_button.setCheckable(True)
        self.pk_button.setMinimumHeight(52)
        self.pk_button.toggled.connect(self._pk)
        self.body.addWidget(self.pk_button)
        self.body.addWidget(
            self._caption(t("DUET: BLUE LINES FOR ONE, PINK FOR THE OTHER, GOLD TOGETHER"))
        )
        self.duet_button = QPushButton(t("🎭  Duet: Off"))
        self.duet_button.setCheckable(True)
        self.duet_button.setMinimumHeight(52)
        self.duet_button.toggled.connect(self._duet)
        self.body.addWidget(self.duet_button)
        self.body.addWidget(self._caption(t("MOOD: THE TV'S LIGHTS AND SMART LIGHTS IN ONE TAP")))
        scenes = QHBoxLayout()
        self.scene_buttons: dict[str, QPushButton] = {}
        for key, title in (("", t("✨ Usual")), *((k, t(s.title)) for k, s in SCENES.items())):
            button = QPushButton(title)
            button.setCheckable(True)
            button.setMinimumHeight(56)
            button.clicked.connect(lambda _c=False, k=key: ctx.controller.set_scene(k))
            scenes.addWidget(button)
            self.scene_buttons[key] = button
        self.body.addLayout(scenes)
        self.body.addWidget(self._caption(t("CHEER THE SINGER")))
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

        self.body.addWidget(self._caption(t("CROWD SOUNDS")))
        sounds = QHBoxLayout()
        for name, label in SOUNDS:
            button = QPushButton(t(label))
            button.setMinimumHeight(64)
            button.setProperty("gold", True)
            button.clicked.connect(lambda _c=False, n=name: ctx.controller.play_sfx(n))
            sounds.addWidget(button)
        self.body.addLayout(sounds)
        self.body.addStretch()

    def on_state(self, state: dict[str, Any]) -> None:
        current = state.get("scene") or ""
        for key, button in self.scene_buttons.items():
            button.setChecked(key == current)

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("caption")
        return label

    def send(self) -> None:
        if self._send(self.danmaku_input.text()):
            self.danmaku_input.clear()

    def _duet(self, on: bool) -> None:
        self.ctx.controller.set_duet_mode(on)
        self.duet_button.setText(t("Duet: On") if on else t("Duet: Off"))

    def _pk(self, on: bool) -> None:
        self.ctx.controller.set_pk_mode(on)
        self.pk_button.setText(t("PK Battle: On") if on else t("PK Battle: Off"))
