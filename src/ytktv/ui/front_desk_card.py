"""The Front Desk card in Settings: bind this machine to a YTKTV Desk as a room."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ytktv.config import SettingsStore
from ytktv.rooms import binding, discovery
from ytktv.rooms.client import RoomClient


class FrontDeskCard(QFrame):
    def __init__(self, store: SettingsStore, client: RoomClient | None = None) -> None:
        super().__init__()
        self.store = store
        self.client = client
        self.setObjectName("settingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        head = QLabel("FRONT DESK")
        head.setObjectName("settingsHead")
        layout.addWidget(head)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        self.form = QWidget()
        form = QVBoxLayout(self.form)
        form.setContentsMargins(0, 0, 0, 0)
        found_row = QHBoxLayout()
        self.found = QComboBox()
        self.found.setPlaceholderText("Desks on this network")
        self.found.currentIndexChanged.connect(self._pick_found)
        search = QPushButton("Find Desks")
        search.clicked.connect(self.find_desks)
        found_row.addWidget(self.found, stretch=1)
        found_row.addWidget(search)
        form.addLayout(found_row)
        self.address = QLineEdit()
        self.address.setPlaceholderText("…or type its address, e.g. 192.168.1.10:8770")
        self.code = QLineEdit()
        self.code.setPlaceholderText("6-digit code shown on the desk")
        self.code.setMaxLength(6)
        self.name = QLineEdit()
        self.name.setPlaceholderText("Room name, e.g. Kids' Room")
        bind = QPushButton("Bind")
        bind.setObjectName("accent")
        bind.clicked.connect(self.bind)
        for widget in (self.address, self.code, self.name):
            form.addWidget(widget)
        form.addWidget(bind)
        layout.addWidget(self.form)

        row = QHBoxLayout()
        self.unbind_button = QPushButton("Unbind")
        self.unbind_button.clicked.connect(self.unbind)
        self.unbind_note = QLabel()
        self.unbind_note.setObjectName("muted")
        self.unbind_note.setWordWrap(True)
        row.addWidget(self.unbind_button)
        row.addWidget(self.unbind_note, stretch=1)
        self.bound_row = QWidget()
        self.bound_row.setLayout(row)
        layout.addWidget(self.bound_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        self.refresh()

    def refresh(self) -> None:
        settings = self.store.settings
        bound = binding.is_bound(settings)
        self.form.setVisible(not bound)
        self.bound_row.setVisible(bound)
        if not bound:
            self.status.setText(
                "This machine is stand-alone. Bind it to a YTKTV Desk to run it as a room."
            )
            return
        online = self.client is not None and self.client.online
        self.status.setText(
            f"Room “{settings.room_name}” · bound to {settings.desk_url} · "
            + ("🟢 Connected" if online else "🔴 Desk offline")
        )
        allowed = binding.can_unbind(settings)
        self.unbind_button.setEnabled(allowed)
        if allowed:
            self.unbind_note.setText("The desk has been offline for 7 days, so you may unbind.")
        else:
            days = max(0.0, (time.time() - settings.desk_last_seen) / 86400)
            self.unbind_note.setText(
                "Bound to the front desk. Unbind it from the desk, or here after the desk"
                f" has been offline for 7 days ({days:.0f} so far)."
            )

    def find_desks(self) -> None:
        self.found.clear()
        try:
            desks = discovery.browse(2.0)
        except Exception:
            desks = []
        for desk in desks:
            self.found.addItem(f"{desk.name} · {desk.address}", desk.address)
        if not desks:
            self.found.setPlaceholderText("No desk found. Type its address below.")

    def _pick_found(self, index: int) -> None:
        if index >= 0:
            self.address.setText(str(self.found.itemData(index)))

    def bind(self) -> None:
        try:
            pairing = binding.request(self.address.text(), self.code.text(), self.name.text())
        except Exception as exc:
            QMessageBox.warning(self, "Could not bind", f"Check the address and code.\n\n{exc}")
            return
        answer = QMessageBox.question(
            self,
            "Check the security code",
            f"Does the front desk show these four pictures?\n\n{pairing.fingerprint}\n\n"
            "Only press Yes if they match exactly.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        binding.apply(self.store.settings, pairing)
        self.store.save()
        if self.client is not None:
            self.client.start()
        self.code.clear()
        self.refresh()

    def unbind(self) -> None:
        if binding.can_unbind(self.store.settings):
            binding.clear(self.store.settings)
            self.store.save()
            self.refresh()
