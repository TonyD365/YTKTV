"""Application wiring: build every component and run the Qt event loop."""

from __future__ import annotations

import argparse
import logging
import os
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
    parser.add_argument(
        "--separation-self-test",
        action="store_true",
        help="install the separation runtime, separate a test clip, and exit (used by CI)",
    )
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


def make_stem_manager(youtube: YouTube, settings: Any, ffmpeg: str | None, separator: Any) -> Any:
    from ytktv.separation.cache import StemCache
    from ytktv.separation.worker import StemManager

    cache = StemCache(cache_dir() / "stems", int(settings.stem_cache_gb * 1024**3))

    def download(video_id: str, dest: Path) -> Path:
        return youtube.download_audio(video_id, dest, ffmpeg=ffmpeg)

    manager = StemManager(cache, separator, download)
    manager.start()
    return manager


def make_separator(settings: Any, runtime: Any = None) -> Any:
    """Separator running in a worker process.

    With *runtime* it uses the downloaded environment (packaged Windows / Linux
    builds); otherwise the libraries that are part of this build.
    """
    from ytktv.separation.remote import SubprocessSeparator, builtin_launcher, runtime_launcher
    from ytktv.separation.runtime import VARIANTS

    directml = False
    launcher = builtin_launcher()
    if runtime is not None:
        directml = VARIANTS[runtime.installed_variant()].directml
        launcher = runtime_launcher(runtime.python)
    return SubprocessSeparator(
        launcher,
        settings.separation_model,
        data_dir() / "models",
        cache_dir() / "separator",
        directml=directml,
        log_path=cache_dir() / "separator.log",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        # Windowed builds have no console; YTKTV_LOG_FILE captures the log instead.
        filename=os.environ.get("YTKTV_LOG_FILE") or None,
    )

    if args.separation_self_test:
        from ytktv.separation import runtime as separation_runtime

        return separation_runtime.self_test(lambda line: log.info("%s", line))

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

    from ytktv.separation import runtime as separation_runtime
    from ytktv.separation.base import separation_installed

    # Three ways to get separation: libraries inside this build (macOS, source installs),
    # a downloaded runtime (packaged Windows / Linux), or not at all. Either way it runs
    # in a separate low-priority process so it cannot disturb the live audio.
    runtime = None
    separator: Any = None
    if separation_installed():
        separator = make_separator(settings)
    elif separation_runtime.supported():
        runtime = separation_runtime.Runtime()
        if runtime.installed_variant():
            separator = make_separator(settings, runtime)

    from ytktv.core.preload import MediaPreloader

    def preload(video_id: str, dest: Path) -> Path:
        return youtube.download_media(video_id, dest, settings.max_height, ffmpeg=ffmpeg)

    preloader = MediaPreloader(cache_dir() / "media", preload)
    preloader.start()

    controller = KTVController(
        store,
        player,
        youtube,
        library=Library(data_dir() / "library.json"),
        bus=bus,
        preloader=preloader,
        stems=make_stem_manager(youtube, settings, ffmpeg, separator) if separator else None,
        audio=audio,
    )

    def describe_device(active: Any) -> None:
        """Find out (off the GUI thread) which device separation runs on."""

        def work() -> None:
            try:
                label = active.start()
            except Exception as exc:
                log.warning("separation runtime did not start: %s", exc)
                label = "Unavailable (see Settings)"
            controller.accelerator = label
            bus.emit("state", None)

        threading.Thread(target=work, name="ytktv-detect", daemon=True).start()

    if separator is not None:
        describe_device(separator)
    elif runtime is None:
        controller.accelerator = "Not installed"

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
    updates.ready.connect(window.settings_page.set_update_ready)
    window.settings_page.install_update.connect(updates.install_now)
    if runtime is not None:
        from ytktv.ui.separation_setup import SeparationSetup

        def enable(new_separator: Any) -> None:
            controller.attach_stems(make_stem_manager(youtube, settings, ffmpeg, new_separator))
            describe_device(new_separator)

        setup = SeparationSetup(
            controller,
            runtime,
            window,
            make_separator=lambda: make_separator(settings, runtime),
            on_ready=enable,
        )
        window.settings_page.install_separation.connect(setup.install_recommended)
        setup.status.connect(window.settings_page.set_runtime_status)
        setup.start()
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
