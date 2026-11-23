"""The Staff Terminal card in Settings: bind this machine to a YTKTV Desk as a room."""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
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
from ytktv.i18n import t
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
        head = QLabel(t("STAFF TERMINAL"))
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
        self.found.setPlaceholderText(t("Desks on this network"))
        self.found.currentIndexChanged.connect(self._pick_found)
        search = QPushButton(t("Find Desks"))
        search.clicked.connect(self.find_desks)
        found_row.addWidget(self.found, stretch=1)
        found_row.addWidget(search)
        form.addLayout(found_row)
        self.address = QLineEdit()
        self.address.setPlaceholderText(t("…or type its address, e.g. 192.168.1.10:8770"))
        self.code = QLineEdit()
        self.code.setPlaceholderText(t("6-digit code shown on the desk"))
        self.code.setMaxLength(6)
        self.name = QLineEdit()
        self.name.setPlaceholderText(t("Room name, e.g. Kids' Room"))
        bind = QPushButton(t("Bind"))
        bind.setObjectName("accent")
        bind.clicked.connect(self.bind)
        for widget in (self.address, self.code, self.name):
            form.addWidget(widget)
        form.addWidget(bind)
        layout.addWidget(self.form)

        row = QHBoxLayout()
        self.unbind_button = QPushButton(t("Unbind"))
        self.unbind_button.clicked.connect(self.unbind)
        self.unbind_note = QLabel()
        self.unbind_note.setObjectName("muted")
        self.unbind_note.setWordWrap(True)
        row.addWidget(self.unbind_button)
        row.addWidget(self.unbind_note, stretch=1)
        self.bound_row = QWidget()
        self.bound_row.setLayout(row)
        layout.addWidget(self.bound_row)
        self.on_desk = QCheckBox(
            t(
                "Process songs on the Desk when it offers (vocal separation and AI lyrics on its"
                " GPU; this computer does them when the Desk cannot)"
            )
        )
        self.on_desk.setChecked(store.settings.process_on_desk)
        self.on_desk.toggled.connect(self._set_on_desk)
        layout.addWidget(self.on_desk)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(2000)
        self.refresh()

    def _set_on_desk(self, on: bool) -> None:
        self.store.settings.process_on_desk = on
        self.store.save()

    def refresh(self) -> None:
        settings = self.store.settings
        bound = binding.is_bound(settings)
        self.form.setVisible(not bound)
        self.bound_row.setVisible(bound)
        self.on_desk.setVisible(bound)
        if not bound:
            self.status.setText(
                t("This machine is stand-alone. Bind it to a YTKTV Desk to run it as a room.")
            )
            return
        online = self.client is not None and self.client.online
        self.status.setText(
            t(
                "Room “{room_name}” · bound to {desk_url} · ",
                room_name=settings.room_name,
                desk_url=settings.desk_url,
            )
            + (t("🟢 Connected") if online else t("🔴 Desk offline"))
        )
        allowed = binding.can_unbind(settings)
        self.unbind_button.setEnabled(allowed)
        if allowed:
            self.unbind_note.setText(t("The desk has been offline for 7 days, so you may unbind."))
        else:
            days = max(0.0, (time.time() - settings.desk_last_seen) / 86400)
            self.unbind_note.setText(
                t(
                    "Bound to the staff terminal. Unbind it from the desk, or here after "
                    "the desk has been offline for 7 days ({days:.0f} so far).",
                    days=days,
                )
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
            self.found.setPlaceholderText(t("No desk found. Type its address below."))

    def _pick_found(self, index: int) -> None:
        if index >= 0:
            self.address.setText(str(self.found.itemData(index)))

    def bind(self) -> None:
        try:
            pairing = binding.request(self.address.text(), self.code.text(), self.name.text())
        except Exception as exc:
            QMessageBox.warning(
                self, t("Could not bind"), t("Check the address and code.\n\n{exc}", exc=exc)
            )
            return
        answer = QMessageBox.question(
            self,
            t("Check the security code"),
            t(
                "Does the staff terminal show these four pictures?\n\n{fingerprint}\n\n"
                "Only press Yes if they match exactly.",
                fingerprint=pairing.fingerprint,
            ),
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
