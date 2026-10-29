"""The desk's optional password, and the screen that asks for it."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from ytktv.desk.store import DeskStore

LOCK_AFTER = {"Never": 0, "5 minutes": 5, "15 minutes": 15, "30 minutes": 30}


def _digest(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


def set_password(store: DeskStore, password: str | None) -> None:
    """Turn the password on (with *password*) or off (None)."""
    if not password:
        store.set_setting("password", "")
        return
    salt = secrets.token_hex(16)
    store.set_setting("password", f"{salt}:{_digest(password, salt)}")


def has_password(store: DeskStore) -> bool:
    return bool(store.setting("password"))


def check(store: DeskStore, password: str) -> bool:
    saved = store.setting("password")
    if not saved:
        return True
    salt, digest = saved.split(":", 1)
    return hmac.compare_digest(_digest(password, salt), digest)


class LockScreen(QWidget):
    """Covers the desk until the password is typed; locks itself again when idle."""

    def __init__(self, parent: QWidget, store: DeskStore) -> None:
        super().__init__(parent)
        self.store = store
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("LockScreen { background: #07040f; }")
        column = QVBoxLayout(self)
        column.addStretch()
        title = QLabel("🔒  YTKTV Front Desk is locked")
        title.setStyleSheet("color: white; font-size: 28px; font-weight: 800;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.setPlaceholderText("Password")
        self.password.setFixedWidth(320)
        self.password.returnPressed.connect(self.try_unlock)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #ff6b8b;")
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        unlock = QPushButton("Unlock")
        unlock.setObjectName("accent")
        unlock.clicked.connect(self.try_unlock)
        column.addWidget(title)
        column.addSpacing(18)
        column.addWidget(self.password, alignment=Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.error)
        column.addWidget(unlock, alignment=Qt.AlignmentFlag.AlignCenter)
        column.addStretch()
        self.hide()
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self.lock)
        parent.installEventFilter(self)

    def lock(self) -> None:
        if not has_password(self.store):
            return
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.password.clear()
        self.error.clear()
        self.show()
        self.raise_()
        self.password.setFocus()

    def try_unlock(self) -> None:
        if check(self.store, self.password.text()):
            self.hide()
            self.activity()
        else:
            self.error.setText("Wrong password")
            self.password.selectAll()

    def activity(self) -> None:
        """Restart the idle countdown (called on every key press and click)."""
        minutes = LOCK_AFTER.get(self.store.setting("lock_after", "Never"), 0)
        if minutes and has_password(self.store) and not self.isVisible():
            self._idle.start(minutes * 60 * 1000)
        else:
            self._idle.stop()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress):
            self.activity()
        elif event.type() == QEvent.Type.Resize and self.isVisible():
            parent = self.parentWidget()
            if parent is not None:
                self.setGeometry(parent.rect())
        return False
