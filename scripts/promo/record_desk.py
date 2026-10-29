"""Record YTKTV Desk being used, headless, into video/desk.mp4."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import imageio_ffmpeg
from PySide6.QtCore import QPoint, QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

FPS = 30
FRAMES = Path("video/frames_desk")


def main() -> None:
    from ytktv.desk.server import Hub
    from ytktv.desk.store import Booking, DeskStore, Product
    from ytktv.desk.window import DeskWindow
    from ytktv.ui import theme

    app = QApplication(sys.argv[:1])
    app.setStyleSheet(theme.STYLESHEET)
    store = DeskStore()
    names = ("101", "102", "103", "105", "201 VIP", "202", "203", "301 Party")
    ids = [store.pair(store.new_code(), n)[0].room_id for n in names]
    store.set_type(ids[0], "Small", 4)
    store.set_type(ids[4], "VIP", 12)
    store.set_type(ids[5], "Large", 10)
    store.set_type(ids[7], "Party", 20)
    store.open_room(ids[0], "Kim", 120)
    store.open_room(ids[4], "Sam & friends", None)
    store.open_room(ids[7], "Birthday", 180)
    store.close_room(ids[1])
    store.set_state(ids[6], "maintenance")
    store.book(Booking(0, ids[5], time.time() + 3600, 120, "Lee"))
    cola = store.save_product(Product(0, "Cola", "Drinks", 3.5, stock=20))
    store.add_order(ids[0], [(cola, 2)])
    for room_id, song in ((ids[0], "Alexander's Ragtime Band"), (ids[4], "A Perfect Day"),
                          (ids[7], "Happy Birthday")):
        store.note_song(room_id, song)
    hub = Hub()
    hub.channels = {i: None for i in ids if i != ids[3]}  # type: ignore[misc]
    hub.send_soon = lambda *_a, **_k: None  # type: ignore[method-assign]
    window = DeskWindow(store, hub, "192.168.1.10:8770")
    window.resize(1920, 1080)
    window.show()
    shutil.rmtree(FRAMES, ignore_errors=True)
    FRAMES.mkdir(parents=True)

    cursor = {"pos": QPointF(1400, 700), "goal": QPointF(1400, 700), "ring": 0}
    count = [0]

    def at(widget: QWidget) -> QPoint:
        return widget.mapTo(window, widget.rect().center())

    def tile(name: str) -> QPushButton:
        return next(b for b in window.findChildren(QPushButton)
                    if b.objectName() == "roomTile" and b.text().startswith(name) and b.isVisible())

    def move(target: object) -> None:
        widget = target() if callable(target) else target
        cursor["goal"] = QPointF(at(widget))

    def press(action: object) -> None:
        cursor["ring"] = 12
        action()

    def grab() -> None:
        pos, goal = cursor["pos"], cursor["goal"]
        cursor["pos"] = pos + (goal - pos) * 0.18
        image = window.grab().toImage()
        p = QPainter(image)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x, y = cursor["pos"].x(), cursor["pos"].y()
        if cursor["ring"] > 0:
            r = 14 + (12 - cursor["ring"]) * 4
            p.setPen(QPen(QColor(255, 61, 154, 20 * cursor["ring"]), 4))
            p.drawEllipse(QPointF(x, y), r, r)
            cursor["ring"] -= 1
        arrow = [(0, 0), (0, 26), (7, 20), (18, 20)]
        p.setPen(QPen(QColor("black"), 2))
        p.setBrush(QColor("white"))
        p.drawPolygon(QPolygonF([QPointF(x + a, y + b) for a, b in arrow]))
        p.end()
        image.save(str(FRAMES / f"{count[0]:05d}.png"))
        count[0] += 1

    room = ids[2]
    open_button = window.room_actions["open"]
    steps: list[tuple[int, object]] = [
        (600, lambda: move(lambda: tile("103"))),
        (1500, lambda: press(lambda: window.select(room))),
        (2200, lambda: move(open_button)),
        (3000, lambda: press(lambda: (store.set_state(room, "ready"),
                                      window.open_room(guest="Alex", length="2 hours")))),
        (4200, lambda: (store.add_call(ids[4], "Drinks", "more ice"), window.refresh())),
        (5000, lambda: move(lambda: window.call_chips.itemAt(0).widget())),
        (6000, lambda: press(lambda: window.finish_call(store.calls()[0].call_id))),
        (6800, lambda: move(window.nav["Bookings"])),
        (7600, lambda: press(lambda: window.show_tab(1))),
        (9200, lambda: move(window.nav["Rooms"])),
        (10000, lambda: press(lambda: window.show_tab(0))),
    ]
    for delay, step in steps:
        QTimer.singleShot(delay, step)
    timer = QTimer()
    timer.timeout.connect(grab)
    timer.start(1000 // FPS)
    QTimer.singleShot(11500, app.quit)
    app.exec()
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-framerate", str(FPS),
         "-i", str(FRAMES / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "18", "video/desk.mp4"],
        check=True,
    )
    print("desk frames:", count[0], "seconds:", round(count[0] / FPS, 1))


if __name__ == "__main__":
    main()
