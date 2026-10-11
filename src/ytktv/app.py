"""Application wiring: build every component and run the Qt event loop."""

from __future__ import annotations

import argparse
import logging
import platform
import signal
import socket
import sys
import threading
from pathlib import Path
from typing import Any

from ytktv import __version__, bootstrap
from ytktv.config import SettingsStore, cache_dir, data_dir
from ytktv.core.controller import KTVController
from ytktv.core.events import EventBus
from ytktv.core.library import Library
from ytktv.player.fake import FakePlayer
from ytktv.youtube.search import YouTube

log = logging.getLogger("ytktv")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="ytktv", description="Turn this computer into a KTV machine."
    )
    parser.add_argument("--version", action="version", version=f"YTKTV {__version__}")
    parser.add_argument(
        "--port", type=int, help="port for the phone remote (default: saved setting)"
    )
    parser.add_argument("--no-mic", action="store_true", help="start without the microphone mixer")
    parser.add_argument("--windowed", action="store_true", help="keep the MV screen in a window")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    return parser.parse_args(argv)


def free_port(preferred: int) -> int:
    """Return *preferred* if it can be bound, else the next free port after it."""
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    return preferred


def _ensure_libmpv(app: Any) -> bool:
    """Find libmpv, offering to install it when missing. Returns True if usable."""
    from PySide6.QtWidgets import QMessageBox, QProgressDialog

    if bootstrap.find_libmpv():
        return True
    plan = bootstrap.install_plan()
    if plan is None:
        QMessageBox.warning(
            None,
            "mpv is required",
            "YTKTV plays video with mpv (libmpv), which was not found and cannot be installed "
            "automatically on this system.\n\nInstall mpv with your package manager "
            "(macOS: install Homebrew, then 'brew install mpv') and start YTKTV again.",
        )
        return False
    answer = QMessageBox.question(
        None,
        "Install mpv?",
        "YTKTV plays video with mpv (libmpv), which is not installed yet.\n\n"
        f"Install it now?\n\n{plan}",
    )
    if answer != QMessageBox.StandardButton.Yes:
        return False

    dialog = QProgressDialog("Installing mpv...", "", 0, 0)
    dialog.setCancelButton(None)
    dialog.setWindowTitle("YTKTV")
    dialog.setMinimumDuration(0)
    dialog.show()
    result: dict[str, bool] = {}
    worker = threading.Thread(
        target=lambda: result.update(ok=bootstrap.install_libmpv(lambda msg: log.info(msg))),
        daemon=True,
    )
    worker.start()
    while worker.is_alive():
        app.processEvents()
        worker.join(0.05)
    dialog.close()
    if not result.get("ok"):
        QMessageBox.warning(
            None, "Installation failed", f"Could not install mpv. Try manually:\n\n{plan}"
        )
    return bool(result.get("ok"))


def _build_stems(youtube: YouTube, settings: Any, ffmpeg: str | None) -> Any:
    from ytktv.separation.base import separation_installed

    if not separation_installed():
        return None
    from ytktv.separation.cache import StemCache
    from ytktv.separation.uvr import UvrSeparator
    from ytktv.separation.worker import StemManager

    root = cache_dir() / "stems"
    cache = StemCache(root, int(settings.stem_cache_gb * 1024**3))
    separator = UvrSeparator(
        settings.separation_model, data_dir() / "models", cache_dir() / "separator"
    )

    def download(video_id: str, dest: Path) -> Path:
        return youtube.download_audio(video_id, dest, ffmpeg=ffmpeg)

    manager = StemManager(cache, separator, download)
    manager.start()
    return manager


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QSurfaceFormat
    from PySide6.QtWidgets import QApplication

    if platform.system() == "Darwin":
        # macOS only hands out a modern OpenGL context when asked for a core profile.
        fmt = QSurfaceFormat()
        fmt.setVersion(4, 1)
        fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
        QSurfaceFormat.setDefaultFormat(fmt)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("YTKTV")
    app.setApplicationVersion(__version__)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from ytktv.ui import theme

    app.setStyleSheet(theme.STYLESHEET)

    have_mpv = _ensure_libmpv(app)
    ffmpeg = bootstrap.ensure_ffmpeg()

    store = SettingsStore()
    settings = store.settings

    player: Any
    if have_mpv:
        from ytktv.player.mpv_player import MpvPlayer

        try:
            player = MpvPlayer()
        except Exception:
            log.exception("libmpv could not be loaded")
            player, have_mpv = FakePlayer(), False
    else:
        player = FakePlayer()

    youtube = YouTube()
    bus = EventBus()
    audio = None
    if not args.no_mic:
        from ytktv.audio.engine import AudioEngine

        audio = AudioEngine(settings)
        audio.start()

    controller = KTVController(
        store,
        player,
        youtube,
        library=Library(data_dir() / "library.json"),
        bus=bus,
        stems=_build_stems(youtube, settings, ffmpeg),
        audio=audio,
    )

    def detect() -> None:
        from ytktv.separation.base import detect_accelerator

        controller.accelerator = detect_accelerator().label
        bus.emit("state", None)

    threading.Thread(target=detect, name="ytktv-detect", daemon=True).start()

    from ytktv.server.app import ServerThread, create_app

    server = ServerThread(
        create_app(controller, youtube), free_port(args.port or settings.server_port)
    )
    server.start()
    log.info("phone remote: %s", server.url)

    from ytktv.ui.main_window import MainWindow
    from ytktv.ui.mv_window import MvWindow
    from ytktv.ui.update_manager import UpdateManager

    mv_window = MvWindow(player if have_mpv else None)
    window = MainWindow(controller, youtube, mv_window, server.url, force_windowed=args.windowed)
    updates = UpdateManager(controller, window)
    updates.status.connect(window.settings_page.set_update_status)
    window.settings_page.check_updates.connect(lambda: updates.check(manual=True))
    window.show()
    window.place_mv()
    if not have_mpv:
        window.show_toast("Video playback is unavailable: mpv is not installed.", error=True)

    def shutdown() -> None:
        server.stop()
        mv_window.release()
        controller.close()

    app.aboutToQuit.connect(shutdown)
    return int(app.exec())
