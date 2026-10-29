"""Cut the recorded clips into the 45-second promo: video/ytktv-promo.mp4.

usage: compose.py ORIGINAL.wav INSTRUMENTAL.wav  (the same 45 s+ of the song, two stems)
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import imageio_ffmpeg
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication

W, H = 1920, 1080
CLIP = (1600, 900, 160, 22)  # width, height, x, y of the app footage
OUT = Path("video/parts")
FF = imageio_ffmpeg.get_ffmpeg_exe()
SWITCH = 22.5  # when the Instrumental key is pressed in the cut
# (seconds, source, start in source, English, Chinese)
SHOTS = [
    (4.0, "intro", 0, "", ""),
    (7.0, "video/console_search.mp4", 0.3, "Pick songs on the console", "在点歌台点歌"),
    (
        4.0,
        "docs/images/phone.png",
        0,
        "…or from any phone: scan the QR code. A phone can even be your mic",
        "或者手机扫码点歌，手机还能当麦克风",
    ),
    (
        6.0,
        "video/mv.mp4",
        0,
        "🎤 A 1911 recording, with the original singers",
        "一首 1911 年的老唱片，带原唱",
    ),
    (
        3.5,
        "video/console_party.mp4",
        0,
        "🎵 One click: AI takes the vocals out",
        "一键 AI 去原唱，马上变伴奏",
    ),
    (
        4.0,
        "video/mv.mp4",
        6,
        "Lyrics follow you · live pitch · cheers from phones",
        "歌词逐字跟唱 · 音高线 · 手机发弹幕表情",
    ),
    (
        5.5,
        "video/console_controls.mp4",
        0,
        "Change the key · volume keys with a pop-up display",
        "一键升降调 · 音量按键，屏幕弹出音量条",
    ),
    (
        4.5,
        "video/console_party.mp4",
        2.2,
        "Party games: who sings next?",
        "派对小游戏：谁唱下一首？",
    ),
    (4.0, "video/mv.mp4", 12.2, "…and the answer pops up on the TV", "结果直接显示在电视上"),
    (
        5.5,
        "video/console_games2.mp4",
        0.2,
        "14 games: number bomb, liar's dice, random song, challenge cards…",
        "14 个小游戏：数字炸弹、大话骰、随机点歌、挑战卡……",
    ),
    (4.0, "video/mv.mp4", 20.2, "Live scores and tonight's best", "唱完打分，还有本场排行榜"),
    (
        5.5,
        "video/desk.mp4",
        0.3,
        "🛎 NEW · YTKTV Desk: one front desk for every room",
        "新：YTKTV Desk 服务台，一台管所有包厢",
    ),
    (
        5.5,
        "video/desk.mp4",
        5.8,
        "Service calls, bookings, bills and shift reports",
        "呼叫服务、预定、结账、交班报表",
    ),
    (5.0, "outro", 0, "", ""),
]


def font(size: int, bold: bool = True) -> QFont:
    f = QFont("PingFang SC", size)
    f.setBold(bold)
    return f


def background() -> QImage:
    image = QImage(W, H, QImage.Format.Format_RGB32)
    p = QPainter(image)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor("#2a0845"))
    g.setColorAt(0.55, QColor("#0b0620"))
    g.setColorAt(1, QColor("#05141f"))
    p.fillRect(0, 0, W, H, g)
    w, h, x, y = CLIP
    p.setPen(QPen(QColor(255, 61, 154, 160), 3))
    p.drawRoundedRect(QRectF(x - 3, y - 3, w + 6, h + 6), 10, 10)
    p.end()
    return image


def caption(en: str, zh: str) -> QImage:
    image = QImage(W, H, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setFont(font(40))
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 928, W, 70), Qt.AlignmentFlag.AlignCenter, en)
    p.setFont(font(28, False))
    p.setPen(QColor("#2ee6ff"))
    p.drawText(QRectF(0, 995, W, 60), Qt.AlignmentFlag.AlignCenter, zh)
    p.end()
    return image


def card(kind: str) -> QImage:
    image = QImage(W, H, QImage.Format.Format_RGB32)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, W, H)
    g.setColorAt(0, QColor("#3a0b5c"))
    g.setColorAt(1, QColor("#05030f"))
    p.fillRect(0, 0, W, H, g)
    icon = QImage("src/ytktv/ui/assets/icon.png")
    if not icon.isNull():
        p.drawImage(QRectF(W / 2 - 110, 150, 220, 220), icon)
    lines = (
        [
            ("YTKTV", 150, "#ff3d9a"),
            ("Turn any computer into a KTV", 56, "white"),
            ("把任何电脑变成 KTV 包厢", 40, "#2ee6ff"),
        ]
        if kind == "intro"
        else [
            ("YTKTV", 130, "#ff3d9a"),
            ("Free · macOS · Windows · Linux", 52, "white"),
            ("免费 · 支持 Mac / Windows / Linux", 36, "#c9c3e6"),
            ("github.com/TonyD365/YTKTV", 54, "#2ee6ff"),
        ]
    )
    y = 400
    for text, size, colour in lines:
        p.setFont(font(size, size > 38))
        p.setPen(QColor(colour))
        p.drawText(QRectF(0, y, W, size * 1.6), Qt.AlignmentFlag.AlignCenter, text)
        y += int(size * 1.6) + 10
    p.end()
    return image


def run(*args: str) -> None:
    subprocess.run([FF, "-v", "error", "-y", *args], check=True)


def main() -> None:
    original, instrumental = sys.argv[1], sys.argv[2]
    app = QApplication(sys.argv[:1])  # noqa: F841 - fonts need a QApplication
    OUT.mkdir(parents=True, exist_ok=True)
    background().save(str(OUT / "bg.png"))
    enc = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30", "-crf", "18"]
    parts = []
    for n, (secs, source, start, en, zh) in enumerate(SHOTS):
        part = OUT / f"{n:02d}.mp4"
        fade = f"fade=in:st=0:d=0.35,fade=out:st={secs - 0.35}:d=0.35"
        if source in ("intro", "outro"):
            card(source).save(str(OUT / f"{source}.png"))
            zoom = "1.12-0.12*min(on/24\\,1)" if source == "intro" else "1+0.0008*on"
            run(
                "-framerate",
                "30",
                "-loop",
                "1",
                "-t",
                str(secs),
                "-i",
                str(OUT / f"{source}.png"),
                "-vf",
                f"scale=2304:-2,zoompan=z='{zoom}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2'"
                f":d=1:s={W}x{H}:fps=30,{fade}",
                "-t",
                str(secs),
                *enc,
                str(part),
            )
        else:
            caption(en, zh).save(str(OUT / f"cap{n}.png"))
            w, h, x, y = CLIP
            if source.endswith(".png"):
                clip = ["-framerate", "30", "-loop", "1", "-t", str(secs), "-i", source]
                moving = (
                    f"[1]scale=-2:{h},zoompan=z='1+0.0012*on':x='iw/2-iw/zoom/2'"
                    f":y='ih/2-ih/zoom/2':d=1:s={w}x{h}:fps=30"
                )
                moving = (
                    f"[1]scale={w * 2}:-2,crop=iw:ih,"
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                    f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x0b0620"
                )
            else:
                clip = ["-ss", str(start), "-t", str(secs), "-i", source]
                moving = f"[1]scale={w}:{h}"
            run(
                "-framerate",
                "30",
                "-loop",
                "1",
                "-t",
                str(secs),
                "-i",
                str(OUT / "bg.png"),
                *clip,
                "-framerate",
                "30",
                "-loop",
                "1",
                "-t",
                str(secs),
                "-i",
                str(OUT / f"cap{n}.png"),
                "-filter_complex",
                f"{moving},setpts=PTS-STARTPTS[c];[0][c]overlay={x}:{y}[b];"
                f"[2]format=rgba,fade=in:st=0.25:d=0.4:alpha=1[t];"
                f"[b][t]overlay=0:'max(0,30-(t-0.25)*90)'[v];[v]{fade}",
                "-t",
                str(secs),
                *enc,
                str(part),
            )
        parts.append(part)
    (OUT / "list.txt").write_text("".join(f"file '{p.name}'\n" for p in parts))
    run(
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(OUT / "list.txt"),
        "-c",
        "copy",
        str(OUT / "video.mp4"),
    )
    total = sum(s[0] for s in SHOTS)
    run(
        "-i",
        original,
        "-i",
        instrumental,
        "-filter_complex",
        f"[0]atrim=0:{SWITCH + 0.15},afade=out:st={SWITCH - 0.05}:d=0.2[a];"
        f"[1]atrim={SWITCH}:{total},asetpts=PTS-STARTPTS,afade=in:d=0.15,"
        f"afade=out:st={total - SWITCH - 3}:d=3[b];[a][b]concat=n=2:v=0:a=1,loudnorm=I=-16[o]",
        "-map",
        "[o]",
        "-ar",
        "48000",
        str(OUT / "audio.wav"),
    )
    run(
        "-i",
        str(OUT / "video.mp4"),
        "-i",
        str(OUT / "audio.wav"),
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        "-movflags",
        "+faststart",
        "video/ytktv-promo.mp4",
    )
    print("seconds:", total)


if __name__ == "__main__":
    main()
