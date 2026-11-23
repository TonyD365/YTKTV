from __future__ import annotations

import os
import sys
import types

import pytest

from ytktv.lyrics_ai import whisper_worker as worker


def test_worker_yields_the_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(worker.os, "name", "posix")
    monkeypatch.setattr(worker.os, "nice", calls.append, raising=False)
    monkeypatch.setattr(worker.os, "cpu_count", lambda: 8)
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        monkeypatch.delenv(name, raising=False)
    try:
        assert worker.be_gentle() == 4
        assert calls == [10]
        assert os.environ["OMP_NUM_THREADS"] == "4"
    finally:
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
            os.environ.pop(name, None)


def test_cpu_model_uses_half_the_cores(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def model(_name: str, device: str, **options: object) -> object:
        if device == "cuda":
            raise RuntimeError("no GPU")
        seen.update(options)
        return object()

    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=model))
    monkeypatch.setattr(worker.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(worker, "_MODELS", {})
    worker.load_model("models")
    assert seen["cpu_threads"] == 4
