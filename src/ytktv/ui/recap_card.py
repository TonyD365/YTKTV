"""The card a closed room's TV shows: what the session sang, and a QR code to keep it."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ytktv.core import recap
from ytktv.ui.support import qr_pixmap


class RecapCard(QWidget):
    """Neon-edged summary in the middle of the black closed screen."""

    def __init__(self, parent: QWidget, summary: dict[str, Any], url: str) -> None:
        super().__init__(parent)
        self.url = url
        self.setObjectName("recapCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#recapCard { background: #120a24; border: 2px solid #ff4fd8; border-radius: 24px; }"
            " QLabel { background: transparent; color: white; }"
        )
        outer = QHBoxLayout(self)
        outer.setContentsMargins(48, 40, 48, 40)
        outer.setSpacing(48)
        text = QVBoxLayout()
        title = QLabel("Thanks for singing!")
        title.setStyleSheet("color: #ff4fd8; font-size: 40px; font-weight: 800;")
        text.addWidget(title)
        text.addSpacing(16)
        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(12)
        self.rows = recap.lines(summary)
        for row, (label, value) in enumerate(self.rows):
            name = QLabel(label)
            name.setStyleSheet("color: #9a93b8; font-size: 22px;")
            shown = QLabel(value)
            shown.setStyleSheet("font-size: 24px; font-weight: 700;")
            shown.setWordWrap(True)
            grid.addWidget(name, row, 0)
            grid.addWidget(shown, row, 1)
        text.addLayout(grid)
        text.addStretch()
        outer.addLayout(text, 1)
        side = QVBoxLayout()
        self.qr = QLabel()
        self.qr.setPixmap(qr_pixmap(url, 220))
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Scan to keep tonight's recap")
        hint.setStyleSheet("color: #4ff0ff; font-size: 18px;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        side.addStretch()
        side.addWidget(self.qr)
        side.addWidget(hint)
        side.addStretch()
        outer.addLayout(side)

    def place(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        w, h = parent.width(), parent.height()
        width, height = min(w - 40, max(760, int(w * 0.62))), min(h - 40, max(420, int(h * 0.5)))
        self.setGeometry((w - width) // 2, (h - height) // 2, max(1, width), max(1, height))
