"""Keeps YTKTV Desk up to date from the GitHub releases, like YTKTV itself."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from ytktv import updater
from ytktv.config import cache_dir
from ytktv.ui.support import run_async

log = logging.getLogger(__name__)
APP = "YTKTV-Desk"
CHECK_EVERY = 6 * 3600 * 1000


class DeskUpdater(QObject):
    """Checks at start and every six hours; downloads quietly; offers to install.

    *automatic* says whether those timed checks run; a check asked for by hand always does.
    """

    ready = Signal(str)  # the new version, once its installer is downloaded and verified
    available = Signal(str, str)  # version, release page: found, but this build cannot install
    status = Signal(str)  # what the last check found, for the settings page

    def __init__(
        self, parent: QObject | None = None, automatic: Callable[[], bool] = lambda: True
    ) -> None:
        super().__init__(parent)
        self.installer: Path | None = None
        self.automatic = automatic
        self._busy = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._timed_check)
        self._timer.start(CHECK_EVERY)
        QTimer.singleShot(5000, self._timed_check)

    def _timed_check(self) -> None:
        if self.automatic():
            self.check()

    def check(self) -> None:
        if self.installer is not None:
            self.status.emit("The update is downloaded: press Update at the top to install it.")
            return
        if self._busy:
            return
        self._busy = True
        self.status.emit("Checking…")

        def found(info: updater.UpdateInfo | None) -> None:
            if info is None:
                self._busy = False
                self.status.emit("YTKTV Desk is up to date.")
                return
            if not updater.can_self_install():
                self._busy = False
                self.status.emit(f"Version {info.version} is out.")
                self.available.emit(info.version, info.page_url)
                return
            self.status.emit(f"Downloading version {info.version}…")
            run_async(
                lambda: updater.download_update(info, cache_dir() / "desk-updates"),
                lambda path: self._downloaded(path, info.version),
                self._failed,
            )

        run_async(lambda: updater.check_for_update(app=APP), found, self._failed)

    def _downloaded(self, path: Path, version: str) -> None:
        self._busy = False
        self.installer = path
        self.status.emit(f"Version {version} is ready to install.")
        self.ready.emit(version)

    def _failed(self, exc: Exception) -> None:
        self._busy = False
        self.status.emit("Could not check for updates (no internet?).")
        log.info("desk update check failed: %s", exc)

    def install(self) -> bool:
        """Start the installer; the caller quits the desk right after."""
        if self.installer is None:
            return False
        updater.install_update(self.installer)
        return True
