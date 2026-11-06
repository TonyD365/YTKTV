"""Line the instrumental up with the original, to the sample.

The separator's output can sit a few milliseconds early or late (decoder priming,
the model's own padding). That is inaudible alone but audible when switching between
Original and Instrumental, so each new instrumental is shifted to match the original.

numpy only: this also runs inside the separation runtime, next to sep_worker.py.
"""

from __future__ import annotations

import numpy as np

MAX_SHIFT_SECONDS = 0.5  # anything larger is not a timing slip but a different recording
WINDOW_SECONDS = 60.0
MIN_CORRELATION = 0.3  # below this the two do not look alike: leave the instrumental alone


def offset(original: np.ndarray, instrumental: np.ndarray, rate: int) -> int:
    """How many samples *instrumental* is late against *original* (negative: early).

    Both are mono. The instrumental is most of the original, so their cross-correlation
    peaks where they line up. Returns 0 when no clear match is found.
    """
    start = int(min(10.0 * rate, max(0, len(original) - WINDOW_SECONDS * rate) / 2))
    end = start + int(WINDOW_SECONDS * rate)
    a = np.asarray(original[start:end], dtype=np.float64)
    b = np.asarray(instrumental[start:end], dtype=np.float64)
    size = min(len(a), len(b))
    if size < rate:  # under a second of audio: nothing to go on
        return 0
    a, b = a[:size] - a[:size].mean(), b[:size] - b[:size].mean()
    energy = float(np.sqrt(np.dot(a, a) * np.dot(b, b)))
    if energy == 0.0:
        return 0
    length = 1 << int(np.ceil(np.log2(2 * size)))
    spectrum = np.fft.rfft(b, length) * np.conj(np.fft.rfft(a, length))
    correlation = np.fft.irfft(spectrum, length)
    limit = int(MAX_SHIFT_SECONDS * rate)
    lags = np.concatenate([np.arange(0, limit + 1), np.arange(-limit, 0)])
    values = np.concatenate([correlation[: limit + 1], correlation[length - limit :]])
    best = int(np.argmax(values))
    if values[best] / energy < MIN_CORRELATION:
        return 0
    return int(lags[best])


def shift(samples: np.ndarray, late: int, length: int) -> np.ndarray:
    """Move *samples* (frames × channels) earlier by *late* samples and fit to *length*."""
    if late > 0:
        samples = samples[late:]
    elif late < 0:
        pad = np.zeros((-late, *samples.shape[1:]), dtype=samples.dtype)
        samples = np.concatenate([pad, samples])
    if len(samples) < length:
        pad = np.zeros((length - len(samples), *samples.shape[1:]), dtype=samples.dtype)
        samples = np.concatenate([samples, pad])
    return samples[:length]
