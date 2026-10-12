"""Real-time microphone effects, block-based and vectorised with numpy/scipy.

Everything here works on small float32 blocks (typically 256 frames) and keeps
its own state between calls, so it can run inside an audio callback.
"""

from __future__ import annotations

import math

import numpy as np
from scipy.signal import lfilter, sosfilt

from ytktv.core.models import MicParams

FloatArray = np.ndarray


def db_to_gain(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def _shelf(sr: float, freq: float, gain_db: float, high: bool) -> list[float]:
    """RBJ cookbook shelving filter as one normalised second-order section."""
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq / sr
    cos, sin = math.cos(w0), math.sin(w0)
    alpha = sin / 2.0 * math.sqrt(2.0)
    root = 2.0 * math.sqrt(a) * alpha
    sign = -1.0 if high else 1.0
    b0 = a * ((a + 1) - sign * (a - 1) * cos + root)
    b1 = sign * 2 * a * ((a - 1) - sign * (a + 1) * cos)
    b2 = a * ((a + 1) - sign * (a - 1) * cos - root)
    a0 = (a + 1) + sign * (a - 1) * cos + root
    a1 = -sign * 2 * ((a - 1) + sign * (a + 1) * cos)
    a2 = (a + 1) + sign * (a - 1) * cos - root
    return [b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]


def _peak(sr: float, freq: float, gain_db: float, q: float) -> list[float]:
    a = 10.0 ** (gain_db / 40.0)
    w0 = 2.0 * math.pi * freq / sr
    alpha = math.sin(w0) / (2.0 * q)
    cos = math.cos(w0)
    a0 = 1 + alpha / a
    return [
        (1 + alpha * a) / a0,
        -2 * cos / a0,
        (1 - alpha * a) / a0,
        1.0,
        -2 * cos / a0,
        (1 - alpha / a) / a0,
    ]


def _high_pass(sr: float, freq: float) -> list[float]:
    """Second-order Butterworth high-pass as one normalised section."""
    w0 = 2.0 * math.pi * freq / sr
    alpha = math.sin(w0) / math.sqrt(2.0)
    cos = math.cos(w0)
    a0 = 1 + alpha
    return [
        (1 + cos) / 2 / a0,
        -(1 + cos) / a0,
        (1 + cos) / 2 / a0,
        1.0,
        -2 * cos / a0,
        (1 - alpha) / a0,
    ]


class ThreeBandEQ:
    """LOW shelf (120 Hz), MID peak (1.5 kHz) and HIGH shelf (8 kHz)."""

    def __init__(self, sample_rate: float, low_cut_hz: float | None = None) -> None:
        self.sample_rate = sample_rate
        # An optional high-pass runs in the same filter call as the EQ bands: one pass
        # through the block instead of two.
        self._prefix = [_high_pass(sample_rate, low_cut_hz)] if low_cut_hz else []
        self._gains = (0.0, 0.0, 0.0)
        self._sos = self._design(*self._gains)
        self._zi = np.zeros((len(self._sos), 2), dtype=np.float64)

    def _design(self, low: float, mid: float, high: float) -> FloatArray:
        sr = self.sample_rate
        if (low, mid, high) == (0.0, 0.0, 0.0):
            bands = []  # flat: only the low cut (if any) needs to run
        else:
            bands = [
                _shelf(sr, 120.0, low, high=False),
                _peak(sr, 1500.0, mid, q=0.8),
                _shelf(sr, 8000.0, high, high=True),
            ]
        return np.array([*self._prefix, *bands], dtype=np.float64).reshape(-1, 6)

    def set_gains(self, low_db: float, mid_db: float, high_db: float) -> None:
        gains = (low_db, mid_db, high_db)
        if gains != self._gains:
            flat_changed = (gains == (0.0, 0.0, 0.0)) != (self._gains == (0.0, 0.0, 0.0))
            self._gains = gains
            self._sos = self._design(*gains)
            if flat_changed:  # the number of sections changed; keep the low cut's state
                zi = np.zeros((len(self._sos), 2), dtype=np.float64)
                keep = len(self._prefix)
                zi[:keep] = self._zi[:keep]
                self._zi = zi

    def process(self, x: FloatArray) -> FloatArray:
        if len(self._sos) == 0:
            return x
        y, self._zi = sosfilt(self._sos, x, zi=self._zi)
        return y.astype(np.float32, copy=False)


class Echo:
    """A single feedback delay line: the classic KTV 'echo' knob."""

    def __init__(self, sample_rate: float, delay_ms: float = 260.0) -> None:
        self._buf = np.zeros(max(1, int(sample_rate * delay_ms / 1000.0)), dtype=np.float32)
        self._pos = 0

    def process(self, x: FloatArray, amount: float) -> FloatArray:
        """Return only the wet signal; *amount* is 0..1."""
        feedback = 0.2 + 0.4 * amount
        buf, size, n = self._buf, len(self._buf), len(x)
        wet = np.empty(n, dtype=np.float32)
        i = 0
        while i < n:
            k = min(n - i, size - self._pos)
            segment = buf[self._pos : self._pos + k]
            wet[i : i + k] = segment
            # Keep feeding the line even at amount 0 so turning the knob up is click-free.
            segment *= feedback
            segment += x[i : i + k]
            self._pos = (self._pos + k) % size
            i += k
        wet *= amount * 0.7
        return wet


class _Comb:
    def __init__(self, size: int, feedback: float, damp: float) -> None:
        self.buf = np.zeros(size, dtype=np.float32)
        self.pos = 0
        self.feedback = feedback
        self._b = np.array([1.0 - damp])
        self._a = np.array([1.0, -damp])
        self._zi = np.zeros(1)

    def process(self, x: FloatArray, out: FloatArray) -> None:
        buf, size, n = self.buf, len(self.buf), len(x)
        i = 0
        while i < n:
            k = min(n - i, size - self.pos)
            segment = buf[self.pos : self.pos + k]
            out[i : i + k] += segment
            damped, self._zi = lfilter(self._b, self._a, segment, zi=self._zi)
            segment[:] = x[i : i + k] + self.feedback * damped
            self.pos = (self.pos + k) % size
            i += k


class _Allpass:
    def __init__(self, size: int) -> None:
        self.buf = np.zeros(size, dtype=np.float32)
        self.pos = 0

    def process(self, x: FloatArray) -> FloatArray:
        buf, size, n = self.buf, len(self.buf), len(x)
        y = np.empty(n, dtype=np.float32)
        i = 0
        while i < n:
            k = min(n - i, size - self.pos)
            segment = buf[self.pos : self.pos + k]
            chunk = x[i : i + k]
            y[i : i + k] = segment - chunk
            segment *= 0.5
            segment += chunk
            self.pos = (self.pos + k) % size
            i += k
        return y


class Reverb:
    """Freeverb-style hall: parallel damped combs into stereo all-pass chains."""

    _COMBS = (1116, 1188, 1277, 1356, 1422, 1491)
    _ALLPASS_L = (556, 441, 341)
    _ALLPASS_R = (579, 464, 364)

    def __init__(self, sample_rate: float, room: float = 0.84, damp: float = 0.25) -> None:
        scale = sample_rate / 44100.0
        self._combs = [_Comb(int(d * scale), room, damp) for d in self._COMBS]
        self._left = [_Allpass(int(d * scale)) for d in self._ALLPASS_L]
        self._right = [_Allpass(int(d * scale)) for d in self._ALLPASS_R]

    def process(self, x: FloatArray, amount: float) -> tuple[FloatArray, FloatArray]:
        """Return the wet (left, right) signals; *amount* is 0..1."""
        scaled = x * np.float32(0.03)
        mono = np.zeros(len(x), dtype=np.float32)
        for comb in self._combs:
            comb.process(scaled, mono)
        left = right = mono
        for allpass in self._left:
            left = allpass.process(left)
        for allpass in self._right:
            right = allpass.process(right)
        wet = np.float32(amount * 1.6)
        return left * wet, right * wet


class LowCut:
    """80 Hz high-pass: removes handling rumble and mains hum without touching voices."""

    def __init__(self, sample_rate: float, freq: float = 80.0) -> None:
        self._sos = np.array([_high_pass(sample_rate, freq)])
        self._zi = np.zeros((1, 2))

    def process(self, x: FloatArray) -> FloatArray:
        y, self._zi = sosfilt(self._sos, x, zi=self._zi)
        return y.astype(np.float32, copy=False)


class NoiseGate:
    """Closes the channel while nobody is singing, so an open mic adds no hiss or room noise.

    Opens instantly, holds through short pauses, then fades shut. The open and
    close thresholds differ so a level hovering near one of them cannot chatter.
    """

    def __init__(
        self,
        sample_rate: float,
        open_db: float = -45.0,
        close_db: float = -52.0,
        hold_seconds: float = 0.4,
        release_seconds: float = 0.25,
    ) -> None:
        self.sample_rate = sample_rate
        self._open = db_to_gain(open_db)
        self._close = db_to_gain(close_db)
        self._hold = int(hold_seconds * sample_rate)
        self._release = release_seconds * sample_rate
        self._held = 0
        self._gain = 0.0
        self.is_open = False

    def process(self, x: FloatArray) -> FloatArray:
        n = len(x)
        if n == 0:
            return x
        level = math.sqrt(float(np.dot(x, x)) / n)
        if level >= self._open:
            self.is_open = True
            self._held = self._hold
        elif self.is_open and level < self._close:
            self._held -= n
            if self._held <= 0:
                self.is_open = False
        previous = self._gain
        # Snap open (the first syllable must not be clipped off); fade shut.
        target = 1.0 if self.is_open else max(0.0, previous - n / self._release)
        self._gain = target
        if previous == target:
            return x if target == 1.0 else x * np.float32(target)
        start = target if self.is_open else previous
        return x * np.linspace(start, target, n, dtype=np.float32)


class Limiter:
    """Block-wise brick-wall limiter with instant attack and smooth release."""

    def __init__(self, ceiling: float = 0.98, release: float = 0.08) -> None:
        self.ceiling = ceiling
        self.release = release
        self._gain = 1.0

    def process(self, block: FloatArray) -> FloatArray:
        peak = float(np.max(np.abs(block))) if block.size else 0.0
        target = min(1.0, self.ceiling / peak) if peak > 0 else 1.0
        previous = self._gain
        if target < previous:
            self._gain = target
        else:
            self._gain = previous + (target - previous) * self.release
        if previous == 1.0 and self._gain == 1.0:
            return block
        ramp = np.linspace(min(previous, target), self._gain, len(block), dtype=np.float32)
        return block * (ramp[:, None] if block.ndim == 2 else ramp)


class Compressor:
    """One-knob compressor: evens out a voice so quiet words are heard and loud ones do not jump.

    Works block by block: the level of each block sets a gain, and the gain glides
    from the previous block's value so there are no steps. Turning the knob up lowers
    the threshold, raises the ratio and adds make-up gain together.
    """

    def __init__(self, sample_rate: float, attack: float = 0.005, release: float = 0.15) -> None:
        self.sample_rate = sample_rate
        self._attack, self._release = attack, release
        self._level_db = -90.0
        self._gain = 1.0
        self.reduction_db = 0.0  # how much the last block was turned down, for meters

    def process(self, x: FloatArray, amount: float) -> FloatArray:
        n = len(x)
        if amount <= 0.0 or n == 0:
            if self._gain == 1.0:
                self.reduction_db = 0.0
                return x
            amount = 0.0  # glide back to unity once, then the branch above takes over
        peak = float(np.max(np.abs(x))) if n else 0.0
        level_db = 20.0 * math.log10(peak) if peak > 1e-5 else -100.0
        seconds = n / self.sample_rate
        rate = self._attack if level_db > self._level_db else self._release
        self._level_db += (level_db - self._level_db) * (1.0 - math.exp(-seconds / rate))
        threshold = -12.0 - 14.0 * amount
        ratio = 1.0 + 5.0 * amount
        over = max(0.0, self._level_db - threshold)
        self.reduction_db = over * (1.0 - 1.0 / ratio)
        target = db_to_gain(10.0 * amount - self.reduction_db) if amount > 0.0 else 1.0
        previous, self._gain = self._gain, target
        if abs(previous - target) < 1e-4:
            return x if target == 1.0 else x * np.float32(target)
        return x * np.linspace(previous, target, n, dtype=np.float32)


class FeedbackGuard:
    """Finds the squeal of a microphone feeding back and cuts just that frequency.

    Feedback is a single pure tone that keeps going. The recent input is examined
    about fifty times a second; when one frequency stands far above everything else,
    has no overtones (a voice always has them) and stays put for about a tenth of a
    second, a narrow notch is put on it. If it keeps squealing the notch deepens.
    Notches that are no longer needed are dropped after a while.
    """

    SIZE = 2048
    HOP = 1024
    MAX_NOTCHES = 6
    _STAND_OUT_DB = 22.0  # the peak over the average of the whole spectrum
    _OVERTONE_DB = 20.0  # the peak over its own second harmonic
    _FLOOR_DB = -45.0  # quieter tones than this are left alone
    _FRAMES = 5  # how many looks in a row before acting
    _KEEP_SECONDS = 20.0

    def __init__(self, sample_rate: float) -> None:
        self.sample_rate = sample_rate
        self._buffer = np.zeros(self.SIZE, dtype=np.float32)
        self._window = np.hanning(self.SIZE).astype(np.float32)
        self._scale = 2.0 / float(np.sum(self._window))
        self._pending = 0
        self._clock = 0  # samples seen
        self._suspect = (-1, 0)  # (spectrum bin, looks in a row)
        self._notches: list[list[float]] = []  # [frequency, depth in dB, last needed at]
        self._sos = np.zeros((0, 6))
        self._zi = np.zeros((0, 2))
        low, high = 150.0, min(10000.0, sample_rate * 0.45)
        self._first = int(low * self.SIZE / sample_rate)
        self._last = int(high * self.SIZE / sample_rate)

    @property
    def notches(self) -> list[tuple[float, float]]:
        """(frequency in Hz, depth in dB) of every notch in use."""
        return [(freq, depth) for freq, depth, _at in self._notches]

    def reset(self) -> None:
        self._notches.clear()
        self._rebuild()
        self._suspect = (-1, 0)

    def _rebuild(self) -> None:
        sections = [_peak(self.sample_rate, f, depth, q=25.0) for f, depth, _at in self._notches]
        self._sos = np.array(sections, dtype=np.float64).reshape(-1, 6)
        zi = np.zeros((len(sections), 2))
        keep = min(len(zi), len(self._zi))
        zi[:keep] = self._zi[:keep]
        self._zi = zi

    def _look(self) -> None:
        spectrum = np.abs(np.fft.rfft(self._buffer * self._window))
        band = spectrum[self._first : self._last]
        k = int(np.argmax(band)) + self._first
        peak = float(spectrum[k])
        level_db = 20.0 * math.log10(max(peak * self._scale, 1e-9))
        mean = float(np.mean(band * band))
        stands_out = 10.0 * math.log10(max(peak * peak, 1e-18) / max(mean, 1e-18))
        overtone = (
            float(np.max(spectrum[2 * k - 2 : 2 * k + 3])) if 2 * k + 3 < len(spectrum) else 0.0
        )
        pure = 20.0 * math.log10(max(peak, 1e-9) / max(overtone, 1e-9))
        howling = (
            level_db > self._FLOOR_DB
            and stands_out > self._STAND_OUT_DB
            and pure > self._OVERTONE_DB
        )
        if not howling:
            self._suspect = (-1, 0)
        elif abs(k - self._suspect[0]) <= 1:
            self._suspect = (k, self._suspect[1] + 1)
        else:
            self._suspect = (k, 1)
        changed = False
        if self._suspect[1] >= self._FRAMES:
            # Parabolic interpolation between bins gives the frequency more exactly.
            a, b, c = (float(v) for v in spectrum[k - 1 : k + 2])
            shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) else 0.0
            freq = (k + shift) * self.sample_rate / self.SIZE
            for notch in self._notches:
                if abs(notch[0] - freq) < freq * 0.03:
                    notch[1] = max(-30.0, notch[1] - 6.0)  # still squealing: cut deeper
                    notch[2] = self._clock
                    break
            else:
                if len(self._notches) >= self.MAX_NOTCHES:
                    self._notches.remove(min(self._notches, key=lambda notch: notch[2]))
                self._notches.append([freq, -12.0, self._clock])
            self._suspect = (-1, 0)
            changed = True
        keep = self._KEEP_SECONDS * self.sample_rate
        fresh = [notch for notch in self._notches if self._clock - notch[2] < keep]
        if changed or len(fresh) != len(self._notches):
            self._notches = fresh
            self._rebuild()

    def process(self, x: FloatArray) -> FloatArray:
        n = len(x)
        if n >= self.SIZE:
            self._buffer = np.asarray(x[-self.SIZE :], dtype=np.float32).copy()
        else:
            self._buffer = np.concatenate((self._buffer[n:], x))
        self._clock += n
        self._pending += n
        if self._pending >= self.HOP:
            self._pending = 0
            self._look()
        if len(self._sos) == 0:
            return x
        y, self._zi = sosfilt(self._sos, x, zi=self._zi)
        return y.astype(np.float32, copy=False)


