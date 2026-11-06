"""Server Mode: the main Desk's computer shows a server console instead of the front desk.

Staff work on staff terminals; this screen shows that the server is up and what it is doing.
"""

from __future__ import annotations

import csv
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ytktv.config import data_dir
from ytktv.desk import awake, lock, staff
from ytktv.desk.metrics import Metrics, memory_mb, uptime_text
from ytktv.desk.server import Hub
from ytktv.desk.store import DeskStore
from ytktv.ui import backdrop

ONLINE_SECONDS = 120  # a staff terminal that called within this long counts as online
FILTERS = ("Everything", "Operations", "Rooms", "Songs", "Errors", "Server")
KINDS = {
    "Operations": "operation",
    "Rooms": "room",
    "Songs": "gpu",
    "Errors": "error",
    "Server": "server",
}

STYLE = """
#console QLabel { color: #f3eeff; }
#console QLabel#title { font-size: 30px; font-weight: 900; color: #ff3d9a; }
#console QLabel#running { font-size: 18px; font-weight: 800; color: #3dff9a; }
#console QLabel#facts { color: #b9b0d6; font-size: 14px; }
#console QFrame#card { background: rgba(23, 15, 46, 0.88); border: 1px solid #3a2a6a;
    border-radius: 16px; }
#console QLabel#cardHead { color: #2ee6ff; font-size: 13px; font-weight: 800;
    letter-spacing: 2px; }
#console QLabel#cardValue { font-size: 30px; font-weight: 900; }
#console QLabel#cardDetail { color: #b9b0d6; font-size: 13px; }
#console QListWidget { background: rgba(11, 7, 24, 0.9); color: #e6e0ff;
    border: 1px solid #3a2a6a; border-radius: 12px; font-family: Menlo, Consolas, monospace; }
"""


def day_start(now: float) -> float:
    return time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))


