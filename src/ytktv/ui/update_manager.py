"""Glue between the updater and the UI: periodic checks, download, prompt."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QWidget

from ytktv import __version__, updater
from ytktv.config import cache_dir
from ytktv.core.controller import KTVController
from ytktv.core.models import PlayStatus
from ytktv.ui.support import run_async

log = logging.getLogger(__name__)


class UpdateManager(QObject):
    status = Signal(str, str)  # text, release page url ("" when none)

    def __init__(self, controller: KTVController, parent: QWidget) -> None:
        super().__init__(parent)
        self.controller = controller
        self._parent = parent
        self._installer: Path | None = None
        self._info: updater.UpdateInfo | None = None
        self._busy = False
        self._declined = False

        self._timer = QTimer(self)
        self._timer.setInterval(updater.CHECK_INTERVAL_SECONDS * 1000)
        self._timer.timeout.connect(self.check)
        self._timer.start()
        # Wait for a quiet moment (nothing playing, empty queue) before prompting.
        self._idle_timer = QTimer(self)
        self._idle_timer.setInterval(15_000)
        self._idle_timer.timeout.connect(self._prompt_when_idle)
        QTimer.singleShot(8_000, self.check)

    def check(self, manual: bool = False) -> None:
        if self._busy or not (manual or self.controller.settings.auto_update):
            return
        self._busy = True
        if manual:
            self._declined = False
            self.status.emit("Checking for updates...", "")

        def failed(exc: Exception) -> None:
            self._busy = False
            log.info("update check failed: %s", exc)
            if manual:
                self.status.emit(f"YTKTV {__version__}  ·  could not reach GitHub", "")

        run_async(updater.check_for_update, self._checked, failed)

    def _checked(self, info: updater.UpdateInfo | None) -> None:
        self._busy = False
        if info is None:
            self.status.emit(f"YTKTV {__version__}  ·  up to date", "")
            return
        self._info = info
        if not updater.can_self_install():
            self.status.emit(
                f"YTKTV {__version__}  ·  version {info.version} is available (git pull to update)",
                info.page_url,
            )
            return
        self.status.emit(f"Downloading YTKTV {info.version}...", info.page_url)
        self._busy = True

        def downloaded(path: Path) -> None:
            self._busy = False
            self._installer = path
            self.status.emit(f"YTKTV {info.version} is ready to install", info.page_url)
            self._idle_timer.start()
            self._prompt_when_idle()

        def failed(exc: Exception) -> None:
            self._busy = False
            log.warning("update download failed: %s", exc)
            self.status.emit(f"Could not download YTKTV {info.version}", info.page_url)

        run_async(
            lambda: updater.download_update(info, cache_dir() / "updates"), downloaded, failed
        )

    def _prompt_when_idle(self) -> None:
        if self._installer is None or self._info is None or self._declined:
            return
        controller = self.controller
        if controller.status != PlayStatus.IDLE or len(controller.queue) > 0:
            return
        self._idle_timer.stop()
        box = QMessageBox(self._parent)
        box.setWindowTitle("Update ready")
        box.setText(f"YTKTV {self._info.version} has been downloaded.")
        box.setInformativeText("Install it now? YTKTV will close and reopen after the update.")
        install = box.addButton("Install and Restart", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not install:
            self._declined = True  # ask again on the next launch
            return
        try:
            updater.install_update(self._installer)
        except Exception as exc:
            log.exception("could not start the installer")
            QMessageBox.warning(self._parent, "Update failed", str(exc))
            return
        QApplication.quit()
