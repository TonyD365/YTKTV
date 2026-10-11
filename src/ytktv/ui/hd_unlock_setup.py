"""Settings-page flow for downloading the HD unlock component."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from ytktv.core.controller import KTVController
from ytktv.ui.support import run_async
from ytktv.youtube.hd_unlock import DOWNLOAD_SIZE
from ytktv.youtube.search import YouTube

log = logging.getLogger(__name__)

_ABOUT = (
    'YouTube limits a few videos (mostly ones marked "made for kids") to 360p unless the '
    "request proves it comes from a real player."
)


class HdUnlockSetup(QObject):
    # text for the Settings card, label for its button ("" hides the button)
    status = Signal(str, str)
    _progress = Signal(str)

    def __init__(self, controller: KTVController, youtube: YouTube, parent: QWidget) -> None:
        super().__init__(parent)
        self.controller = controller
        self.youtube = youtube
        self._busy = False
        self._progress.connect(lambda line: self.status.emit(f"Installing...  {line}", ""))

    def publish(self) -> None:
        unlock = self.youtube.hd_unlock
        if unlock is None:
            return
        if unlock.installed():
            self.status.emit(
                "Installed. Restricted videos play in HD; they take a few seconds longer to "
                f"start.\n{_ABOUT}",
                "",
            )
        else:
            self.status.emit(
                f"Not installed. {_ABOUT}\nThis optional component ({DOWNLOAD_SIZE} to download, "
                "about 400 MB on disk) lets YTKTV do that, so those videos play in HD.",
                "Download and Install",
            )

    def install(self) -> None:
        unlock = self.youtube.hd_unlock
        if unlock is None or self._busy:
            return
        self._busy = True
        self.status.emit("Installing...", "")

        def done(_result: object) -> None:
            self._busy = False
            self.youtube.forget_limited()  # songs already in the queue get re-resolved in HD
            self.publish()
            self.controller.toast("HD unlock is ready")

        def failed(exc: Exception) -> None:
            self._busy = False
            log.warning("HD unlock install failed: %s", exc)
            reason = str(exc)[:300]
            self.status.emit(
                f"The download failed: {reason}\nCheck the internet connection and try again.",
                "Try Again",
            )

        run_async(lambda: unlock.install(self._progress.emit), done, failed)
