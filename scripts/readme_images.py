"""Regenerate the README and website pictures in docs/images.

    python scripts/readme_images.py            # console, mixer, MV screen, demo GIF
    python scripts/readme_images.py --phone    # also the phone page (needs Google Chrome)

Everything is drawn off-screen: no window opens. The songs, singers and covers are made up,
so no real artwork appears in the pictures.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, QUrl  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QFont,
    QImage,
    QLinearGradient,
    QPainter,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

SONGS = [  # title, channel, seconds, singer
    ("Neon Nights (Karaoke Version)", "Party Hits", 214, "Kim"),
    ("Midnight City Lights", "Synth Club", 245, "Alex"),
    ("Paper Moon Duet", "Ballad Stars", 232, "Kim & Lee"),
    ("Dancing On The Ceiling Fan", "Funk Room", 198, "Sam"),
    ("Hometown Summer", "Acoustic Night", 221, "Alex"),
    ("Last Train Home", "City Pop Classics", 256, ""),
]
COLOURS = [
    ("#ff3d9a", "#5b1aa6"),
    ("#2ee6ff", "#3a1a7a"),
    ("#ffc94d", "#c2185b"),
    ("#8b5cff", "#1e88e5"),
    ("#00c9a7", "#2a1052"),
    ("#ff7a59", "#4a148c"),
]


def run_for(app: QApplication, steps: list[tuple[int, object]]) -> None:
    """Run (milliseconds, callable) steps on the Qt event loop, then stop."""
    for delay, step in steps:
        QTimer.singleShot(delay, step)
    QTimer.singleShot(max(delay for delay, _ in steps) + 200, app.quit)
    app.exec()


def cover(folder: Path, index: int, title: str) -> str:
    """A made-up album cover: a colour blend with the song's initials. Returns a file URL."""
    image = QImage(320, 180, QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    blend = QLinearGradient(0, 0, 320, 180)
    blend.setColorAt(0, QColor(COLOURS[index][0]))
    blend.setColorAt(1, QColor(COLOURS[index][1]))
    painter.fillRect(0, 0, 320, 180, blend)
    font = QFont()
    font.setWeight(QFont.Weight.Black)
    font.setPixelSize(74)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 215))
    initials = "".join(word[0] for word in title.split()[:2]).upper()
    painter.drawText(QRectF(0, 0, 320, 180), Qt.AlignmentFlag.AlignCenter, initials)
    painter.end()
    path = folder / f"cover{index}.png"
    image.save(str(path))
    return QUrl.fromLocalFile(str(path)).toString()


def demo_controller(covers: bool = True):
    from ytktv.config import SettingsStore
    from ytktv.core.controller import KTVController
    from ytktv.core.models import Song
    from ytktv.player.fake import FakePlayer
    from ytktv.youtube.parse import MediaSource

    class Resolver:
        def resolve(self, video_id, max_height=1080):
            return MediaSource("http://example.invalid/" + video_id)

        def forget_stream(self, video_id, max_height=1080):
            pass

    folder = Path(tempfile.mkdtemp())
    controller = KTVController(SettingsStore(folder / "settings.json"), FakePlayer(), Resolver())
    controller.accelerator = "GPU: Apple M5 (Metal)"
    controller.settings.mics[1].enabled = True
    controller.settings.mics[1].device = "Phone: Kim"
    for i, (title, channel, seconds, singer) in enumerate(SONGS):
        thumbnail = cover(folder, i, title) if covers else ""
        controller.enqueue(Song(f"demo{i:07d}", title, channel, seconds, thumbnail), singer=singer)
    return controller


def console(app: QApplication) -> None:
    from ytktv.audio import devices
    from ytktv.ui.main_window import MainWindow
    from ytktv.ui.mv_window import MvWindow
    from ytktv.youtube.search import YouTube

    devices.list_inputs = lambda: ["USB Wireless Mic", "MacBook Microphone"]
    devices.list_outputs = lambda: ["Living Room TV (HDMI)", "MacBook Speakers"]
    window = MainWindow(demo_controller(), YouTube(), MvWindow(None), "http://192.168.1.20:8765")
    window.resize(1600, 1000)
    window.show()
    run_for(
        app,
        [
            (600, lambda: window.show_page("home")),
            (1500, lambda: window.grab().save(str(OUT / "console.png"))),
            (1600, lambda: window.show_page("mixer")),
            (2600, lambda: window.grab().save(str(OUT / "mixer.png"))),
            (2700, lambda: window.show_page("party")),
            (3600, lambda: window.grab().save(str(OUT / "party.png"))),
            (3700, lambda: window.pages["games"].open_game("spin").start()),
            (3800, lambda: window.show_page("games")),
            (4700, lambda: window.grab().save(str(OUT / "games.png"))),
        ],
    )


