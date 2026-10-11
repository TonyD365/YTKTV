"""Synthesised crowd sound effects (no samples, so nothing to license)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from scipy.signal import butter, fftconvolve, sosfilt

SFX_NAMES = ("applause", "cheer", "airhorn", "drumroll")


def _normalise(stereo: np.ndarray, peak: float = 0.7) -> np.ndarray:
    top = float(np.max(np.abs(stereo))) or 1.0
    return (stereo * (peak / top)).astype(np.float32)


def _band(noise: np.ndarray, low: float, high: float, sr: int) -> np.ndarray:
    sos = butter(2, [low, min(high, sr / 2 - 100)], btype="band", fs=sr, output="sos")
    return sosfilt(sos, noise, axis=0)


def _claps(rng: np.random.Generator, sr: int, seconds: float, count: int) -> np.ndarray:
    n = int(sr * seconds)
    t = np.arange(n) / sr
    # Crowd swells quickly, then thins out.
    density = np.minimum(t / 0.3, 1.0) * np.exp(-np.maximum(t - seconds * 0.55, 0) * 3.0)
    density /= density.sum()
    out = np.zeros((n, 2))
    klen = int(sr * 0.02)
    decay = np.exp(-np.arange(klen) / (sr * 0.004))
    for channel in range(2):
        for _ in range(3):  # a few different "hands"
            train = np.zeros(n)
            hits = rng.choice(n, size=count // 3, p=density)
            np.add.at(train, hits, rng.uniform(0.3, 1.0, size=len(hits)))
            centre = rng.uniform(1100, 2600)
            kernel = _band(rng.standard_normal(klen), centre * 0.6, centre * 1.8, sr) * decay
            out[:, channel] += fftconvolve(train, kernel)[:n]
    return out


def applause(sr: int, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return _normalise(_claps(rng, sr, 3.5, 1500))


def cheer(sr: int, seed: int = 2) -> np.ndarray:
    rng = np.random.default_rng(seed)
    seconds = 3.5
    n = int(sr * seconds)
    t = np.arange(n) / sr
    out = _claps(rng, sr, seconds, 900) * 0.5
    envelope = np.minimum(t / 0.25, 1.0) * np.exp(-np.maximum(t - 1.6, 0) * 2.0)
    for _ in range(14):  # individual "woooo!" voices
        start = rng.uniform(380, 620)
        glide = start * (1.0 + rng.uniform(0.2, 0.6) * np.minimum(t / rng.uniform(0.3, 0.9), 1.0))
        vibrato = 1.0 + 0.012 * np.sin(2 * np.pi * rng.uniform(4, 7) * t)
        phase = 2 * np.pi * np.cumsum(glide * vibrato) / sr
        voice = np.sin(phase) + 0.4 * np.sin(2 * phase) + 0.2 * np.sin(3 * phase)
        pan = rng.uniform(0.15, 0.85)
        voice = voice * envelope * rng.uniform(0.4, 1.0)
        out[:, 0] += voice * (1 - pan) * 0.08
        out[:, 1] += voice * pan * 0.08
    crowd = _band(rng.standard_normal((n, 2)), 500, 3000, sr) * envelope[:, None]
    return _normalise(out + crowd * 0.25)


def airhorn(sr: int, seed: int = 3) -> np.ndarray:
    del seed
    blasts = [(0.0, 0.22), (0.28, 0.22), (0.56, 0.9)]
    n = int(sr * 1.6)
    t = np.arange(n) / sr
    out = np.zeros(n)
    for start, length in blasts:
        local = t - start
        gate = (local >= 0) & (local < length)
        envelope = np.clip(local / 0.01, 0, 1) * np.clip((length - local) / 0.05, 0, 1) * gate
        for freq in (466.0, 470.0, 587.0, 592.0):
            saw = 2.0 * ((freq * local) % 1.0) - 1.0
            out += saw * envelope
    sos = butter(2, 5000, btype="low", fs=sr, output="sos")
    out = sosfilt(sos, out)
    return _normalise(np.stack([out, out], axis=1), 0.6)


def drumroll(sr: int, seed: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    roll, tail = 1.8, 1.6
    n = int(sr * (roll + tail))
    out = np.zeros(n)
    hit_len = int(sr * 0.05)
    hit_env = np.exp(-np.arange(hit_len) / (sr * 0.012))
    time, interval = 0.0, 0.11
    while time < roll:
        i = int(time * sr)
        hit = _band(rng.standard_normal(hit_len), 180, 6000, sr) * hit_env
        out[i : i + hit_len] += hit * (0.4 + 0.6 * time / roll)
        interval = max(0.028, interval * 0.93)
        time += interval
    crash_start = int(roll * sr)
    crash_len = n - crash_start
    sos = butter(2, 3500, btype="high", fs=sr, output="sos")
    crash = sosfilt(sos, rng.standard_normal(crash_len)) * np.exp(
        -np.arange(crash_len) / (sr * 0.45)
    )
    kick = np.sin(2 * np.pi * 60 * np.arange(crash_len) / sr) * np.exp(
        -np.arange(crash_len) / (sr * 0.08)
    )
    out[crash_start:] += crash * 0.8 + kick * 2.0
    return _normalise(np.stack([out, out], axis=1))


_GENERATORS: dict[str, Callable[[int], np.ndarray]] = {
    "applause": applause,
    "cheer": cheer,
    "airhorn": airhorn,
    "drumroll": drumroll,
}


class SfxBank:
    """Lazily renders and caches effects at the engine's sample rate."""

    def __init__(self, sample_rate: int) -> None:
        self.sample_rate = sample_rate
        self._cache: dict[str, np.ndarray] = {}

    def get(self, name: str) -> np.ndarray | None:
        generator = _GENERATORS.get(name)
        if generator is None:
            return None
        if name not in self._cache:
            self._cache[name] = generator(self.sample_rate)
        return self._cache[name]
