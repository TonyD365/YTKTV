"""Lyrics written by AI (Whisper) for songs that have none: an optional download."""

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
    ) -> None:
        self.env, self._audio, self.on_done, self._run = env, audio, on_done, run
        self.folder = folder or cache_dir() / "ai-lyrics"
        self._lock = threading.Lock()
        self._waiting: list[tuple[str, str]] = []
        self._busy = False

    @property
    def installed(self) -> bool:
        return self.env.installed_variant() in VARIANTS

    def path(self, video_id: str) -> Path:
        return self.folder / f"{video_id}.json"

    def cached(self, video_id: str) -> list[LyricLine] | None:
        try:
            data = json.loads(self.path(video_id).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return [LyricLine.from_dict(line) for line in data]

    def request(self, video_id: str, language: str = "") -> None:
        """Write lyrics for *video_id* soon (nothing happens without the runtime)."""
        if not self.installed or self.cached(video_id) is not None:
            return
        with self._lock:
            if any(v == video_id for v, _ in self._waiting):
                return
            self._waiting.append((video_id, language))
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
                video_id, language = self._waiting.pop(0)
            try:
                lines = self.write(video_id, language)
            except Exception:
                log.info("AI lyrics failed for %s", video_id, exc_info=True)
                continue
            if self.on_done:
                self.on_done(video_id, lines)

    def write(self, video_id: str, language: str = "") -> list[LyricLine]:
        work = self.folder / "work" / video_id
        work.mkdir(parents=True, exist_ok=True)
        try:
            audio = self._audio(video_id, work)
            out = work / "lyrics.json"
            command = [str(self.env.python), str(WORKER), str(audio), str(out),
                       str(self.env.root / "models"), language]  # fmt: skip
            result = self._run(command, capture_output=True, text=True, timeout=TIMEOUT)
            if result.returncode != 0 or not out.exists():
                raise RuntimeError((result.stderr or "")[-400:])
            out.replace(self.path(video_id))
        finally:
            import shutil

            shutil.rmtree(work, ignore_errors=True)
        return self.cached(video_id) or []
