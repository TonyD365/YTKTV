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
from ytktv.i18n import t
from ytktv.ui.support import run_async

log = logging.getLogger(__name__)


class UpdateManager(QObject):
    status = Signal(str, str)  # text, release page url ("" when none)
    ready = Signal(bool)  # an installer is downloaded and can be installed now

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
        if updater.can_self_install():
            # Installers of versions already installed are just taking up space.
            run_async(
                lambda: updater.clean_old_downloads(cache_dir() / "updates"), lambda _freed: None
            )

    def check(self, manual: bool = False) -> None:
        if self._busy or not (manual or self.controller.settings.auto_update):
            return
        self._busy = True
        if manual:
            self._declined = False
            self.status.emit(t("Checking for updates..."), "")

        def failed(exc: Exception) -> None:
            self._busy = False
            log.info("update check failed: %s", exc)
            if manual:
                self.status.emit(
                    t("YTKTV {version}  ·  could not reach GitHub", version=__version__), ""
                )

        run_async(updater.check_for_update, self._checked, failed)

    def _checked(self, info: updater.UpdateInfo | None) -> None:
        self._busy = False
        if info is None:
            self.status.emit(t("YTKTV {version}  ·  up to date", version=__version__), "")
            return
        self._info = info
        if not updater.can_self_install():
            self.status.emit(
                t(
                    "YTKTV {version}  ·  version {version2} is available (git pull to update)",
                    version=__version__,
                    version2=info.version,
                ),
                info.page_url,
            )
            return
        size = updater.size_label(info, cache_dir() / "updates")
        self.status.emit(
            t("Downloading YTKTV {version}{size}...", version=info.version, size=size),
            info.page_url,
        )
        self._busy = True

        def downloaded(path: Path) -> None:
            self._busy = False
            self._installer = path
            self.status.emit(
                t("YTKTV {version} is ready to install", version=info.version), info.page_url
            )
            self.ready.emit(True)
            self._idle_timer.start()
            self._prompt_when_idle()

        def failed(exc: Exception) -> None:
            self._busy = False
            log.warning("update download failed: %s", exc)
            self.status.emit(
                t("Could not download YTKTV {version}", version=info.version), info.page_url
            )

        run_async(
            lambda: updater.download_update(info, cache_dir() / "updates"), downloaded, failed
        )

    def install_now(self) -> None:
        """The user asked for the update from Settings: offer it even mid-song."""
        if self._installer is None or self._info is None:
            return
        self._declined = False
        self._prompt(interrupting=self.controller.status != PlayStatus.IDLE)

    def _prompt_when_idle(self) -> None:
        if self._installer is None or self._info is None or self._declined:
            return
        controller = self.controller
        if controller.status != PlayStatus.IDLE or len(controller.queue) > 0:
            return
        self._prompt(interrupting=False)

    def _prompt(self, interrupting: bool) -> None:
        if self._installer is None or self._info is None:
            return
        self._idle_timer.stop()
        box = QMessageBox(self._parent)
        box.setWindowTitle(t("Update ready"))
        box.setText(t("YTKTV {version} has been downloaded.", version=self._info.version))
        detail = t("Install it now? YTKTV will close and reopen after the update.")
        if updater.password_needed(self._installer):
            detail += "\n\n" + updater.PASSWORD_NOTE.format(app="YTKTV")
        if interrupting:
            detail += t("\n\nThe song that is playing will stop and the queue will be lost.")
        box.setInformativeText(detail)
        install = box.addButton(t("Install and Restart"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(t("Later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not install:
            # Do not ask again by ourselves this session; Settings still offers it.
            self._declined = True
            return
        try:
            updater.install_update(self._installer)
        except Exception as exc:
            log.exception("could not start the installer")
            QMessageBox.warning(self._parent, t("Update failed"), str(exc))
            return
        QApplication.quit()
