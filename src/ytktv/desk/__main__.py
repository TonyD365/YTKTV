"""Start YTKTV Desk: the staff terminal server and its window."""

from __future__ import annotations

import sys
from typing import Any, cast

from ytktv.config import data_dir


def self_test() -> int:
    """Start the desk's server and announcer from a packaged build and ask it who it is."""
    import json
    import ssl
    import tempfile
    import time
    import urllib.request
    from pathlib import Path

    from ytktv.desk.server import Hub, create_desk_app
    from ytktv.desk.store import DeskStore
    from ytktv.rooms.discovery import Announcer
    from ytktv.server.app import ServerThread
    from ytktv.server.tls import ensure_certificate

    folder = Path(tempfile.mkdtemp())
    store = DeskStore(folder / "desk.sqlite3")
    port = 18770
    server = ServerThread(
        create_desk_app(store, Hub()),
        port,
        host="127.0.0.1",
        certificate=ensure_certificate(folder, "127.0.0.1"),
    )
    server.start()
    announcer = Announcer(store.desk_id, "YTKTV Desk", "127.0.0.1", port)
    context = ssl.create_default_context()
    context.check_hostname, context.verify_mode = False, ssl.CERT_NONE
    try:
        for _ in range(50):
            try:
                with urllib.request.urlopen(  # noqa: S310
                    f"https://127.0.0.1:{port}/api/desk", timeout=2, context=context
                ) as response:
                    reply = json.loads(response.read())
                break
            except OSError:
                time.sleep(0.2)
        else:
            print("desk self-test: the server did not answer")
            return 1
    finally:
        announcer.close()
        server.stop()
    ok = reply.get("desk_id") == store.desk_id
    print("desk self-test:", "ok" if ok else f"unexpected reply {reply}")
    return 0 if ok else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    import logging

    from ytktv import diagnostics

    logging.basicConfig(level=logging.INFO)
    diagnostics.keep_log("desk")
    from PySide6.QtWidgets import QApplication

    from ytktv.desk.server import DESK_PORT, Hub, create_desk_app
    from ytktv.desk.store import DeskStore
    from ytktv.desk.window import DeskWindow
    from ytktv.server.app import ServerThread, lan_ip
    from ytktv.ui import theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName("YTKTV Desk")
    from ytktv.ui import icons

    icons.install(app)  # our own icons instead of system emoji, everywhere
    from PySide6.QtGui import QIcon

    from ytktv.desk.window import ICON

    app.setWindowIcon(QIcon(str(ICON)))
    app.setStyleSheet(theme.STYLESHEET)
    from ytktv.desk import remote

    config = remote.load_config()
    if config is not None:
        return run_terminal(app, config)
    store = DeskStore(data_dir() / "desk.sqlite3")
    app.setStyleSheet(theme.apply(store.setting("theme", theme.DEFAULT_THEME)))
    hub = Hub()
    from ytktv.desk import staff
    from ytktv.desk.metrics import Metrics
    from ytktv.rooms.discovery import Announcer
    from ytktv.server.tls import ensure_certificate

    ip = lan_ip()
    certificate = ensure_certificate(data_dir() / "desk-tls", ip)
    metrics = Metrics()
    from ytktv.config import cache_dir
    from ytktv.desk import processing

    processor = None
    if store.setting(processing.SETTING, "0") == "1":
        try:
            processor = processing.make_processor(cache_dir() / "desk-processing")
        except Exception:
            logging.exception("could not start processing songs for the rooms")
        if processor is not None:
            processor.on_event = metrics.event
    desk_app = create_desk_app(
        store, hub, staff.certificate_hash(certificate[0]), metrics, processor
    )
    server = ServerThread(desk_app, DESK_PORT, certificate=certificate)
    server.start()
    try:
        announcer: Announcer | None = Announcer(
            store.desk_id, staff.machine_name(store), ip, DESK_PORT
        )
    except Exception:  # no multicast here; rooms can still type the address
        announcer = None
    # What is done here is logged under this Desk's name, like a terminal's under its own.
    name = lambda: staff.machine_name(store)  # noqa: E731 - read again at every change
    if store.setting(staff.SERVER_MODE_SETTING, "0") == "1":
        return run_server_mode(
            app, store, hub, metrics, f"{ip}:{DESK_PORT}", server, announcer, processor
        )
    window = DeskWindow(
        cast(DeskStore, staff.LoggedStore(store, name)),
        cast(Hub, staff.LoggedHub(hub, store, name)),
        f"{ip}:{DESK_PORT}",
    )
    try:
        return show(app, window)
    finally:
        if announcer is not None:
            announcer.close()
        server.stop()


def run_server_mode(
    app: Any,
    store: Any,
    hub: Any,
    metrics: Any,
    address: str,
    server: Any,
    announcer: Any,
    processor: Any = None,
) -> int:
    """This computer only runs the server; its window is the server console."""
    from ytktv.desk.awake import KeepAwake
    from ytktv.desk.console import ServerConsole

    console = ServerConsole(store, hub, metrics, address, KeepAwake(), processor)
    try:
        console.show()
        return int(app.exec())
    finally:
        if console.keep_awake is not None:
            console.keep_awake.stop()
        if announcer is not None:
            announcer.close()
        server.stop()


def run_terminal(app: Any, config: Any) -> int:
    """This Desk is a staff terminal: the same window, working on the main Desk's records."""
    from ytktv.desk import remote
    from ytktv.desk.server import Hub
    from ytktv.desk.store import DeskStore
    from ytktv.desk.window import DeskWindow

    main = remote.MainDesk(config)
    window = DeskWindow(
        cast(DeskStore, remote.RemoteStore(main)),
        cast(Hub, remote.RemoteHub(main)),
        f"the main Desk, {config.main_name or config.address}",
        terminal=main,
    )
    previous = sys.excepthook

    def offline(kind: Any, value: Any, trace: Any) -> None:
        # A button pressed while the main Desk is unreachable: say so, do not crash.
        if isinstance(value, (remote.DeskOffline, remote.NotPaired)):
            window.refresh()
            return
        previous(kind, value, trace)

    sys.excepthook = offline
    try:
        return show(app, window)
    finally:
        main.close()


def show(app: Any, window: Any) -> int:
    from ytktv.desk.update import DeskUpdater

    window.watch_updates(DeskUpdater(window, automatic=window.updates.automatic))
    window.show()
    return int(app.exec())


if __name__ == "__main__":
    sys.exit(main())
