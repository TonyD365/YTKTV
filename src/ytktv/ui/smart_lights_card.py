"""The Smart Lights card in Settings: WLED or Philips Hue lights that follow the music."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ytktv import smart_lights
from ytktv.core.controller import KTVController
from ytktv.ui.support import run_async


class SmartLightsCard(QFrame):
    def __init__(self, controller: KTVController) -> None:
        super().__init__()
        self.controller = controller
        settings = controller.settings
        self.setObjectName("settingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        head = QLabel("SMART LIGHTS")
        head.setObjectName("settingsHead")
        layout.addWidget(head)
        note = QLabel(
            "Room lights that change colour with the music, like the TV's edge lights: a WLED"
            " strip, or Philips Hue lights through their bridge (all lights on the bridge)."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for key, name in smart_lights.KINDS.items():
            self.kind.addItem(name, key)
        self.kind.setCurrentIndex(list(smart_lights.KINDS).index(settings.smart_lights))
        self.host = QLineEdit(settings.smart_lights_host)
        self.host.setPlaceholderText("Address, e.g. 192.168.1.50")
        self.pair_button = QPushButton("Pair Hue Bridge")
        self.pair_button.setToolTip("Press the round button on the bridge first, then this")
        self.pair_button.clicked.connect(lambda: self.pair())
        test = QPushButton("Test")
        test.clicked.connect(lambda: self.test())
        row.addWidget(self.kind)
        row.addWidget(self.host, stretch=1)
        row.addWidget(self.pair_button)
        row.addWidget(test)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.kind.currentIndexChanged.connect(lambda _i: self.save())
        self.host.editingFinished.connect(self.save)
        self._show_kind()

    def _show_kind(self) -> None:
        kind = self.controller.settings.smart_lights
        self.pair_button.setVisible(kind == "hue")
        self.host.setEnabled(kind != "off")
        if kind == "hue" and not self.controller.settings.hue_key:
            self.status.setText("Not paired yet: press the bridge's button, then Pair Hue Bridge.")

    def save(self) -> None:
        settings = self.controller.settings
        settings.smart_lights = str(self.kind.currentData())
        settings.smart_lights_host = self.host.text().strip()
        self.controller.store.save()
        self._show_kind()

    def pair(self, request: Callable[..., Any] = smart_lights.request) -> None:
        self.save()
        host = self.controller.settings.smart_lights_host
        if not host:
            self.status.setText("Type the Hue bridge's address first.")
            return
        self.status.setText("Pairing…")

        def done(key: str) -> None:
            self.controller.settings.hue_key = key
            self.controller.store.save()
            self.status.setText("Paired. Press Test to see the lights change.")

        def failed(exc: Exception) -> None:
            self.status.setText(f"Could not pair: {exc}")

        run_async(lambda: smart_lights.pair_hue(host, request), done, failed)

    def test(self, lights: smart_lights.SmartLights | None = None) -> None:
        self.save()
        sender = lights or smart_lights.SmartLights(self.controller.settings)
        self.status.setText("Sending a colour…")
        run_async(
            lambda: sender.send(1.0, 0.85),
            lambda _r: self.status.setText("Sent: the lights should turn pink."),
            lambda exc: self.status.setText(f"No answer from the lights: {exc}"),
        )
