"""Settings → Process Songs: let this Desk's GPU separate songs and write lyrics for the rooms."""

from __future__ import annotations

import platform

from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ytktv.desk import processing
from ytktv.desk.store import DeskStore
from ytktv.ui.support import run_async


class ProcessingSettings(QFrame):
    def __init__(self, store: DeskStore) -> None:
        super().__init__()
        self.store = store
        self.setObjectName("panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        head = QLabel("PROCESS SONGS FOR THE ROOMS")
        head.setObjectName("panelHead")
        note = QLabel(
            "With a GPU here, this Desk removes the vocals and writes the lyrics of the songs"
            " every room has queued, so the rooms' own computers need no GPU. Each song is done"
            " once for all rooms. A room does it itself when the Desk is off or too busy."
            " Needs both downloads below; takes effect when YTKTV Desk is opened again."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.enabled = QCheckBox("Separate songs and write lyrics for the rooms on this computer")
        self.enabled.setChecked(store.setting(processing.SETTING, "0") == "1")
        self.enabled.toggled.connect(self.save)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.separation = QPushButton("Download Vocal Separation")
        self.separation.clicked.connect(self.install_separation)
        self.lyrics = QPushButton("Download AI Lyrics")
        self.lyrics.clicked.connect(self.install_lyrics)
        row = QHBoxLayout()
        row.addWidget(self.separation)
        row.addWidget(self.lyrics)
        row.addStretch()
        for widget in (head, note, self.enabled, self.status):
            column.addWidget(widget)
        column.addLayout(row)
        self.show_status()

    def save(self, on: bool) -> None:
        self.store.set_setting(processing.SETTING, "1" if on else "0")
        self.show_status()

    def show_status(self, text: str = "") -> None:
        self.status.setText(text or processing.runtimes_text())

    def install_separation(self) -> None:
        from ytktv.separation import runtime as separation_runtime

        def work() -> str:
            gpu = separation_runtime.detect_gpu()
            key = separation_runtime.choose_variant(platform.system(), gpu, platform.machine())
            return separation_runtime.Runtime().install_with_fallback(key)

        self._install(work)

    def install_lyrics(self) -> None:
        from ytktv import lyrics_ai

        self._install(lambda: lyrics_ai.install(lyrics_ai.runtime()))

    def _install(self, work: object) -> None:
        self.separation.setEnabled(False)
        self.lyrics.setEnabled(False)
        self.show_status("Downloading… (this takes a while)")

        def done(_result: object) -> None:
            self.separation.setEnabled(True)
            self.lyrics.setEnabled(True)
            self.show_status()

        def failed(exc: Exception) -> None:
            self.separation.setEnabled(True)
            self.lyrics.setEnabled(True)
            self.show_status(f"Could not download: {exc}"[:160])

        run_async(work, done, failed)  # type: ignore[arg-type]
