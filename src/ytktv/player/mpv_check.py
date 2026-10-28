"""Check that the mpv on this computer can do everything YTKTV asks of it."""

from __future__ import annotations

import contextlib
import logging
import math
import struct
import tempfile
import time
import wave
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

Report = Callable[[str], None]


def _tone(path: Path, frequency: float, seconds: float = 1.0, rate: int = 48000) -> None:
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        noise = 1
        frames = bytearray()
        for i in range(int(seconds * rate)):
            # A little noise on top: a perfectly repeating tone can be mistaken for
            # a compressed stream when the file is probed.
            noise = (noise * 1103515245 + 12345) & 0x7FFFFFFF
            value = int(12000 * math.sin(2 * math.pi * frequency * i / rate)) + (noise >> 24) - 64
            frames += struct.pack("<hh", value, value)
        out.writeframes(bytes(frames))


def self_test(report: Report = print) -> int:
    """Check that the mpv libraries can do everything YTKTV asks of them. 0 = fine.

    Uses the libmpv YTKTV would use (see bootstrap.find_libmpv). Nothing is shown or
    heard: picture and sound go to "null" outputs.
    """
    from ytktv import bootstrap
    from ytktv.player import mpv_player

    try:
        library = bootstrap.find_libmpv()
        report(f"libmpv: {library}")
        if library is None:
            raise RuntimeError("libmpv was not found")
        mpv = bootstrap.import_mpv()
        with tempfile.TemporaryDirectory() as folder:
            original, backing = Path(folder) / "a.wav", Path(folder) / "b.wav"
            _tone(original, 440.0, seconds=3.0)
            _tone(backing, 677.0, seconds=3.0)
            problems: list[str] = []

            def note(level: str, component: str, message: str) -> None:
                if level in ("error", "fatal"):
                    problems.append(f"{component}: {message.strip()[:200]}")

            # The "null" outputs discard picture and sound but keep real time, so the
            # three-second test tracks take that long and can be watched while they play.
            player = mpv.MPV(
                vo="null",
                ao="null",
                audio_display="no",
                idle="yes",
                ytdl=False,
                log_handler=note,
                loglevel="warn",
            )
            try:
                report(f"mpv {player.mpv_version}")
                # The same chain as during a song: both tracks merged and mixed, a
                # channel mode, the level meter, and the key change without rubberband.
                player["audio-files"] = [str(backing)]
                player["lavfi-complex"] = mpv_player._DUAL_GRAPH.format(original=1, instrumental=2)
                player.af = ",".join(
                    [
                        mpv_player._MIX_FILTER.format(original=0.5, instrumental=0.5),
                        mpv_player._PAN_FILTERS[mpv_player.VocalMode.LEFT],
                        "lavfi=[asetrate=48000*1.059463,aresample=48000,atempo=0.943874]",
                        mpv_player._LEVEL_FILTER,
                    ]
                )
                player.loadfile(str(original))
                deadline = time.monotonic() + 30
                levels, reached, started, finished = None, 0.0, False, False
                while time.monotonic() < deadline:
                    if not player.idle_active:
                        started = True
                    elif started:
                        finished = True  # played to the end
                        break
                    reached = max(reached, float(player.time_pos or 0.0))
                    if levels is None:
                        # The meter has nothing to report until sound has gone through it.
                        with contextlib.suppress(Exception):
                            levels = player._get_property("af-metadata/" + mpv_player._LEVEL_LABEL)
                    time.sleep(0.01)
            finally:
                player.terminate()
            if problems:
                raise RuntimeError("mpv reported: " + " | ".join(problems[:4]))
            if not finished or reached < 1.0:
                raise RuntimeError(f"playback did not run to the end (reached {reached:.2f} s)")
            if not levels:
                raise RuntimeError("the level meter filter gave no readings")
            report(f"Played two tracks through the full filter chain ({reached:.2f} s).")
    except Exception as exc:
        log.exception("mpv self-test failed")
        report(f"FAILED: {exc}")
        return 1
    report("mpv self-test passed")
    return 0
