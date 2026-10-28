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

from ytktv import __version__, bootstrap, children
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
        "--hd-unlock-self-test",
        action="store_true",
        help="check that this build can use the HD unlock component, and exit (used by CI)",
    )
    parser.add_argument(
        "--phone-mic-self-test",
        action="store_true",
        help="check that this build can serve the phone microphone page, and exit (used by CI)",
    )
    parser.add_argument(
        "--mpv-self-test",
        action="store_true",
        help="check that the mpv libraries can play through YTKTV's filters, and exit (used by CI)",
    )
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
    """Find libmpv; when it is missing, offer to install it. Returns True if usable.

    mpv is a separate program under the GPL and is not part of YTKTV or its releases.
    YTKTV asks before installing it, the usual way for each system: Homebrew on macOS,
    the Windows build linked from mpv.io, the package manager on Linux.
    """
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import QMessageBox, QProgressDialog

    while not bootstrap.find_libmpv():
        plan = bootstrap.install_plan()
        box = QMessageBox()
        box.setWindowTitle("mpv is needed")
        box.setIcon(QMessageBox.Icon.Information)
        if plan is not None:
            box.setText("YTKTV plays video with mpv, a free program that is installed separately.")
            box.setInformativeText(f"Install mpv now?\n\nYTKTV will run: {plan}")
            install = box.addButton("Install mpv", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
            box.setDefaultButton(install)
            box.exec()
            if box.clickedButton() is not install:
                return False
            if _install_libmpv_with_progress(app, QProgressDialog):
                return True
            QMessageBox.warning(
                None,
                "mpv was not installed",
                f"Installing mpv did not work. You can install it yourself:\n\n{plan}\n\n"
                "Then start YTKTV again.",
            )
            return False
        # macOS without Homebrew (or a Linux without a known package manager).
        if platform.system() == "Darwin":
            box.setText("YTKTV plays video with mpv, a free program that is installed separately.")
            box.setInformativeText(
                "The easiest way on a Mac is Homebrew. Install Homebrew from brew.sh, then press "
                "Check Again; YTKTV installs mpv for you.\n\n"
                "Or, in Terminal: brew install mpv"
            )
            website = box.addButton("Open brew.sh", QMessageBox.ButtonRole.ActionRole)
        else:
            box.setText("YTKTV plays video with mpv, which is not installed.")
            box.setInformativeText(
                "Install mpv (libmpv) with your system's package manager, then press Check Again."
            )
            website = box.addButton("Open mpv.io", QMessageBox.ButtonRole.ActionRole)
        again = box.addButton("Check Again", QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Not Now", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(again)
        box.exec()
        clicked = box.clickedButton()
        if clicked is website:
            url = (
                "https://brew.sh"
                if platform.system() == "Darwin"
                else "https://mpv.io/installation/"
            )
            QDesktopServices.openUrl(QUrl(url))
        elif clicked is later:
            return False
    return True


def _install_libmpv_with_progress(app: Any, dialog_class: Any) -> bool:
    dialog = dialog_class("Installing mpv. This can take a few minutes...", "", 0, 0)
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


def _give_missing_console_streams_somewhere_to_go() -> None:
    """A windowed Windows build has no console: sys.stdout and sys.stderr are None.

    Libraries that print, or merely ask the stream a question, fail on that, so the
    missing streams are pointed at nothing.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))  # noqa: SIM115


def main(argv: list[str] | None = None) -> int:
    _give_missing_console_streams_somewhere_to_go()
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        # Windowed builds have no console; YTKTV_LOG_FILE captures the log instead.
        filename=os.environ.get("YTKTV_LOG_FILE") or None,
    )

    if args.hd_unlock_self_test:
        from ytktv.youtube import hd_unlock

        return hd_unlock.self_check(lambda line: log.info("%s", line))

    if args.phone_mic_self_test:
        from ytktv.server import mic_app

        return mic_app.self_test(lambda line: log.info("%s", line))

    if args.mpv_self_test:
        from ytktv.player import mpv_check

        return mpv_check.self_test(lambda line: log.info("%s", line))

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
    from PySide6.QtGui import QIcon

    from ytktv.ui.icon import ICON_FILE

    app.setWindowIcon(QIcon(str(ICON_FILE)))  # title bars and the taskbar; macOS uses the bundle's
    app.setApplicationVersion(__version__)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    from ytktv.ui import theme
    from ytktv.ui.support import collect_garbage_on_gui_thread

    app.setStyleSheet(theme.STYLESHEET)
    collect_garbage_on_gui_thread(app)

    children.start([data_dir()])
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
    from ytktv.youtube.hd_unlock import HdUnlock

    unlock = HdUnlock()
    if unlock.supported():
        youtube.hd_unlock = unlock
    bus = EventBus()
    audio = None
    if not args.no_mic:
        from ytktv.audio.engine import AudioEngine
        from ytktv.audio.phone_mic import PhoneMics

        phones = PhoneMics()
        # Called from the server's thread when a phone connects or leaves.
        phones.on_change = lambda: bus.emit("phones", None)
        audio = AudioEngine(settings, phones)
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

    mic_server = None
    if audio is not None and audio.phones is not None:
        # Phones as microphones need HTTPS, so they get a small server of their own.
        try:
            from ytktv.server import tls
            from ytktv.server.app import lan_ip
            from ytktv.server.mic_app import create_mic_app

            certificate = tls.ensure_certificate(data_dir() / "tls", lan_ip())
            mic_server = ServerThread(
                create_mic_app(audio.phones, controller.phone_channel),
                free_port(server.port + 1),
                certificate=certificate,
            )
            mic_server.start()
            controller.phone_mic_url = mic_server.url
            log.info("phone microphone: %s", mic_server.url)
        except Exception:
            log.exception("the phone microphone page could not be started")
            mic_server = None

    from ytktv.ui.main_window import MainWindow
    from ytktv.ui.mv_window import MvWindow
    from ytktv.ui.update_manager import UpdateManager

    mv_window = MvWindow(player if have_mpv else None)
    from ytktv.rooms.client import RoomClient

    room_client = RoomClient(store, lambda kind, data: None)
    room_client.start()
    window = MainWindow(
        controller,
        youtube,
        mv_window,
        server.url,
        force_windowed=args.windowed,
        room_client=room_client,
    )
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
    if youtube.hd_unlock is not None:
        from ytktv.ui.hd_unlock_setup import HdUnlockSetup

        hd_setup = HdUnlockSetup(controller, youtube, window)
        hd_setup.status.connect(window.settings_page.set_hd_unlock_status)
        window.settings_page.install_hd_unlock.connect(hd_setup.install)
        hd_setup.publish()
    window.settings_page.run_setup.connect(window.run_setup)
    window.show()
    window.place_mv()
    if not settings.setup_done:
        window.run_setup()
    if not have_mpv:
        window.show_toast("Video playback is unavailable: mpv is not installed.", error=True)

    def shutdown() -> None:
        server.stop()
        if mic_server is not None:
            mic_server.stop()
        mv_window.release()
        controller.close()
        children.stop()  # downloads, HD unlock and separation must not carry on alone

    app.aboutToQuit.connect(shutdown)
    return int(app.exec())