def stage(width: int, height: int) -> QPixmap:
    """A drawn stage with three spotlights, standing in for a music video."""
    image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    sky = QLinearGradient(0, 0, 0, height)
    sky.setColorAt(0, QColor("#120a2e"))
    sky.setColorAt(0.7, QColor("#2a1052"))
    sky.setColorAt(1, QColor("#0a0614"))
    p.fillRect(0, 0, width, height, sky)
    p.setPen(Qt.PenStyle.NoPen)
    for x, colour in ((0.18, "#ff3d9a"), (0.5, "#2ee6ff"), (0.82, "#8b5cff")):
        beam = QRadialGradient(QPointF(width * x, -40), height * 1.05)
        c = QColor(colour)
        c.setAlpha(95)
        beam.setColorAt(0, c)
        c.setAlpha(0)
        beam.setColorAt(1, c)
        p.setBrush(beam)
        p.drawPolygon(
            [
                QPointF(width * x - 30, 0),
                QPointF(width * x + 30, 0),
                QPointF(width * x + 260, height),
                QPointF(width * x - 260, height),
            ]
        )
    floor = QLinearGradient(0, height * 0.7, 0, height)
    floor.setColorAt(0, QColor("#1a0d33"))
    floor.setColorAt(1, QColor("#05030c"))
    p.fillRect(QRectF(0, height * 0.7, width, height * 0.3), floor)
    p.end()
    return QPixmap.fromImage(image)


TUNE = [
    64,
    64,
    66,
    67,
    None,
    69,
    67,
    66,
    64,
    62,
    None,
    64,
    66,
    67,
    67,
    69,
    71,
    None,
    72,
    71,
    69,
    67,
]


def mv_screen(app: QApplication, width: int = 1600, height: int = 900):
    """The MV screen with its real overlays: lyrics, pitch lane, score, danmaku, lights."""
    from ytktv.ui import theme
    from ytktv.ui.mv_window import MvWindow

    app.setStyleSheet(theme.STYLESHEET)
    mv = MvWindow(None)
    mv.resize(width, height)
    mv.idle.hide()
    background = QLabel(mv)
    background.setPixmap(stage(width, height))
    background.setGeometry(0, 0, width, height)
    background.lower()
    mv.resizeEvent(None)
    words = [[12.0, 0], [12.4, 5], [12.9, 9], [13.5, 14]]
    mv.set_lyrics(
        [
            {"start": 12.0, "end": 15.0, "text": "Sing it loud tonight", "words": words},
            {"start": 15.0, "end": 18.0, "text": "under the neon lights"},
        ]
    )
    mv.lyrics.show()
    notes = [n for n in TUNE * 4 for _ in range(7)]
    mv.set_melody({"hop": 0.05, "notes": notes, "transpose": 0.0})
    mv.set_live_score(87)
    return mv, notes


def sing(mv, notes, now: float) -> None:
    """Draw the singer's voice up to *now*, slightly off on some notes."""
    for i in range(int((now - 2) / 0.05), int(now / 0.05)):
        target = notes[i] if 0 <= i < len(notes) else None
        if target is not None:
            mv.add_sung_pitch(i * 0.05, target - 12 + (0.3 * math.sin(i) if i % 11 else 2.4))


def lights(mv, phase: float) -> None:
    """Pulse the edge lights in the console's own colours: pink, cyan, purple, blue."""
    for k, (side, hue) in enumerate(
        (("left", 0.9), ("right", 0.5), ("top", 0.75), ("bottom", 0.62))
    ):
        strength = 0.45 + 0.35 * math.sin(phase * 2.2 + k)
        mv.lights[side].set_light(strength, (hue + 0.03 * math.sin(phase + k)) % 1.0)


def mv_still(app: QApplication) -> None:
    mv, notes = mv_screen(app)
    sing(mv, notes, 13.2)
    mv.pitch_lane.set_time(13.2)
    mv.add_danmaku("What a voice! 🎤")
    mv.add_danmaku("唱得好！")
    mv.danmaku.advance(4.2)
    lights(mv, 0.4)
    run_for(
        app,
        [
            (300, lambda: mv.lyrics.set_time(13.2)),
            (900, lambda: mv.grab().save(str(OUT / "mv-screen.png"))),
        ],
    )


def demo_gif(app: QApplication, seconds: float = 4.0, fps: int = 12) -> None:
    """A short loop of the MV screen while someone sings: docs/images/demo.gif."""
    from PIL import Image

    mv, notes = mv_screen(app, 960, 540)
    mv.add_danmaku("What a voice! 🎤")
    frames: list[Image.Image] = []
    count = int(seconds * fps)
    step = {"i": 0}

    def frame() -> None:
        i = step["i"]
        now = 11.6 + i / fps
        mv.pitch_lane.set_melody({"hop": 0.05, "notes": notes, "transpose": 0.0})
        sing(mv, notes, now)
        mv.pitch_lane.set_time(now)
        mv.lyrics.set_time(now)
        mv.danmaku.advance(1 / fps)
        if i == int(count * 0.45):
            mv.add_danmaku("唱得好！")
        lights(mv, i / fps)
        image = mv.grab().toImage().convertToFormat(QImage.Format.Format_RGB888)
        data = bytes(image.constBits())[: image.sizeInBytes()]
        frames.append(
            Image.frombuffer(
                "RGB", (image.width(), image.height()), data, "raw", "RGB", image.bytesPerLine()
            ).copy()
        )
        step["i"] += 1
        if step["i"] < count:
            QTimer.singleShot(5, frame)
        else:
            app.quit()

    QTimer.singleShot(600, frame)
    app.exec()
    # Each frame gets its own 256 colours: one shared palette turned the lights muddy.
    still = [f.quantize(colors=256, method=Image.Quantize.FASTOCTREE) for f in frames]
    still[0].save(
        OUT / "demo.gif",
        save_all=True,
        append_images=still[1:],
        duration=int(1000 / fps),
        loop=0,
        optimize=True,
    )


