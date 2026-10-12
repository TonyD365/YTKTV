"""The live mixer: microphones -> channel strips -> main bus -> output device.

Music is played by mpv straight to the same output device; this engine adds
the microphones (and crowd effects) on top, so singers hear themselves with
effects without any extra routing.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

from ytktv.audio import devices
from ytktv.audio.dsp import Limiter, MicChain
from ytktv.audio.sfx import SfxBank
from ytktv.config import Settings
from ytktv.separation import pitch_core

log = logging.getLogger(__name__)

# 512 frames (about 10 ms at 48 kHz): small enough to sing through comfortably, large
# enough that the Python mixer never misses a deadline and crackles.
BLOCK = 512
# Keep at most this many blocks of microphone audio buffered; more is latency.
MAX_BUFFERED_BLOCKS = 2


class RingBuffer:
    """Mono float32 FIFO shared between an input and the output callback."""

    def __init__(self, capacity: int) -> None:
        self._data = np.zeros(capacity, dtype=np.float32)
        self._capacity = capacity
        self._read = 0
        self._size = 0
        self._lock = threading.Lock()

    @property
    def available(self) -> int:
        return self._size

    def write(self, samples: np.ndarray) -> None:
        n = len(samples)
        if n >= self._capacity:
            samples = samples[-self._capacity :]
            n = self._capacity
        with self._lock:
            overflow = self._size + n - self._capacity
            if overflow > 0:  # drop the oldest audio rather than fall behind
                self._read = (self._read + overflow) % self._capacity
                self._size -= overflow
            start = (self._read + self._size) % self._capacity
            first = min(n, self._capacity - start)
            self._data[start : start + first] = samples[:first]
            self._data[: n - first] = samples[first:]
            self._size += n

    def read(self, n: int, max_lag: int | None = None) -> np.ndarray:
        """Read *n* samples, zero-padded on underrun.

        When *max_lag* is given and more than that is buffered, the excess is
        skipped so latency cannot build up from clock drift between devices.
        """
        out = np.zeros(n, dtype=np.float32)
        with self._lock:
            if max_lag is not None and self._size > max_lag:
                skip = self._size - max_lag
                self._read = (self._read + skip) % self._capacity
                self._size -= skip
            take = min(n, self._size)
            first = min(take, self._capacity - self._read)
            out[:first] = self._data[self._read : self._read + first]
            out[first:take] = self._data[: take - first]
            self._read = (self._read + take) % self._capacity
            self._size -= take
        return out


class PitchTap:
    """The most recent raw microphone audio, for the scoring pitch detector."""

    def __init__(self, size: int) -> None:
        self._data = np.zeros(size, dtype=np.float32)
        self._size = size
        self._pos = 0
        self._lock = threading.Lock()

    def write(self, samples: np.ndarray) -> None:
        n = len(samples)
        if n >= self._size:
            samples, n = samples[-self._size :], self._size
        with self._lock:
            first = min(n, self._size - self._pos)
            self._data[self._pos : self._pos + first] = samples[:first]
            self._data[: n - first] = samples[first:]
            self._pos = (self._pos + n) % self._size

    def latest(self, n: int) -> np.ndarray:
        n = min(n, self._size)
        with self._lock:
            start = (self._pos - n) % self._size
            if start + n <= self._size:
                return self._data[start : start + n].copy()
            return np.concatenate((self._data[start:], self._data[: start + n - self._size]))


class Mixer:
    """Device-independent mixing maths; the engine feeds it from real streams."""

    def __init__(self, settings: Settings, sample_rate: int) -> None:
        self.settings = settings
        self.sample_rate = sample_rate
        self.chains = [MicChain(sample_rate) for _ in settings.mics]
        self.limiter = Limiter()
        self.sfx = SfxBank(sample_rate)
        self._voices: list[list[Any]] = []  # [stereo samples, position]
        self._voice_lock = threading.Lock()
        self.mic_peaks = [0.0] * len(settings.mics)
        self.master_peak = (0.0, 0.0)
        self.tap = PitchTap(int(sample_rate * 0.25))

    def trigger(self, name: str) -> bool:
        samples = self.sfx.get(name)
        if samples is None:
            return False
        with self._voice_lock:
            if len(self._voices) < 6:
                self._voices.append([samples, 0])
        return True

    def mix(self, inputs: list[np.ndarray | None], frames: int) -> np.ndarray:
        """Mix one block. ``inputs[i]`` is mic i's mono block, or None when unused."""
        settings = self.settings
        bus = np.zeros((frames, 2), dtype=np.float32)
        live = [block for block in inputs if block is not None]
        if live:
            # All microphones together, before any effects: this is what gets scored.
            self.tap.write(live[0] if len(live) == 1 else np.sum(live, axis=0))
        for i, block in enumerate(inputs):
            if block is None:
                self.mic_peaks[i] = 0.0
                continue
            chain = self.chains[i]
            bus += chain.process(
                block, settings.mics[i], settings.feedback_guard, settings.feedback_sensitivity
            )
            self.mic_peaks[i] = chain.peak
        bus *= np.float32(settings.mic_volume / 100.0)
        if self._voices:
            with self._voice_lock:
                for voice in self._voices:
                    samples, pos = voice
                    chunk = samples[pos : pos + frames]
                    bus[: len(chunk)] += chunk
                    voice[1] = pos + frames
                self._voices = [v for v in self._voices if v[1] < len(v[0])]
        bus *= np.float32(settings.master_volume / 100.0)
        bus = self.limiter.process(bus)
        if frames:
            peaks = np.max(np.abs(bus), axis=0)
            self.master_peak = (float(peaks[0]), float(peaks[1]))
        return bus


