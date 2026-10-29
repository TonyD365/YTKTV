"""First-run download of the separation runtime (packaged Windows / Linux builds)."""

from __future__ import annotations

import logging
import platform
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QMessageBox, QWidget

from ytktv.core.controller import KTVController
from ytktv.separation.runtime import VARIANTS, Gpu, Runtime, choose_variant, detect_gpu
from ytktv.ui.support import run_async

log = logging.getLogger(__name__)


class SeparationSetup(QObject):
    # text for the Settings card, label for its button ("" hides the button)
    status = Signal(str, str)
    _progress = Signal(str)

    def __init__(
        self,
        controller: KTVController,
        runtime: Runtime,
        parent: QWidget,
        make_separator: Callable[[], Any],
        on_ready: Callable[[Any], None],
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.runtime = runtime
        self._parent = parent
        self._make_separator = make_separator
        self._on_ready = on_ready
        self._gpu: Gpu | None = None
        self._recommended = "cpu"
        self._busy = False
        self._progress.connect(lambda line: self.status.emit(f"Installing...  {line}", ""))

    def start(self) -> None:
        """Detect the hardware in the background, then offer the download if needed."""
        self.status.emit("Checking the graphics hardware...", "")
        run_async(detect_gpu, self._detected, lambda _exc: self._detected(None))

    def _detected(self, gpu: Gpu | None) -> None:
        self._gpu = gpu
        self._recommended = choose_variant(platform.system(), gpu, platform.machine())
        self._publish()
        installed = self.runtime.installed_variant()
        declined = self.controller.settings.separation_declined
        if (
            installed != self._recommended
            and declined != self._recommended
            and (installed is None or self._recommended != "cpu")
        ):
            # Let the window settle before a dialog appears on top of it.
            QTimer.singleShot(1500, self._prompt)

    def _hardware(self) -> str:
        return self._gpu.name if self._gpu else "no supported graphics card"

    def _publish(self) -> None:
        installed = self.runtime.installed_variant()
        wanted = VARIANTS[self._recommended]
        if installed is None:
            self.status.emit(
                f"Not installed yet. Detected: {self._hardware()}.\n"
                f"The {wanted.title} runtime is a one-time download of {wanted.download_size}.",
                "Download and Install",
            )
        elif installed != self._recommended and self._recommended != "cpu":
            self.status.emit(
                f"Installed: {VARIANTS[installed].title}. Detected: {self._hardware()}.\n"
                f"The {wanted.title} runtime ({wanted.download_size}) would be much faster.",
                f"Switch to {wanted.title}",
            )
        else:
            self.status.emit("", "")  # installed and optimal: the normal text applies

    def _prompt(self) -> None:
        if self._busy:
            return
        wanted = VARIANTS[self._recommended]
        installed = self.runtime.installed_variant()
        box = QMessageBox(self._parent)
        box.setWindowTitle("Vocal separation")
        if installed is None:
            box.setText("Download the vocal separation runtime?")
            detail = "Original / Instrumental switching needs an extra component."
        else:
            box.setText("Use your graphics card for vocal separation?")
            detail = "Songs are prepared many times faster on the GPU."
        box.setInformativeText(
            f"{detail}\n\nDetected: {self._hardware()}\n"
            f"Download: {wanted.title} runtime, {wanted.download_size}.\n\n"
            "You can also do this later from Settings."
        )
        accept = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is accept:
            self.install_recommended()
        else:
            self.controller.settings.separation_declined = self._recommended
            self.controller.mixer_changed()

    def install_recommended(self) -> None:
        if self._busy:
            return
        self._busy = True
        key = self._recommended
        self.status.emit(f"Installing the {VARIANTS[key].title} runtime...", "")

        def done(installed: str) -> None:
            self._busy = False
            self.controller.settings.separation_declined = ""
            self.controller.mixer_changed()
            if installed != key:
                self._recommended = installed  # the GPU build did not install; stop offering it
            self._publish()
            self.controller.toast("Vocal separation is ready")
            self._on_ready(self._make_separator())

        def failed(exc: Exception) -> None:
            self._busy = False
            log.warning("separation runtime install failed: %s", exc)
            reason = str(exc)[:300]
            self.status.emit(
                f"The download failed: {reason}\nCheck the internet connection and try again.",
                "Try Again",
            )

        run_async(
            lambda: self.runtime.install_with_fallback(key, self._progress.emit), done, failed
        )
