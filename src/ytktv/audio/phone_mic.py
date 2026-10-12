"""Phones used as microphones: audio arrives over the network instead of a sound card.

A phone sends raw 16-bit sound in small packets. The network delivers them unevenly
and the phone's clock never matches the computer's exactly, so each phone gets a short
buffer: playing starts once a few milliseconds are waiting, and anything beyond a
limit is skipped so that delay cannot pile up.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import numpy as np

PREFIX = "Phone: "  # how these inputs are named in the mixer's device lists
NAME_LENGTH = 24
# Wait for this much sound before starting to play (it rides out uneven packets) ...
TARGET_SECONDS = 0.020
# ... and never let more than this wait, or the singer hears a growing delay.
LIMIT_SECONDS = 0.070


class Resampler:
    """Streaming linear resampler: keeps its place between packets."""

    def __init__(self, source_rate: float, target_rate: float) -> None:
        self.step = source_rate / target_rate  # input samples per output sample
        self._position = 0.0  # where the next output sample falls, in input samples
        self._last = 0.0  # the final sample of the previous packet

    def process(self, samples: np.ndarray) -> np.ndarray:
        if self.step == 1.0 or len(samples) == 0:
            return samples
        # Index 0 is the previous packet's last sample, so positions between two
        # packets can be interpolated as well.
        extended = np.concatenate(([self._last], samples))
        count = int(np.floor((len(samples) - self._position) / self.step)) + 1
        count = max(0, count)
        positions = self._position + self.step * np.arange(count)
        positions = positions[positions <= len(samples)]
        out = np.interp(positions, np.arange(len(extended)), extended).astype(np.float32)
        self._position = self._position + self.step * len(positions) - len(samples)
        self._last = float(samples[-1])
        return out


class PhoneSource:
    """One connected phone: its name and the sound waiting to be played."""

    def __init__(self, name: str, rate: int) -> None:
        self.name = name
        self.rate = rate  # what the mixer runs at
        self._lock = threading.Lock()
        self._chunks: list[np.ndarray] = []
        self._waiting = 0  # samples in _chunks
        self._playing = False  # False until TARGET_SECONDS have arrived
        self._resampler: Resampler | None = None
        self._source_rate = 0
        self.peak = 0.0
        self.dropped = 0  # samples skipped to keep the delay down
        self.gaps = 0  # times the buffer ran dry

    @property
    def buffered_seconds(self) -> float:
        return self._waiting / self.rate

    def set_rate(self, rate: int) -> None:
        with self._lock:
            if rate != self.rate:
                self.rate = rate
                self._chunks, self._waiting, self._playing = [], 0, False
                self._resampler = None

    def feed(self, pcm: bytes, source_rate: int) -> None:
        """Take a packet of little-endian 16-bit mono sound recorded at *source_rate*."""
        samples = np.frombuffer(pcm[: len(pcm) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
        if len(samples) == 0:
            return
        with self._lock:
            if self._resampler is None or source_rate != self._source_rate:
                self._source_rate = source_rate
                self._resampler = Resampler(source_rate, self.rate)
            samples = self._resampler.process(samples)
            self._chunks.append(samples)
            self._waiting += len(samples)
            limit = int(LIMIT_SECONDS * self.rate)
            while self._waiting > limit and self._chunks:
                # Too much is waiting (the phone's clock runs fast, or packets came in
                # a burst): skip the oldest sound rather than fall behind.
                excess = self._waiting - limit
                head = self._chunks[0]
                if len(head) <= excess:
                    self._chunks.pop(0)
                    self._waiting -= len(head)
                    self.dropped += len(head)
                else:
                    self._chunks[0] = head[excess:]
                    self._waiting -= excess
                    self.dropped += excess

    def read(self, frames: int) -> np.ndarray:
        """The next *frames* samples; silence while the buffer is filling."""
        out = np.zeros(frames, dtype=np.float32)
        with self._lock:
            if not self._playing:
                if self._waiting < int(TARGET_SECONDS * self.rate):
                    self.peak = 0.0
                    return out
                self._playing = True
            filled = 0
            while filled < frames and self._chunks:
                head = self._chunks[0]
                take = min(len(head), frames - filled)
                out[filled : filled + take] = head[:take]
                filled += take
                if take == len(head):
                    self._chunks.pop(0)
                else:
                    self._chunks[0] = head[take:]
            self._waiting -= filled
            if filled < frames:
                # Ran dry: wait for the buffer to fill again instead of stuttering.
                self._playing = False
                self.gaps += 1
        self.peak = float(np.max(np.abs(out))) if frames else 0.0
        return out


class PhoneMics:
    """Every phone that is connected as a microphone right now."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sources: dict[str, PhoneSource] = {}  # by connection key
        self.rate = 48000
        self.on_change: Callable[[], Any] | None = None

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    def set_rate(self, rate: int) -> None:
        """Called by the audio engine when it (re)starts: the rate it mixes at."""
        with self._lock:
            self.rate = rate
            for source in self._sources.values():
                source.set_rate(rate)

    def connect(self, key: str, name: str) -> PhoneSource:
        cleaned = " ".join(str(name).split())[:NAME_LENGTH] or "phone"
        with self._lock:
            taken = {source.name for k, source in self._sources.items() if k != key}
            label, number = PREFIX + cleaned, 2
            while label in taken:  # two phones with the same name stay apart
                label, number = f"{PREFIX}{cleaned} {number}", number + 1
            source = self._sources[key] = PhoneSource(label, self.rate)
        self._changed()
        return source

    def disconnect(self, key: str) -> None:
        with self._lock:
            gone = self._sources.pop(key, None)
        if gone is not None:
            self._changed()

    def names(self) -> list[str]:
        with self._lock:
            return sorted(source.name for source in self._sources.values())

    def source(self, name: str) -> PhoneSource | None:
        with self._lock:
            return next((s for s in self._sources.values() if s.name == name), None)

    def read(self, name: str, frames: int) -> np.ndarray:
        """Sound from the phone called *name*; silence when it is not connected."""
        source = self.source(name)
        return source.read(frames) if source is not None else np.zeros(frames, dtype=np.float32)


def is_phone(device: str | None) -> bool:
    return bool(device) and str(device).startswith(PREFIX)
