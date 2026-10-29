"""What a room's console shows while the front desk has it closed."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

ICON = Path(__file__).parent / "assets" / "icon.png"


class RoomClosed(QWidget):
    """Covers the whole console; only Settings stays reachable."""

    open_settings = Signal()

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("RoomClosed { background: #07040f; }")
        layout = QVBoxLayout(self)
        layout.addStretch()
        icon = QLabel()
        icon.setPixmap(
            QPixmap(str(ICON)).scaled(
                220,
                220,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message = QLabel("This room is closed")
        self.message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message.setStyleSheet("color: white; font-size: 30px; font-weight: 700;")
        self.detail = QLabel("Please ask at the front desk.")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail.setStyleSheet("color: #9a93b8; font-size: 16px;")
        layout.addWidget(icon)
        layout.addSpacing(24)
        layout.addWidget(self.message)
        layout.addWidget(self.detail)
        layout.addStretch()
        settings = QPushButton("Settings")
        settings.clicked.connect(self.open_settings.emit)
        layout.addWidget(settings, alignment=Qt.AlignmentFlag.AlignRight)
        self.hide()

    def cover(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
