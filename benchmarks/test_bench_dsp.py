"""Microphone DSP cost per audio block.

At 48 kHz a 256-frame block lasts 5.33 ms; the whole mixer has to finish well
inside that or the microphones crackle.
"""

from __future__ import annotations

import numpy as np
import pytest

from ytktv.audio.dsp import Echo, Limiter, MicChain, Reverb, ThreeBandEQ
from ytktv.audio.engine import Mixer, RingBuffer
from ytktv.config import Settings
from ytktv.core.models import MicParams

SR = 48000
REALTIME_BUDGET = {256: 256 / SR, 512: 512 / SR}


def block(frames: int) -> np.ndarray:
    rng = np.random.default_rng(0)
    return (rng.standard_normal(frames) * 0.1).astype(np.float32)


@pytest.mark.parametrize("frames", [256, 512])
def test_eq(benchmark, frames):
    eq = ThreeBandEQ(SR)
    eq.set_gains(4.0, -3.0, 6.0)
    benchmark(eq.process, block(frames))


@pytest.mark.parametrize("frames", [256, 512])
def test_echo(benchmark, frames):
    echo = Echo(SR)
    benchmark(echo.process, block(frames), 0.5)


@pytest.mark.parametrize("frames", [256, 512])
def test_reverb(benchmark, frames):
    reverb = Reverb(SR)
    benchmark(reverb.process, block(frames), 0.5)


def test_limiter(benchmark):
    limiter = Limiter()
    loud = np.tile(block(256)[:, None] * 20, (1, 2))
    benchmark(limiter.process, loud)


@pytest.mark.parametrize("frames", [256, 512])
def test_mic_chain(benchmark, frames):
    chain = MicChain(SR)
    params = MicParams(low_db=3.0, mid_db=-2.0, high_db=4.0, reverb=0.4, echo=0.3, pan=0.2)
    benchmark(chain.process, block(frames), params)


@pytest.mark.parametrize("frames", [256, 512])
def test_full_mixer_four_mics(benchmark, frames):
    """Worst case: all four channels live with EQ, echo and reverb, plus a crowd effect."""
    settings = Settings()
    for mic in settings.mics:
        mic.enabled = True
        mic.low_db, mic.mid_db, mic.high_db = 3.0, -2.0, 4.0
    mixer = Mixer(settings, SR)
    inputs = [block(frames) for _ in settings.mics]

    def run():
        if not mixer._voices:
            mixer.trigger("applause")
        return mixer.mix(inputs, frames)

    benchmark(run)
    # Hard guard, independent of the base-vs-head comparison: stay under half the block time.
    assert benchmark.stats.stats.median < REALTIME_BUDGET[frames] * 0.5


def test_ring_buffer_round_trip(benchmark):
    ring = RingBuffer(SR)
    data = block(256)

    def run():
        ring.write(data)
        return ring.read(256, 768)

    benchmark(run)
