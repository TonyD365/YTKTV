"""Settings-page flow for downloading the HD unlock component."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from ytktv.core.controller import KTVController
from ytktv.i18n import N_, t
from ytktv.ui.support import run_async
from ytktv.youtube.hd_unlock import DOWNLOAD_SIZE
from ytktv.youtube.search import YouTube

log = logging.getLogger(__name__)

_ABOUT = N_(
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
        self._progress.connect(
            lambda line: self.status.emit(t("Installing...  {line}", line=line), "")
        )

    def publish(self) -> None:
        unlock = self.youtube.hd_unlock
        if unlock is None:
            return
        if unlock.installed():
            self.status.emit(
                t(
                    "Installed. Restricted videos play in HD; they take a few seconds "
                    "longer to start.\n{about}",
                    about=_ABOUT,
                ),
                "",
            )
        else:
            self.status.emit(
                t(
                    "Not installed. {about}\nThis optional component ({download_size} to "
                    "download, about 400 MB on disk) lets YTKTV do that, so those videos "
                    "play in HD.",
                    about=_ABOUT,
                    download_size=DOWNLOAD_SIZE,
                ),
                t("Download and Install"),
            )

    def install(self) -> None:
        unlock = self.youtube.hd_unlock
        if unlock is None or self._busy:
            return
        self._busy = True
        self.status.emit(t("Installing..."), "")

        def done(_result: object) -> None:
            self._busy = False
            self.youtube.forget_limited()  # songs already in the queue get re-resolved in HD
            self.publish()
            self.controller.toast(t("HD unlock is ready"))

        def failed(exc: Exception) -> None:
            self._busy = False
            log.warning("HD unlock install failed: %s", exc)
            reason = str(exc)[:300]
            self.status.emit(
                t(
                    "The download failed: {reason}\nCheck the internet connection and try again.",
                    reason=reason,
                ),
                t("Try Again"),
            )

        run_async(lambda: unlock.install(self._progress.emit), done, failed)
