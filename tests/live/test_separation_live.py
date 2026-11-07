"""The real separation worker with the real model: a short song in, its instrumental (and
vocals) out. Needs the separation extra (audio-separator); downloads the model the first
time into YTKTV_MODEL_DIR (cached by area-tests.yml)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pytest

from ytktv.config import Settings

pytest.importorskip("audio_separator")
WORKER = Path(__file__).resolve().parents[2] / "src" / "ytktv" / "separation" / "sep_worker.py"


def song(path: Path, seconds: float = 8.0, rate: int = 44100) -> None:
    """A "voice" gliding over a steady chord, in stereo."""
    t = np.arange(int(seconds * rate)) / rate
    chord = sum(np.sin(2 * np.pi * f * t) for f in (130.8, 164.8, 196.0)) * 0.12
    voice = np.sin(2 * np.pi * (440 + 60 * np.sin(2 * np.pi * 0.5 * t)) * t) * 0.3
    mono = np.clip(chord + voice, -1, 1)
    frames = (np.stack([mono, mono], axis=1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(frames.tobytes())


def test_the_worker_separates_a_song_with_the_real_model(tmp_path):
    source, output = tmp_path / "song.wav", tmp_path / "out" / "instrumental.flac"
    song(source)
    model_dir = os.environ.get("YTKTV_MODEL_DIR") or str(tmp_path / "models")
    worker = subprocess.Popen(
        [sys.executable, str(WORKER), "--model", Settings().separation_model,
         "--model-dir", model_dir, "--work-dir", str(tmp_path / "work")],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )  # fmt: skip
    assert worker.stdin and worker.stdout
    try:
        replies = []
        worker.stdin.write(json.dumps({"source": str(source), "output": str(output)}) + "\n")
        worker.stdin.flush()
        for line in worker.stdout:
            if line.startswith("@@YTKTV "):
                replies.append(json.loads(line[8:]))
                if "ok" in replies[-1]:
                    break
        assert replies[0]["event"] == "ready", replies
        assert replies[-1] == {"ok": True}, replies
    finally:
        worker.kill()
    assert output.stat().st_size > 10_000
    assert (output.parent / "vocals.partial.flac").exists()
