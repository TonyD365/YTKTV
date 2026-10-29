"""Record the MV screen while someone sings, then a party game result: video/mv.mp4."""

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
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

FPS = 30
SECONDS = 25
FRAMES = Path("video/frames_mv")
# Alexander's Ragtime Band, Irving Berlin, 1911: public domain.
LINES = [
    "Come on and hear, come on and hear",
    "Alexander's Ragtime Band",
    "Come on and hear, come on and hear",
    "It's the best band in the land",
]
DANMAKU = {1.5: "What a voice! 🎤", 3.2: "唱得好！", 5.0: "1911 bangers 🔥", 7.4: "安可！安可！"}
REACTIONS = {6.0: "👏", 6.3: "🔥", 6.6: "🎉", 6.9: "❤️", 7.2: "🌹", 7.5: "💯", 7.8: "🍻", 8.1: "🎉"}


def lyric(start: float, end: float, text: str) -> dict:
    words, offset = [], 0
    step = (end - start - 0.4) / max(1, len(text.split()))
    for k, word in enumerate(text.split()):
        words.append([start + k * step, offset])
        offset += len(word) + 1
    return {"start": start, "end": end, "text": text, "words": words}


def main() -> None:
    app = QApplication(sys.argv[:1])
    mv, notes = readme_images.mv_screen(app, 1920, 1080)
    mv.set_lyrics([lyric(1 + 3 * i, 4 + 3 * i, line) for i, line in enumerate(LINES)])
    shutil.rmtree(FRAMES, ignore_errors=True)
    FRAMES.mkdir(parents=True)
    state = {"i": 0, "fired": set()}

    def frame() -> None:
        i = state["i"]
        now = i / FPS
        song_time = 11.0 + now
        for table, act in ((DANMAKU, mv.add_danmaku), (REACTIONS, mv.add_reaction)):
            for at, value in table.items():
                if now >= at and (at, value) not in state["fired"]:
                    state["fired"].add((at, value))
                    act(value)
        if now >= 12.5 and "game" not in state["fired"]:
            state["fired"].add("game")
            mv.show_game({"title": "🎡 Next to sing", "text": "Kim & Lee", "detail": ""})
        if now >= 20.3 and "score" not in state["fired"]:
            state["fired"].add("score")
            mv.game_card.hide()  # frames run slower than real time
            board = [
                {"rank": 1, "points": 94, "title": "Alexander's Ragtime Band", "singer": "Kim"},
                {"rank": 2, "points": 88, "title": "A Perfect Day", "singer": "Alex"},
                {"rank": 3, "points": 81, "title": "Paper Moon Duet", "singer": "Sam"},
            ]
            mv.show_score(
                {
                    "points": 94,
                    "grade": "Superstar!",
                    "title": "Alexander's Ragtime Band",
                    "singer": "Kim",
                    "rank": 1,
                    "board": board,
                }
            )
        readme_images.sing(mv, notes, song_time)
        mv.pitch_lane.set_time(song_time)
        mv.lyrics.set_time(now)
        mv.danmaku.advance(1 / FPS)
        mv.reactions.advance(1 / FPS)
        readme_images.lights(mv, now)
        mv.grab().save(str(FRAMES / f"{i:05d}.png"))
        state["i"] += 1
        if state["i"] < SECONDS * FPS:
            QTimer.singleShot(1000 // FPS, frame)
        else:
            app.quit()

    QTimer.singleShot(600, frame)
    app.exec()
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
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
            "video/mv.mp4",
        ],
        check=True,
    )
    print("mv seconds:", state["i"] / FPS)


if __name__ == "__main__":
    main()