class ServerConsole(QMainWindow):
    def __init__(
        self,
        store: DeskStore,
        hub: Hub,
        metrics: Metrics,
        address: str,
        keep_awake: awake.KeepAwake | None = None,
        processor: Any = None,
    ) -> None:
        super().__init__()
        self.store, self.hub, self.metrics, self.address = store, hub, metrics, address
        self.processor = processor  # processing.SongProcessor while songs are done here
        self.keep_awake = keep_awake
        self.confirm_close = True
        self.setWindowTitle("YTKTV Desk · Server")
        self.resize(1280, 800)
        root = backdrop.Backdrop()
        root.setObjectName("console")
        root.setStyleSheet(STYLE)
        self.setCentralWidget(root)
        page = QVBoxLayout(root)
        page.setContentsMargins(32, 24, 32, 24)
        page.setSpacing(16)

        top = QHBoxLayout()
        heading = QVBoxLayout()
        self.title = QLabel()
        self.title.setObjectName("title")
        self.facts = QLabel()
        self.facts.setObjectName("facts")
        self.facts.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        heading.addWidget(self.title)
        heading.addWidget(self.facts)
        top.addLayout(heading, stretch=1)
        self.running = QLabel("●  RUNNING")
        self.running.setObjectName("running")
        top.addWidget(self.running, alignment=Qt.AlignmentFlag.AlignTop)
        page.addLayout(top)

        grid = QGridLayout()
        grid.setSpacing(14)
        self.values: dict[str, QLabel] = {}
        self.details: dict[str, QLabel] = {}
        cards = (
            ("rooms", "ROOMS ONLINE"),
            ("terminals", "STAFF TERMINALS"),
            ("requests", "REQUESTS / MIN"),
            ("machine", "THIS COMPUTER"),
            ("today", "TODAY"),
            ("gpu", "SONGS FOR ROOMS"),
        )
        for index, (key, head) in enumerate(cards):
            card = QFrame()
            card.setObjectName("card")
            box = QVBoxLayout(card)
            box.setContentsMargins(18, 14, 18, 14)
            label = QLabel(head)
            label.setObjectName("cardHead")
            value = QLabel("—")
            value.setObjectName("cardValue")
            detail = QLabel("")
            detail.setObjectName("cardDetail")
            detail.setWordWrap(True)
            for widget in (label, value, detail):
                box.addWidget(widget)
            box.addStretch()
            grid.addWidget(card, index // 3, index % 3)
            self.values[key], self.details[key] = value, detail
        page.addLayout(grid)

        bar = QHBoxLayout()
        log_head = QLabel("LIVE LOG")
        log_head.setObjectName("cardHead")
        self.filter = QComboBox()
        self.filter.addItems(FILTERS)
        self.filter.currentIndexChanged.connect(lambda _i: self.refresh())
        export = QPushButton("Export Log…")
        export.clicked.connect(lambda: self.export_log())
        bar.addWidget(log_head)
        bar.addStretch()
        bar.addWidget(self.filter)
        bar.addWidget(export)
        page.addLayout(bar)
        self.log = QListWidget()
        page.addWidget(self.log, stretch=1)

        buttons = QHBoxLayout()
        settings = QPushButton("⚙️  Settings")
        settings.clicked.connect(lambda: ConsoleSettings(self).exec())
        backup = QPushButton("💾  Back Up Now")
        backup.clicked.connect(lambda: self.backup_now(tell=True))
        lock_button = QPushButton("🔒  Lock")
        lock_button.clicked.connect(self._lock)
        lock_button.setEnabled(lock.has_password(store))
        buttons.addWidget(settings)
        buttons.addWidget(backup)
        buttons.addWidget(lock_button)
        buttons.addStretch()
        note = QLabel("Front-desk work happens on the staff terminals.")
        note.setObjectName("facts")
        buttons.addWidget(note)
        page.addLayout(buttons)

        self.lock_screen = lock.LockScreen(root, store)
        self.lock_screen.lock()
        self.lock_screen.activity()
        metrics.event("server", "Server Mode started")
        if keep_awake is not None:
            keep_awake.start()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()

    def _lock(self) -> None:
        self.lock_screen.lock()

    def name(self) -> str:
        return staff.machine_name(self.store)

    # -- what the screen shows ------------------------------------------------------

    def refresh(self) -> None:
        now = time.time()
        self.title.setText(f"{self.name()}  ·  Server")
        self.facts.setText(
            f"https://{self.address}   ·   fingerprint {self.store.fingerprint}"
            f"   ·   up {uptime_text(self.metrics.uptime())}"
        )
        rooms = self.store.rooms()
        online = self.hub.online()
        live = [r for r in rooms if r.room_id in online]
        self.values["rooms"].setText(f"{len(live)} / {len(rooms)}")
        in_use = sum(1 for r in rooms if r.is_open)
        offline = [r.name for r in rooms if r.room_id not in online]
        self.details["rooms"].setText(
            f"{in_use} in use"
            + (f" · offline: {', '.join(sorted(offline)[:6])}" if offline else " · all online")
        )
        terminals = self.store.terminals()
        here = [t for t in terminals if now - t.last_seen < ONLINE_SECONDS]
        self.values["terminals"].setText(f"{len(here)} / {len(terminals)}")
        self.details["terminals"].setText(
            ", ".join(sorted(t.name for t in here)) or "None online right now"
        )
        self.values["requests"].setText(str(self.metrics.per_minute()))
        errors = self.metrics.errors_last_hour()
        self.details["requests"].setText(f"{errors} refused or failed in the last hour")
        memory = memory_mb()
        self.values["machine"].setText(f"{self.metrics.cpu_percent():.0f}% CPU")
        file = Path(self.store.path)
        size = file.stat().st_size / 2**20 if file.is_file() else 0.0
        self.details["machine"].setText(
            (f"{memory:.0f} MB memory · " if memory is not None else "") + f"database {size:.1f} MB"
        )
        start = day_start(now)
        visits = self.store.history(start, start + 86400)
        takings = sum(v.total for v in visits)
        currency = self.store.setting("currency", "$")
        orders = [o for o in self.store.orders() if o.created >= start]
        self.values["today"].setText(f"{currency}{takings:,.2f}")
        self.details["today"].setText(
            f"{len(visits)} sessions closed · {in_use} open · {len(orders)} orders"
        )
        self._show_gpu()
        self.show_log(now)

    def _show_gpu(self) -> None:
        from ytktv.desk import processing

        state = processing.describe(self.processor)
        if not state["on"]:
            self.values["gpu"].setText("Off")
            self.details["gpu"].setText("Settings → Process Songs for the Rooms")
            return
        self.values["gpu"].setText(f"{state['queue']} queued")
        parts = [f"working on {state['active']}" if state["active"] else "idle"]
        if state["device"]:
            parts.append(state["device"])
        parts.append(f"cache {state['cache_mb'] / 1024:.1f} GB")
        if not state["lyrics"]:
            parts.append("AI lyrics not downloaded")
        self.details["gpu"].setText(" · ".join(parts))

    def rows(self, now: float) -> list[tuple[float, str, str]]:
        """(time, kind, text) for the log, newest first."""
        rows = [
            (e.at, "operation", f"{e.machine}: {e.action}")
            for e in self.store.oplog(now - 86400, now + 1)
        ]
        rows += [(e.at, e.kind, e.text) for e in self.metrics.events()]
        wanted = KINDS.get(self.filter.currentText())
        if wanted:
            rows = [row for row in rows if row[1] == wanted]
        return sorted(rows, key=lambda row: row[0], reverse=True)

    def show_log(self, now: float) -> None:
        lines = [
            f"{time.strftime('%m-%d %H:%M:%S', time.localtime(at))}  {kind.upper():<9}  {text}"
            for at, kind, text in self.rows(now)[:400]
        ]
        if lines != [self.log.item(i).text() for i in range(self.log.count())]:
            self.log.clear()
            self.log.addItems(lines)

    # -- actions --------------------------------------------------------------------

    def export_log(self, path: str | None = None) -> None:
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Log", "ytktv-desk-log.csv", "CSV (*.csv)"
            )
            if not path:
                return
        with open(path, "w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow(("Time", "Kind", "What"))
            for at, kind, text in self.rows(time.time()):
                writer.writerow((datetime.fromtimestamp(at).isoformat(" ", "seconds"), kind, text))

    def backup_now(self, folder: Path | None = None, tell: bool = False) -> Path:
        folder = folder or data_dir() / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"desk-{time.strftime('%Y%m%d-%H%M%S')}.sqlite3"
        self.store.backup(target)
        self.metrics.event("server", f"Backed up the records to {target}")
        if tell:
            QMessageBox.information(
                self, "Back Up Now", f"Saved a copy of every record to\n{target}"
            )
        self.refresh()
        return target

    def leave(self, password: str | None = None, confirm: bool = True) -> bool:
        """Turn Server Mode off; the Desk opens as a normal front desk next time."""
        if lock.has_password(self.store):
            if password is None:
                password, ok = QInputDialog.getText(
                    self, "Leave Server Mode", "Desk password:", QLineEdit.EchoMode.Password
                )
                if not ok:
                    return False
            if not lock.check(self.store, password):
                if confirm:
                    QMessageBox.warning(self, "Leave Server Mode", "Wrong password.")
                return False
        self.store.set_setting(staff.SERVER_MODE_SETTING, "0")
        self.store.log(self.name(), "Left Server Mode")
        if confirm:
            QMessageBox.information(
                self,
                "Leave Server Mode",
                "YTKTV Desk closes now. Open it again to use the front desk on this computer.",
            )
            self.confirm_close = False
            QApplication.quit()
        return True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt)
        if self.confirm_close:
            answer = QMessageBox.question(
                self,
                "Stop the server",
                "Closing this window stops the server: rooms and staff terminals lose the Desk"
                " until it is opened again. Close it?",
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self.timer.stop()
        if self.keep_awake is not None:
            self.keep_awake.stop()
        event.accept()


class ConsoleSettings(QDialog):
    """The settings a server needs: its name, starting with the computer, and leaving."""

    def __init__(
        self, console: ServerConsole, start_at_login: Callable[[bool], None] | None = None
    ) -> None:
        super().__init__(console)
        self.console = console
        self._start_at_login = start_at_login or awake.start_at_login
        self.setWindowTitle("Server Settings")
        column = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit(console.name())
        form.addRow("This Desk's name", self.name)
        column.addLayout(form)
        self.autostart = QCheckBox("Start YTKTV Desk when this computer starts")
        self.autostart.setChecked(awake.starts_at_login())
        column.addWidget(self.autostart)
        from ytktv.desk.processing_settings import ProcessingSettings

        column.addWidget(ProcessingSettings(console.store))
        row = QHBoxLayout()
        save = QPushButton("Save")
        save.setObjectName("accent")
        save.clicked.connect(self.save)
        leave = QPushButton("Leave Server Mode…")
        leave.clicked.connect(self.leave)
        row.addWidget(leave)
        row.addStretch()
        row.addWidget(save)
        column.addLayout(row)

    def leave(self) -> None:
        if self.console.leave():
            self.accept()

    def save(self) -> None:
        name = self.name.text().strip()
        store = self.console.store
        if name and name != staff.machine_name(store):
            store.set_setting(staff.NAME_SETTING, name)
            store.log(name, "Renamed this Desk")
        if self.autostart.isChecked() != awake.starts_at_login():
            self._start_at_login(self.autostart.isChecked())
        self.console.refresh()
        self.accept()


def enter_server_mode(
    parent: QWidget, store: DeskStore, password: str | None = None, confirm: bool = True
) -> bool:
    """Switch this Desk to Server Mode from Settings; it restarts into the console."""
    if lock.has_password(store):
        if password is None:
            password, ok = QInputDialog.getText(
                parent, "Server Mode", "Desk password:", QLineEdit.EchoMode.Password
            )
            if not ok:
                return False
        if not lock.check(store, password):
            if confirm:
                QMessageBox.warning(parent, "Server Mode", "Wrong password.")
            return False
    if confirm:
        answer = QMessageBox.question(
            parent,
            "Server Mode",
            "This computer will only run the server and show its console; staff work on the"
            " staff terminals. It stays in Server Mode until you leave it in the console's"
            " Settings. Switch now?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return False
    store.set_setting(staff.SERVER_SETTING, "1")
    store.set_setting(staff.SERVER_MODE_SETTING, "1")
    store.log(staff.machine_name(store), "Switched to Server Mode")
    if confirm:
        QMessageBox.information(
            parent, "Server Mode", "YTKTV Desk closes now. Open it again to start the server."
        )
        QApplication.quit()
    return True
