"""Settings → Staff Terminals: let other Desks work on this one, or work on another Desk."""

from __future__ import annotations

import contextlib
import socket
import time
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ytktv.desk import remote, staff
from ytktv.desk.store import CODE_SECONDS, DeskStore
from ytktv.rooms import discovery
from ytktv.ui.support import qr_pixmap, run_async


def _restart_note(parent: QWidget, text: str) -> None:
    QMessageBox.information(parent, "Restart YTKTV Desk", text)
    QApplication.quit()


class TerminalSettings(QFrame):
    """On the main Desk: its name, whether terminals may connect, and the paired ones.
    On a staff terminal: which Desk it works on, its own name, and disconnecting."""

    def __init__(self, store: DeskStore, address: str, main: remote.MainDesk | None = None) -> None:
        super().__init__()
        self.store, self.address, self.main = store, address, main
        self.phone_url = f"https://{address}/staff"
        self.setObjectName("panel")
        self.column = QVBoxLayout(self)
        self.column.setContentsMargins(24, 20, 24, 20)
        head = QLabel("STAFF TERMINALS")
        head.setObjectName("panelHead")
        self.column.addWidget(head)
        if main is None:
            self._main_desk()
        else:
            self._terminal(main)

    def _note(self, text: str) -> QLabel:
        note = QLabel(text)
        note.setObjectName("muted")
        note.setWordWrap(True)
        self.column.addWidget(note)
        return note

    # -- this Desk is the main one ------------------------------------------------

    def _main_desk(self) -> None:
        self._note(
            "Other computers running YTKTV Desk can work on this Desk's rooms as staff"
            " terminals: everything stays here, and the Log shows which machine did what."
        )
        form = QFormLayout()
        self.name = QLineEdit(staff.machine_name(self.store))
        self.name.editingFinished.connect(self.save_name)
        form.addRow("This Desk's name", self.name)
        self.column.addLayout(form)
        self.serving = QCheckBox("Let other Desks connect as staff terminals")
        self.serving.setChecked(self.store.setting(staff.SERVER_SETTING, "0") == "1")
        self.serving.toggled.connect(self.set_serving)
        self.column.addWidget(self.serving)
        phone_row = QHBoxLayout()
        qr = QLabel()
        qr.setPixmap(qr_pixmap(self.phone_url, 120))
        phone_row.addWidget(qr)
        phone_note = QLabel(
            f"Staff can use a phone too: open {self.phone_url} (accept the security warning"
            " once: the Desk's certificate is its own), then pair it with a code from Add"
            " Terminal. Phones see rooms, calls and orders, and can open and check out rooms."
        )
        phone_note.setWordWrap(True)
        phone_note.setObjectName("muted")
        phone_row.addWidget(phone_note, stretch=1)
        self.column.addLayout(phone_row)
        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        self.column.addWidget(self.list)
        buttons = QHBoxLayout()
        self.add_button = QPushButton("Add Terminal")
        self.add_button.clicked.connect(self.add_terminal)
        remove = QPushButton("Remove")
        remove.clicked.connect(self.remove_terminal)
        join = QPushButton("Make This Desk a Staff Terminal…")
        join.setToolTip("Work on another Desk's rooms instead of this one's")
        join.clicked.connect(lambda: ConnectDialog(self).exec())
        for button in (self.add_button, remove):
            buttons.addWidget(button)
        buttons.addStretch()
        buttons.addWidget(join)
        self.column.addLayout(buttons)
        self.load()

    def save_name(self) -> None:
        name = self.name.text().strip()
        if name and name != staff.machine_name(self.store):
            self.store.set_setting(staff.NAME_SETTING, name)

    def set_serving(self, on: bool) -> None:
        self.store.set_setting(staff.SERVER_SETTING, "1" if on else "0")
        self.add_button.setEnabled(on)

    def load(self) -> None:
        self.add_button.setEnabled(self.serving.isChecked())
        self.list.clear()
        for terminal in self.store.terminals():
            seen = time.strftime("%m-%d %H:%M", time.localtime(terminal.last_seen))
            item = QListWidgetItem(f"{terminal.name}  ·  last seen {seen}")
            item.setData(Qt.ItemDataRole.UserRole, terminal.terminal_id)
            self.list.addItem(item)

    def add_terminal(self, _checked: bool = False, show: bool = True) -> str:
        code = self.store.new_terminal_code()
        if show:
            QMessageBox.information(
                self,
                "Add a staff terminal",
                f"On the other computer open YTKTV Desk → Settings → Staff Terminals →"
                f" Make This Desk a Staff Terminal, pick this Desk ({self.address})"
                f" and enter\n\n{code}\n\nwithin {CODE_SECONDS // 60} minutes. Its screen will"
                f" show these pictures; they must match:\n\n{self.store.fingerprint}",
            )
            self.load()
        return code

    def remove_terminal(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.store.remove_terminal(str(item.data(Qt.ItemDataRole.UserRole)))
            self.load()

    # -- this Desk is a staff terminal -----------------------------------------

    def _terminal(self, main: remote.MainDesk) -> None:
        config = main.config
        self._note(
            f"This Desk is a staff terminal of {config.main_name or 'the main Desk'}"
            f" ({config.fingerprint}). The rooms, records and settings are that Desk's."
        )
        form = QFormLayout()
        self.name = QLineEdit(config.name)
        rename = QPushButton("Rename")
        rename.clicked.connect(self.rename_self)
        row = QHBoxLayout()
        row.addWidget(self.name)
        row.addWidget(rename)
        form.addRow("This terminal's name", row)
        self.column.addLayout(form)
        leave = QPushButton("Disconnect")
        leave.setToolTip("Stop being a staff terminal; this Desk uses its own rooms again")
        leave.clicked.connect(self.leave)
        self.column.addWidget(leave, alignment=Qt.AlignmentFlag.AlignLeft)

    def rename_self(self) -> None:
        assert self.main is not None
        name = self.name.text().strip()
        if name:
            self.main.call("terminal", "rename", name)
            self.main.config.name = name
            remote.save_config(self.main.config)

    def leave(self, _checked: bool = False, confirm: bool = True) -> None:
        if confirm:
            answer = QMessageBox.question(
                self, "Disconnect", "Stop working on the main Desk and use this Desk's own rooms?"
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        remote.forget_config()
        if confirm:
            _restart_note(self, "YTKTV Desk closes now. Open it again to use its own rooms.")


class ConnectDialog(QDialog):
    """Find the main Desk, enter its code, compare its pictures, and become its terminal."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Make This Desk a Staff Terminal")
        self.setMinimumWidth(460)
        column = QVBoxLayout(self)
        column.addWidget(QLabel("Desks on this network:"))
        self.found = QListWidget()
        self.found.currentItemChanged.connect(self._picked)
        column.addWidget(self.found)
        form = QFormLayout()
        self.address = QLineEdit()
        self.address.setPlaceholderText("or type its address, e.g. 192.168.1.20:8770")
        self.code = QLineEdit()
        self.code.setMaxLength(6)
        self.name = QLineEdit(socket.gethostname().split(".")[0])
        form.addRow("Address", self.address)
        form.addRow("Code", self.code)
        form.addRow("This terminal's name", self.name)
        column.addLayout(form)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        column.addWidget(self.status)
        buttons = QHBoxLayout()
        search = QPushButton("Search Again")
        search.clicked.connect(self.search)
        connect = QPushButton("Connect")
        connect.setObjectName("accent")
        connect.clicked.connect(lambda: self.join())
        buttons.addWidget(search)
        buttons.addStretch()
        buttons.addWidget(connect)
        column.addLayout(buttons)
        self.search()

    def search(self) -> None:
        self.status.setText("Looking for Desks…")
        run_async(lambda: discovery.browse(2.0), self._show_found, lambda _e: self._show_found([]))

    def _show_found(self, desks: list[discovery.FoundDesk]) -> None:
        # the dialog may have been closed while the search ran
        with contextlib.suppress(RuntimeError):
            self._list_found(desks)

    def _list_found(self, desks: list[discovery.FoundDesk]) -> None:
        self.found.clear()
        for desk in desks:
            item = QListWidgetItem(f"{desk.name}  ·  {desk.address}")
            item.setData(Qt.ItemDataRole.UserRole, desk.address)
            self.found.addItem(item)
        self.status.setText("" if desks else "No Desk answered. Type its address instead.")

    def _picked(self, item: QListWidgetItem | None) -> None:
        if item is not None:
            self.address.setText(str(item.data(Qt.ItemDataRole.UserRole)))

    def join(self, confirm: Callable[[remote.TerminalConfig], bool] | None = None) -> None:
        address, code = self.address.text().strip(), self.code.text().strip()
        if not address or not code:
            self.status.setText("Pick a Desk (or type its address) and enter its code.")
            return
        self.status.setText("Connecting…")

        def paired(config: remote.TerminalConfig) -> None:
            if not (confirm or self._compare)(config):
                self.status.setText("Not connected.")
                return
            remote.save_config(config)
            self.accept()
            if confirm is None:
                _restart_note(
                    self,
                    f"This Desk is now a staff terminal of {config.main_name}."
                    " YTKTV Desk closes now; open it again to start.",
                )

        def failed(exc: Exception) -> None:
            self.status.setText(f"Could not connect: {exc}")

        name = self.name.text().strip() or "Staff terminal"
        run_async(lambda: remote.pair(address, code, name), paired, failed)

    def _compare(self, config: remote.TerminalConfig) -> bool:
        answer = QMessageBox.question(
            self,
            "Is this the right Desk?",
            f"Does {config.main_name or 'the main Desk'} show these pictures?\n\n"
            f"{config.fingerprint}",
        )
        return answer == QMessageBox.StandardButton.Yes
