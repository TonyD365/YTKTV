"""Pitch detection for singing, with numpy only.

This file is imported both by the app (to follow the microphone) and by the
separation worker (to extract the original singer's melody), and the worker may
run in a separate Python environment where the ``ytktv`` package does not
exist. So it must not import anything from ``ytktv``.

The detector is YIN (de Cheveigné & Kawahara, 2002): find the lag at which the
signal best matches a shifted copy of itself.
"""

import math

import numpy as np

# Analysis happens at a low sample rate: voices live below 1 kHz, and it keeps the cost down.
ANALYSIS_RATE = 12000
FRAME = 768  # 64 ms: more than two periods of the lowest note we accept
FMIN = 75.0  # just under a bass's low E
FMAX = 1050.0  # a soprano's high C
# A frame is "voiced" only if its best match is this good (0 = perfect periodicity).
THRESHOLD = 0.18
SILENCE_RMS = 0.004  # about -48 dBFS


def hz_to_midi(hz):
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def decimate(samples, rate):
    """Mono float samples at *rate* -> (samples at about ANALYSIS_RATE, the actual rate)."""
    step = max(1, int(round(rate / ANALYSIS_RATE)))
    if step == 1:
        return samples, float(rate)
    usable = len(samples) // step * step
    # Averaging each group of samples is a crude low-pass, which is all this needs.
    return samples[:usable].reshape(-1, step).mean(axis=1), rate / step


def detect(frame, rate):
    """MIDI note number (fractional) sung in *frame*, or None if it is not a clear pitch."""
    n = len(frame)
    frame = frame - frame.mean()
    energy = float(np.dot(frame, frame))
    if n < 64 or energy / n < SILENCE_RMS * SILENCE_RMS:
        return None
    max_lag = min(int(rate / FMIN), n // 2)
    min_lag = max(2, int(rate / FMAX))
    if max_lag <= min_lag + 2:
        return None
    # Difference function d(lag) = sum (x[i] - x[i+lag])^2, via an FFT autocorrelation.
    size = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(frame, size)
    autocorrelation = np.fft.irfft(spectrum * np.conj(spectrum))[: max_lag + 1]
    squares = np.concatenate(([0.0], np.cumsum(frame * frame)))
    lags = np.arange(max_lag + 1)
    difference = (
        (squares[n - lags] - squares[0]) + (squares[n] - squares[lags]) - 2 * autocorrelation
    )
    difference[0] = 0.0
    # Cumulative mean normalisation removes the bias towards short lags.
    running = np.cumsum(difference[1:])
    normalised = np.ones(max_lag + 1)
    normalised[1:] = difference[1:] * lags[1:] / np.maximum(running, 1e-12)

    window = normalised[min_lag : max_lag + 1]
    below = np.nonzero(window < THRESHOLD)[0]
    if len(below) == 0:
        return None
    lag = int(below[0]) + min_lag
    while lag + 1 <= max_lag and normalised[lag + 1] < normalised[lag]:
        lag += 1  # walk down to the bottom of this dip
    # Parabolic interpolation between samples for sub-sample accuracy.
    if 1 <= lag < max_lag:
        a, b, c = normalised[lag - 1], normalised[lag], normalised[lag + 1]
        denominator = a - 2 * b + c
        if abs(denominator) > 1e-12:
            lag = lag + 0.5 * (a - c) / denominator
    return hz_to_midi(rate / lag)


def track(samples, rate, hop_seconds=0.05):
    """Pitch of a whole recording: one value (MIDI or None) per *hop_seconds*."""
    samples, rate = decimate(np.asarray(samples, dtype=np.float64), rate)
    hop = rate * hop_seconds
    count = int(len(samples) / hop)
    notes = []
    for index in range(count):
        centre = int(index * hop)
        start = max(0, centre - FRAME // 2)
        notes.append(detect(samples[start : start + FRAME], rate))
    return _despeckle(notes)


def _despeckle(notes):
    """Drop isolated one-frame blips, which are detector noise rather than singing."""
    cleaned = list(notes)
    for i, note in enumerate(notes):
        if note is None:
            continue
        before = notes[i - 1] if i > 0 else None
        after = notes[i + 1] if i + 1 < len(notes) else None
        if before is None and after is None:
            cleaned[i] = None
    return cleaned


def pitch_class_distance(a, b):
    """Distance in semitones between two notes, ignoring which octave each is in."""
    difference = (a - b) % 12.0
    return min(difference, 12.0 - difference)