class AudioEngine:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.sample_rate = 48000
        self.mixer = Mixer(settings, self.sample_rate)
        self.error: str | None = None
        self.underruns = 0  # output blocks the mixer delivered too late
        self._lock = threading.RLock()
        self._output: Any = None
        self._inputs: list[Any] = [None] * len(settings.mics)
        self._rings: list[RingBuffer | None] = [None] * len(settings.mics)

    @property
    def running(self) -> bool:
        return self._output is not None

    def start(self) -> None:
        with self._lock:
            self._stop_locked()
            self.error = None
            self.underruns = 0
            try:
                self._start_locked()
            except Exception as exc:
                log.exception("audio engine failed to start")
                self.error = str(exc)
                self._stop_locked()

    def _start_locked(self) -> None:
        import sounddevice as sd

        settings = self.settings
        out_index = devices.find_device(settings.output_device, output=True)
        self.sample_rate = devices.default_sample_rate(out_index, output=True)
        self.mixer = Mixer(settings, self.sample_rate)

        for i, mic in enumerate(settings.mics):
            self._rings[i] = None
            if not (settings.mic_monitor and mic.enabled):
                continue
            ring = RingBuffer(self.sample_rate)

            def on_input(indata: Any, _frames: int, _time: Any, _status: Any, ring=ring) -> None:
                ring.write(indata[:, 0])

            try:
                stream = sd.InputStream(
                    device=devices.find_device(mic.device, output=False),
                    channels=1,
                    samplerate=self.sample_rate,
                    blocksize=BLOCK,
                    latency="low",
                    dtype="float32",
                    callback=on_input,
                )
                stream.start()
            except Exception as exc:
                log.warning("mic %d could not start: %s", i + 1, exc)
                self.error = f"Mic {i + 1}: {exc}"
                continue
            self._inputs[i] = stream
            self._rings[i] = ring

        self._output = sd.OutputStream(
            device=out_index,
            channels=2,
            samplerate=self.sample_rate,
            blocksize=BLOCK,
            latency="low",
            dtype="float32",
            callback=self._on_output,
        )
        self._output.start()

    def _on_output(self, outdata: Any, frames: int, _time: Any, status: Any) -> None:
        if status and getattr(status, "output_underflow", False):
            self.underruns += 1
        max_lag = frames * MAX_BUFFERED_BLOCKS
        try:
            inputs = [
                ring.read(frames, max_lag) if ring is not None else None for ring in self._rings
            ]
            outdata[:] = self.mixer.mix(inputs, frames)
        except Exception:
            # Never let an exception kill the stream; a silent block is the safe failure.
            outdata.fill(0)
            log.exception("mixer callback failed")

    def _stop_locked(self) -> None:
        for stream in [self._output, *self._inputs]:
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception:
                    log.debug("stream close failed", exc_info=True)
        self._output = None
        self._inputs = [None] * len(self.settings.mics)
        self._rings = [None] * len(self.settings.mics)

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def play_sfx(self, name: str) -> bool:
        return self.running and self.mixer.trigger(name)

    def mic_pitch(self) -> float | None:
        """The note being sung into the microphones right now (MIDI), or None."""
        if not self.running:
            return None
        samples, rate = pitch_core.decimate(
            self.mixer.tap.latest(int(self.sample_rate * 0.1)).astype(np.float64), self.sample_rate
        )
        return pitch_core.detect(samples[-pitch_core.FRAME :], rate)

    def levels(self) -> dict[str, Any]:
        return {
            "mics": list(self.mixer.mic_peaks),
            "master": list(self.mixer.master_peak),
            "notches": sum(len(chain.guard.notches) for chain in self.mixer.chains),
        }
