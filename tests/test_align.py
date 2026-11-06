"""The instrumental is lined up with the original to the sample."""

from __future__ import annotations

import numpy as np
import pytest
import soundfile

from ytktv.separation import align, sep_worker

RATE = 44100


def song(seconds: float = 30.0, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    beat = (np.sin(2 * np.pi * 2 * t) > 0.95).astype(float)  # a kick twice a second
    return 0.3 * rng.standard_normal(len(t)) * beat + 0.2 * np.sin(2 * np.pi * 220 * t)


@pytest.mark.parametrize("late", [1764, -1764, 0, 7])  # 40 ms late, 40 ms early, none, 7 samples
def test_offset_finds_the_slip(late):
    original = song()
    backing = 0.8 * original + 0.05 * np.random.default_rng(2).standard_normal(len(original))
    slipped = align.shift(backing[:, None], -late, len(backing))[:, 0]  # move it *late* later
    assert align.offset(original, slipped, RATE) == late
    fixed = align.shift(slipped[:, None], late, len(original))[:, 0]
    assert len(fixed) == len(original)
    assert align.offset(original, fixed, RATE) == 0


def test_unrelated_audio_is_left_alone():
    assert (
        align.offset(song(seed=1), np.random.default_rng(9).standard_normal(30 * RATE), RATE) == 0
    )
    assert align.offset(np.zeros(RATE * 5), np.zeros(RATE * 5), RATE) == 0


def test_the_worker_aligns_both_stems_to_the_original_length(tmp_path):
    original = song(20)
    stereo = np.stack([original, original], axis=1).astype("float32")
    source = tmp_path / "source.wav"
    soundfile.write(source, stereo, RATE)
    late = 1764
    instrumental, vocals = tmp_path / "inst.flac", tmp_path / "vocals.flac"
    shifted = align.shift(stereo * 0.8, -late, len(stereo) + 300)  # late and a little long
    soundfile.write(instrumental, shifted, RATE, format="FLAC")
    soundfile.write(vocals, align.shift(stereo * 0.2, -late, len(stereo)), RATE, format="FLAC")
    sep_worker.align_stems(source, [instrumental, vocals])
    for stem in (instrumental, vocals):
        samples, rate = soundfile.read(stem, always_2d=True)
        assert rate == RATE and len(samples) == len(stereo)
        assert align.offset(original, samples.mean(axis=1), RATE) == 0
