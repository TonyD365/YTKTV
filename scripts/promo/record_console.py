"""Record the real console being used, headless, into video/console.mp4."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import imageio_ffmpeg
import readme_images
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ytktv.core.models import Song

FPS = 30
SCENE = sys.argv[1] if len(sys.argv) > 1 else "search"
FRAMES = Path(f"video/frames_{SCENE}")
SONGS = [
    Song("demo1911", "Alexander's Ragtime Band (1911)", "Collins & Harlan", 172),
    Song("demo1915", "A Perfect Day (1915)", "Public Domain Records", 190),
]


class Source:
    def search(self, query, limit=24):
        return SONGS

    def hot(self, category):
        return SONGS

    def suggest(self, text, limit=8):
        return []

    def lookup(self, video_id):
        return None


def centre(window: QWidget, widget: QWidget) -> QPoint:
    return widget.mapTo(window, widget.rect().center())


def main() -> None:
    from ytktv.audio import devices
    from ytktv.ui import theme
    from ytktv.ui.main_window import MainWindow
    from ytktv.ui.mv_window import MvWindow

    app = QApplication(sys.argv[:1])
    app.setStyleSheet(theme.STYLESHEET)
    devices.list_inputs = lambda: ["USB Wireless Mic"]
    devices.list_outputs = lambda: ["Living Room TV (HDMI)"]
    controller = readme_images.demo_controller()
    controller.set_volume("music", 55)
    controller.set_volume("mic", 60)
    window = MainWindow(controller, Source(), MvWindow(None), "http://192.168.1.20:8765")
    show_toast = window.show_toast
    # The demo has no separation model; keep its "not installed" notice out of the video.
    window.show_toast = lambda text, **kw: (  # type: ignore[method-assign]
        None if "separation" in text else show_toast(text, **kw)
    )
    window.resize(1920, 1080)
    window.show()
    shutil.rmtree(FRAMES, ignore_errors=True)
    FRAMES.mkdir(parents=True)
    cursor = {"pos": QPointF(1500, 700), "goal": QPointF(1500, 700), "ring": 0}
    count = [0]

    def move_to(point: QPoint) -> None:
        cursor["goal"] = QPointF(point)

    def click(widget: QWidget) -> None:
        cursor["ring"] = 12
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

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

    search_page = window.pages["search"]

    def button(text: str, page: QWidget | None = None) -> QPushButton:
        found = (page or window).findChildren(QPushButton)
        return next(b for b in found if text in b.text() and b.isVisible())

    def press(t: int, text: str, page: str | None = None) -> list[tuple[int, object]]:
        def target() -> QPushButton:
            return button(text, window.pages[page] if page else None)

        return [
            (t, lambda: move_to(centre(window, target()))),
            (t + 900, lambda: click(target())),
        ]

    def tap(t: int, widget: QWidget) -> list[tuple[int, object]]:
        return [
            (t, lambda: move_to(centre(window, widget))),
            (t + 700, lambda: click(widget)),
        ]

    key_up = button("♯")
    music_up = window.level_keys["music_volume"][1]
    mic_up = window.level_keys["mic_volume"][1]
    if SCENE == "games2":
        steps = [
            (200, lambda: window.show_page("games")),
            *press(900, "Number bomb", "games"),
            *press(2600, "Liar's dice: roll", "games"),
            *press(4300, "Challenge card", "games"),
        ]
        end = 6500
    elif SCENE == "controls":
        steps = [
            *tap(500, key_up),
            (1700, lambda: click(key_up)),
            *tap(2600, music_up),
            (3800, lambda: click(music_up)),
            (4300, lambda: click(music_up)),
            *tap(5200, mic_up),
            (6400, lambda: click(mic_up)),
        ]
        end = 8200
    elif SCENE == "party":
        steps = [
            *press(600, "Instrumental"),
            *press(2400, "Games"),
            *press(4000, "Who sings next", "games"),
        ]
        end = 7500
    else:
        steps = [
            *press(800, "Search", "home"),
            (2300, lambda: move_to(centre(window, search_page.input))),
            (3000, lambda: click(search_page.input)),
        ]
        t = 3300
        for ch in "Alexander":
            steps.append((t, lambda c=ch: QTest.keyClicks(search_page.input, c)))
            t += 130
        steps += [
            (t + 300, lambda: QTest.keyClick(search_page.input, Qt.Key.Key_Return)),
            *press(t + 1600, "Select", "search"),
            (t + 3600, lambda: window.show_page("home")),
        ]
        end = t + 6000
    for delay, step in steps:
        QTimer.singleShot(delay, step)
    timer = QTimer()
    timer.timeout.connect(grab)
    timer.start(1000 // FPS)
    QTimer.singleShot(end, app.quit)
    app.exec()
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            ffmpeg,
            "-v",
            "error",
            "-y",
            "-framerate",
            str(FPS),
            "-i",
            str(FRAMES / "%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            f"video/console_{SCENE}.mp4",
        ],
        check=True,
    )
    print(SCENE, "frames:", count[0], "seconds:", round(count[0] / FPS, 1))


if __name__ == "__main__":
    main()