def fader_gain(position: float) -> float:
    """Map a 0..1 fader position to linear gain with an audio taper (0.8 = unity)."""
    if position <= 0.0:
        return 0.0
    return float((position / 0.8) ** 2.5)


class MicChain:
    """One mixer channel strip.

    feedback guard -> gate -> trim -> low cut + EQ -> compressor -> fader -> echo/reverb -> pan
    """

    def __init__(self, sample_rate: float) -> None:
        self.guard = FeedbackGuard(sample_rate)
        self.gate = NoiseGate(sample_rate)
        self.eq = ThreeBandEQ(sample_rate, low_cut_hz=80.0)  # low cut and EQ in one pass
        self.compressor = Compressor(sample_rate)
        self.echo = Echo(sample_rate)
        self.reverb = Reverb(sample_rate)
        self._trim = 1.0
        self._level = 0.0
        self.peak = 0.0  # post-fader peak of the last block, for meters

    def process(self, x: FloatArray, params: MicParams, guard: bool = True) -> FloatArray:
        """Process a mono block and return a stereo (n, 2) block."""
        n = len(x)
        if guard:
            x = self.guard.process(x)
        elif self.guard.notches:
            self.guard.reset()
        x = self.gate.process(x)
        # The trim comes before the compressor and the fader after it, as on a real
        # desk: pulling the fader down must not change how the voice is compressed.
        if params.gain != self._trim:
            x = x * np.linspace(self._trim, params.gain, n, dtype=np.float32)
            self._trim = params.gain
        elif params.gain != 1.0:
            x = x * np.float32(params.gain)
        self.eq.set_gains(params.low_db, params.mid_db, params.high_db)
        x = self.compressor.process(self.eq.process(x), params.comp)
        target = 0.0 if params.mute else fader_gain(params.fader)
        if target != self._level:
            x = x * np.linspace(self._level, target, n, dtype=np.float32)
            self._level = target
        elif target != 1.0:
            x = x * np.float32(target)
        dry = x
        dry = dry + self.echo.process(dry, params.echo)
        wet_l, wet_r = self.reverb.process(dry, params.reverb)
        angle = (params.pan + 1.0) * math.pi / 4.0
        out = np.empty((n, 2), dtype=np.float32)
        # Equal-power pan, scaled so centre is unity.
        out[:, 0] = dry * np.float32(math.cos(angle) * math.sqrt(2.0)) + wet_l
        out[:, 1] = dry * np.float32(math.sin(angle) * math.sqrt(2.0)) + wet_r
        self.peak = float(np.max(np.abs(out))) if n else 0.0
        return out
