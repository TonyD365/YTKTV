"""Start YTKTV Desk: the front desk server and its window."""

from __future__ import annotations

import sys

from ytktv.config import data_dir


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from ytktv.desk.server import DESK_PORT, Hub, create_desk_app
    from ytktv.desk.store import DeskStore
    from ytktv.desk.window import DeskWindow
    from ytktv.server.app import ServerThread, lan_ip
    from ytktv.ui import theme

    app = QApplication(sys.argv[:1])
    app.setApplicationName("YTKTV Desk")
    app.setStyleSheet(theme.STYLESHEET)
    store = DeskStore(data_dir() / "desk.sqlite3")
    hub = Hub()
    server = ServerThread(create_desk_app(store, hub), DESK_PORT)
    server.start()
    window = DeskWindow(store, hub, f"{lan_ip()}:{DESK_PORT}")
    window.show()
    try:
        return app.exec()
    finally:
        server.stop()


if __name__ == "__main__":
    sys.exit(main())
