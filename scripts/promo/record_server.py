"""Record the Desk's Server Mode console, headless, into video/server.mp4.

Rooms connect, staff terminals work, the GPU processes songs for the rooms: all made up,
shown on the real console window.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import imageio_ffmpeg
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QApplication

FPS = 30
FRAMES = Path("video/frames_server")


class FakeStems:
    def __init__(self) -> None:
        self.cache = SimpleNamespace(size=lambda: int(6.4 * 2**30))
        self._separator = SimpleNamespace(device_label="NVIDIA GeForce RTX 4070")
        self._active: str | None = None


class FakeProcessor:
    def __init__(self) -> None:
        self.stems = FakeStems()
        self.lyrics = SimpleNamespace(installed=True)
        self.waiting = ["a", "b", "c", "d", "e"]

    def queue(self) -> list[str]:
        return self.waiting


def main() -> None:
    from ytktv.desk import staff
    from ytktv.desk.console import ServerConsole
    from ytktv.desk.metrics import Metrics
    from ytktv.desk.server import Hub
    from ytktv.desk.store import DeskStore
    from ytktv.ui import theme

    app = QApplication(sys.argv[:1])
    app.setStyleSheet(theme.STYLESHEET)
    store = DeskStore()
    store.set_setting(staff.NAME_SETTING, "Main Desk")
    names = ("101", "102", "103", "105", "201 VIP", "202", "203", "301 Party")
    ids = [store.pair(store.new_code(), n)[0].room_id for n in names]
    for room_id, guest in ((ids[0], "Kim"), (ids[4], "Sam & friends"), (ids[7], "Birthday")):
        store.open_room(room_id, guest, 120)
    for name in ("Bar", "Lobby"):
        store.pair_terminal(store.new_terminal_code(), name)
    hub = Hub()
    hub.channels = {i: None for i in ids[:5]}  # type: ignore[misc]
    metrics = Metrics()
    metrics.cpu_percent = lambda: 18.0  # type: ignore[method-assign]
    for _ in range(140):
        metrics.request(200)
    processor = FakeProcessor()
    window = ServerConsole(store, hub, metrics, "192.168.1.10:8770", processor=processor)
    window.confirm_close = False
    window.resize(1920, 1080)
    window.show()
    shutil.rmtree(FRAMES, ignore_errors=True)
    FRAMES.mkdir(parents=True)
    cursor = {"pos": QPointF(1500, 900), "goal": QPointF(1500, 900), "ring": 0}
    count = [0]

    def grab() -> None:
        for _ in range(3):
            metrics.request(200)
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

    def happen(kind: str, text: str, room: int | None = None, active: str | None = None) -> None:
        if room is not None:
            hub.channels[ids[room]] = None  # type: ignore[index]
        if active is not None:
            processor.stems._active = active or None
            if processor.waiting:
                processor.waiting.pop()
        metrics.event(kind, text)
        window.refresh()

    def pick(index: int) -> None:
        cursor["ring"] = 12
        window.filter.setCurrentIndex(index)

    filter_at = QPointF(window.filter.mapTo(window, window.filter.rect().center()))
    steps = [
        (300, lambda: happen("room", "Room 202 connected", room=5)),
        (
            900,
            lambda: happen(
                "gpu", "Separated Alexander's Ragtime Band in 21 s", active="A Perfect Day"
            ),
        ),
        (1500, lambda: (store.log("Bar", "Opened room 203 for Lee"), window.refresh())),
        (2100, lambda: happen("gpu", "Wrote lyrics for Alexander's Ragtime Band (38 lines)")),
        (2700, lambda: happen("terminal", "Lobby checked in a booking")),
        (3300, lambda: happen("gpu", "Separated A Perfect Day in 18 s", active="Happy Birthday")),
        (3600, lambda: cursor.update(goal=filter_at)),
        (4600, lambda: pick(3)),  # Songs
        (5200, lambda: happen("gpu", "Wrote lyrics for A Perfect Day (24 lines)")),
        (6200, lambda: pick(0)),
        (6600, lambda: happen("room", "Room 203 connected", room=6)),
    ]
    # Driven by frame, not by the clock: saving a 1080p frame takes longer than 1/30 s.
    for frame in range(8 * FPS):
        for delay, step in steps:
            if delay * FPS // 1000 == frame:
                step()
        app.processEvents()
        grab()
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-y", "-framerate", str(FPS),
            "-i", str(FRAMES / "%05d.png"), "-vf", "scale=1600:900", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-crf", "18", "video/server.mp4",
        ],
        check=True,
    )  # fmt: skip


if __name__ == "__main__":
    main()
