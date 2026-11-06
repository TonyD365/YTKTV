"""Lyrics written by AI (Whisper) from the song's own audio: an optional download.

With a GPU every song's lyrics are written here, so their timing matches the video; the
lyrics found online only help with the words. Without one, AI writes only the lyrics of
songs that have none online (a CPU is too slow to do every song).
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ytktv.config import cache_dir, data_dir
from ytktv.separation.runtime import Runtime, Variant
from ytktv.youtube.lyrics import LyricLine

log = logging.getLogger(__name__)

# NVIDIA cards run Whisper on the GPU (CUDA libraries come as pip packages); everything
# else, Apple Silicon included, on the CPU: faster-whisper has no Metal or DirectML.
VARIANTS = {
    "whisper-mlx": Variant(
        "whisper-mlx", "AI lyrics (Apple GPU)", "about 300 MB", ("mlx-whisper",), None
    ),
    "whisper-cuda": Variant(
        "whisper-cuda",
        "AI lyrics (NVIDIA GPU)",
        "about 1.3 GB",
        ("faster-whisper", "nvidia-cublas-cu12", "nvidia-cudnn-cu12==9.*"),
        None,
    ),
    "whisper": Variant("whisper", "AI lyrics (CPU)", "about 300 MB", ("faster-whisper",), None),
}
FALLBACK = {"whisper-cuda": "whisper", "whisper-mlx": "whisper"}
GPU_VARIANTS = frozenset({"whisper-cuda", "whisper-mlx"})
HINT_CHARACTERS = 600  # Whisper's prompt holds about 224 tokens; more is cut anyway


def best_variant(system: str | None = None, machine: str | None = None) -> str:
    import platform

    from ytktv.separation.runtime import detect_gpu

    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if system == "Darwin" and machine == "arm64":
        return "whisper-mlx"  # Apple Silicon: the GPU through Apple's MLX

    try:
        gpu = detect_gpu()
    except Exception:
        gpu = None
    return "whisper-cuda" if gpu is not None and gpu.cuda else "whisper"


def install(env: Runtime, report: Callable[[str], None] = lambda _line: None) -> str:
    """Install the best runtime for this computer, or the CPU one if that fails."""
    key = best_variant()
    try:
        env.install(key, report)
    except Exception:
        if key not in FALLBACK:
            raise
        log.warning("GPU AI lyrics runtime failed; installing the CPU one", exc_info=True)
        key = FALLBACK[key]
        env.install(key, report)
    return key


WORKER = Path(__file__).with_name("whisper_worker.py")
TIMEOUT = 30 * 60  # seconds for one song on a slow CPU


def runtime() -> Runtime:
    return Runtime(data_dir() / "lyrics-runtime", variants=VARIANTS)


class AiLyrics:
    """Writes lyrics in the background, one song at a time, and keeps them on disk."""

    def __init__(
        self,
        env: Runtime,
        audio: Callable[[str, Path], Path],
        on_done: Callable[[str, list[LyricLine]], None] | None = None,
        run: Callable[..., Any] = subprocess.run,
        folder: Path | None = None,
        vocals: Callable[[str], Path | None] = lambda _video_id: None,
    ) -> None:
        """*audio* fetches a song's full mix; *vocals* gives its separated singer, if any."""
        self.env, self._audio, self.on_done, self._run = env, audio, on_done, run
        self._vocals = vocals
        self.folder = folder or cache_dir() / "ai-lyrics"
        self._lock = threading.Lock()
        self._waiting: list[tuple[str, str, str]] = []
        self._busy = False

    @property
    def installed(self) -> bool:
        return self.env.installed_variant() in VARIANTS

    @property
    def on_gpu(self) -> bool:
        """Whether Whisper runs on a GPU here, fast enough to write every song's lyrics."""
        return self.env.installed_variant() in GPU_VARIANTS

    def pending(self, video_id: str) -> bool:
        with self._lock:
            return any(v == video_id for v, _, _ in self._waiting)

    def path(self, video_id: str) -> Path:
        return self.folder / f"{video_id}.json"

    def cached(self, video_id: str) -> list[LyricLine] | None:
        try:
            data = json.loads(self.path(video_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return [LyricLine.from_dict(line) for line in data]

    def request(
        self, video_id: str, language: str = "", hint: str = "", first: bool = False
    ) -> None:
        """Write lyrics for *video_id* soon (nothing happens without the runtime).

        *hint* is the song's words from elsewhere: they help Whisper spell what it hears,
        while the timing still comes from the audio. *first* jumps the queue (the song on).
        """
        if not self.installed or self.cached(video_id) is not None:
            return
        with self._lock:
            known = next((i for i, (v, _, _) in enumerate(self._waiting) if v == video_id), None)
            if known is not None:
                if first and known:
                    self._waiting.insert(0, self._waiting.pop(known))
                return
            job = (video_id, language, hint[:HINT_CHARACTERS])
            if first:
                self._waiting.insert(0, job)
            else:
                self._waiting.append(job)
            if self._busy:
                return
            self._busy = True
        threading.Thread(target=self._work, name="ytktv-ai-lyrics", daemon=True).start()

    def _work(self) -> None:
        while True:
            with self._lock:
                if not self._waiting:
                    self._busy = False
                    return
                video_id, language, hint = self._waiting.pop(0)
            try:
                lines = self.write(video_id, language, hint)
            except Exception:
                log.info("AI lyrics failed for %s", video_id, exc_info=True)
                continue
            if self.on_done:
                self.on_done(video_id, lines)

    def write(self, video_id: str, language: str = "", hint: str = "") -> list[LyricLine]:
        work = self.folder / "work" / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            audio = self._vocals(video_id) or self._audio(video_id, work)
            out = work / "lyrics.json"
            command = [str(self.env.python), str(WORKER), str(audio), str(out),
                       str(self.env.root / "models"), language]  # fmt: skip
            if hint:
                prompt = work / "hint.txt"
                prompt.write_text(hint, encoding="utf-8")
                command.append(str(prompt))
            result = self._run(command, capture_output=True, text=True, timeout=TIMEOUT)
            if result.returncode != 0 or not out.exists():
                raise RuntimeError((result.stderr or "")[-400:])
            out.replace(self.path(video_id))
        finally:
            import shutil

            shutil.rmtree(work, ignore_errors=True)
        return self.cached(video_id) or []