def phone(chrome: str) -> None:
    """The phone page in headless Chrome, at a phone's width, with made-up songs."""
    from fastapi.responses import HTMLResponse
    from PIL import Image

    from ytktv.server import app as server_app

    class Source:
        def search(self, query, limit=24):
            return []

        def hot(self, category):
            return []

        def suggest(self, text, limit=8):
            return []

        def lookup(self, video_id):
            return None

    controller = demo_controller(covers=False)
    me = hashlib.sha256(b"127.0.0.1").hexdigest()[:10]
    for item in controller.queue.snapshot()[1::2]:
        item.owner, item.singer = me, "Tony"
    for i, item in enumerate(controller.queue.snapshot()):
        a, b = COLOURS[i % len(COLOURS)]
        initials = "".join(w[0] for w in item.song.title.split()[:2]).upper()
        svg = (
            "<svg xmlns='http://www.w3.org/2000/svg' width='320' height='180'>"
            "<defs><linearGradient id='g' x2='1' y2='1'>"
            f"<stop offset='0' stop-color='{a}'/><stop offset='1' stop-color='{b}'/>"
            "</linearGradient></defs><rect width='320' height='180' fill='url(#g)'/>"
            "<text x='160' y='118' font-family='Helvetica' font-weight='900' font-size='74' "
            f"fill='white' fill-opacity='.85' text-anchor='middle'>{initials}</text></svg>"
        )
        object.__setattr__(item.song, "thumbnail", "data:image/svg+xml," + urllib.parse.quote(svg))
    controller.position = 74.0
    for points, title, singer in (
        (96, "Last Train Home", "Kim"),
        (91, "Paper Moon Duet", "Tony"),
        (84, "Hometown Summer", "Alex"),
    ):
        controller.scoreboard.add(points, title, singer)
    controller.phone_mic_url = "https://192.168.1.20:8766"
    web = server_app.create_app(controller, Source())
    page = (Path(server_app.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")

    @web.get("/shot/{tab}", response_class=HTMLResponse)
    def shot(tab: str) -> str:
        click = (
            f"<script>setTimeout(() => document.querySelector('nav button[data-tab={tab}]')"
            ".click(), 300);</script>"
        )
        return page.replace("</body>", click + "</body>")

    @web.get("/frame/{tab}", response_class=HTMLResponse)
    def frame(tab: str) -> str:
        # Headless Chrome will not make a window narrower than 500 px: frame a phone's width.
        return (
            "<html><body style='margin:0;background:#000'><iframe src='/shot/"
            + tab
            + "' width='390' height='844' style='border:0;display:block'></iframe></body></html>"
        )

    server = server_app.ServerThread(web, 8794, host="127.0.0.1")
    server.start()
    time.sleep(2)
    shots = []
    with tempfile.TemporaryDirectory() as folder:
        for tab in ("queue", "remote"):
            target = Path(folder) / f"{tab}.png"
            subprocess.run(
                [
                    chrome,
                    "--headless=new",
                    "--disable-gpu",
                    "--hide-scrollbars",
                    "--no-first-run",
                    f"--user-data-dir={folder}/profile",
                    "--window-size=500,844",
                    "--force-device-scale-factor=2",
                    "--virtual-time-budget=6000",
                    f"--screenshot={target}",
                    f"http://127.0.0.1:8794/frame/{tab}",
                ],
                check=True,
                capture_output=True,
            )
            shots.append(Image.open(target).crop((0, 0, 780, 1688)))
    server.stop()
    sheet = Image.new("RGBA", (780 * 2 + 60, 1688), (0, 0, 0, 0))
    sheet.paste(shots[0], (0, 0))
    sheet.paste(shots[1], (840, 0))
    sheet.thumbnail((810, 844))
    sheet.save(OUT / "phone.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phone", action="store_true", help="also the phone page (needs Chrome)")
    parser.add_argument(
        "--chrome", default="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv[:1])
    from ytktv.ui import theme

    app.setStyleSheet(theme.STYLESHEET)
    console(app)
    mv_still(app)
    demo_gif(app)
    if args.phone:
        chrome = shutil.which(args.chrome) or args.chrome
        phone(chrome)
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
