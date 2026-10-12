from __future__ import annotations

import numpy as np
import pytest

from ytktv.audio import sfx
from ytktv.audio.dsp import Echo, Limiter, MicChain, Reverb, ThreeBandEQ, fader_gain
from ytktv.audio.engine import Mixer, RingBuffer
from ytktv.config import Settings
from ytktv.core.models import MicParams

SR = 48000
BLOCK = 256


def sine(freq: float, blocks: int = 40) -> np.ndarray:
    t = np.arange(BLOCK * blocks) / SR
    return (0.25 * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def run_blocks(process, signal: np.ndarray) -> np.ndarray:
    return np.concatenate([process(signal[i : i + BLOCK]) for i in range(0, len(signal), BLOCK)])


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def test_eq_flat_is_passthrough_and_bands_hit_their_range():
    eq = ThreeBandEQ(SR)
    low = sine(60)
    block = low[:BLOCK]
    assert eq.process(block) is block

    eq.set_gains(12.0, 0.0, 0.0)
    boosted = run_blocks(eq.process, low)
    assert rms(boosted[BLOCK * 20 :]) > rms(low) * 3  # ~ +12 dB on bass

    eq = ThreeBandEQ(SR)
    eq.set_gains(12.0, 0.0, 0.0)
    high = sine(10000)
    untouched = run_blocks(eq.process, high)
    assert rms(untouched[BLOCK * 20 :]) == pytest.approx(rms(high), rel=0.1)


def test_block_processing_matches_one_long_block():
    """Effects must keep state correctly across block boundaries."""
    signal = sine(440, blocks=80)
    for make in (lambda: Echo(SR), lambda: Reverb(SR)):
        chunked, whole = make(), make()

        def as_mono(result):
            return result if isinstance(result, np.ndarray) else result[0]

        a = run_blocks(lambda block, fx=chunked: as_mono(fx.process(block, 0.5)), signal)
        b = as_mono(whole.process(signal, 0.5))
        np.testing.assert_allclose(a, b, atol=1e-5)


def test_echo_repeats_after_the_delay():
    echo = Echo(SR, delay_ms=100)
    impulse = np.zeros(SR // 2, dtype=np.float32)
    impulse[0] = 1.0
    wet = echo.process(impulse, 1.0)
    delay = int(SR * 0.1)
    assert wet[delay] > 0.5
    assert wet[2 * delay] > 0.1
    assert np.all(wet[:delay] == 0)


def test_reverb_has_a_decaying_tail_and_stays_finite():
    reverb = Reverb(SR)
    burst = np.zeros(SR * 2, dtype=np.float32)
    burst[:2000] = sine(440, blocks=8)[:2000]
    left, right = reverb.process(burst, 1.0)
    assert np.isfinite(left).all() and np.isfinite(right).all()
    early, late = rms(left[4000:20000]), rms(left[-16000:])
    assert early > 0 and late < early
    assert not np.allclose(left, right)  # stereo spread


def test_limiter_keeps_peaks_under_the_ceiling():
    limiter = Limiter(ceiling=0.9)
    loud = np.full((BLOCK, 2), 3.0, dtype=np.float32)
    limiter.process(loud)
    out = limiter.process(loud)
    assert float(np.max(np.abs(out))) <= 0.9 + 1e-4
    quiet = np.full((BLOCK, 2), 0.1, dtype=np.float32)
    fresh = Limiter()
    assert fresh.process(quiet) is quiet


def test_fader_taper():
    assert fader_gain(0.0) == 0.0
    assert fader_gain(0.8) == pytest.approx(1.0)
    assert fader_gain(1.0) > 1.0


def test_mic_chain_mute_pan_and_shape():
    signal = sine(440, blocks=8)
    chain = MicChain(SR)
    out = np.concatenate(
        [
            chain.process(signal[i : i + BLOCK], MicParams(pan=-1.0, reverb=0, echo=0))
            for i in range(0, len(signal), BLOCK)
        ]
    )
    assert out.shape == (len(signal), 2) and out.dtype == np.float32
    assert rms(out[:, 1]) < 1e-6 < rms(out[:, 0])

    muted = MicChain(SR)
    params = MicParams(mute=True, reverb=0, echo=0)
    assert rms(muted.process(signal[:BLOCK], params)) == 0.0


def test_ring_buffer_wraps_drops_oldest_and_bounds_latency():
    ring = RingBuffer(8)
    ring.write(np.arange(6, dtype=np.float32))
    np.testing.assert_array_equal(ring.read(4), [0, 1, 2, 3])
    ring.write(np.arange(6, 12, dtype=np.float32))  # wraps
    np.testing.assert_array_equal(ring.read(8), [4, 5, 6, 7, 8, 9, 10, 11])
    np.testing.assert_array_equal(ring.read(3), [0, 0, 0])  # underrun pads with silence

    ring.write(np.arange(20, dtype=np.float32))  # overflow keeps the newest 8
    np.testing.assert_array_equal(ring.read(8), np.arange(12, 20))

    ring.write(np.arange(8, dtype=np.float32))
    np.testing.assert_array_equal(ring.read(2, max_lag=4), [4, 5])  # skipped the backlog


def test_mixer_mixes_mics_applies_volumes_and_plays_sfx():
    settings = Settings()
    mixer = Mixer(settings, SR)
    block = sine(440, blocks=1)
    out = mixer.mix([block, None, None, None], BLOCK)
    assert out.shape == (BLOCK, 2)
    assert mixer.mic_peaks[0] > 0 and mixer.mic_peaks[1] == 0
    assert mixer.master_peak[0] > 0

    settings.master_volume = 0
    assert rms(mixer.mix([block, None, None, None], BLOCK)) == 0.0

    settings.master_volume = 100
    assert mixer.trigger("applause") and not mixer.trigger("nope")
    silent = mixer.mix([None, None, None, None], BLOCK)
    assert rms(silent) > 0  # the effect is audible with no microphones


@pytest.mark.parametrize("name", sfx.SFX_NAMES)
def test_sfx_are_stereo_normalised_and_deterministic(name):
    bank = sfx.SfxBank(22050)
    samples = bank.get(name)
    assert samples is not None and samples.ndim == 2 and samples.shape[1] == 2
    assert samples.dtype == np.float32
    assert 0.3 < float(np.max(np.abs(samples))) <= 0.71
    assert bank.get(name) is samples


def test_noise_gate_silences_hiss_but_passes_singing_without_clipping_the_start():
    from ytktv.audio.dsp import NoiseGate

    gate = NoiseGate(SR)
    rng = np.random.default_rng(1)
    hiss = (rng.standard_normal(BLOCK * 40) * 0.0008).astype(np.float32)  # about -62 dBFS
    assert rms(run_blocks(gate.process, hiss)) == 0.0

    voice = sine(220, blocks=20)
    out = run_blocks(gate.process, voice)
    np.testing.assert_array_equal(out[:BLOCK], voice[:BLOCK])  # opens on the very first block
    assert gate.is_open

    # A short pause between words is held open; a long silence fades shut smoothly.
    pause = np.zeros(int(SR * 0.2), dtype=np.float32)
    run_blocks(gate.process, pause[: len(pause) // BLOCK * BLOCK])
    assert gate.is_open
    tail = run_blocks(gate.process, np.concatenate([hiss] * 4))  # 1.7 s: hold + release
    assert not gate.is_open and rms(tail[-BLOCK * 10 :]) == 0.0
    steps = np.abs(np.diff(tail))
    assert steps.max() < 0.01  # no click when it closes


def test_low_cut_removes_rumble_and_keeps_voice():
    from ytktv.audio.dsp import LowCut

    rumble, voice = sine(25), sine(300)
    low = run_blocks(LowCut(SR).process, rumble)
    mid = run_blocks(LowCut(SR).process, voice)
    assert rms(low[BLOCK * 20 :]) < rms(rumble) * 0.15
    assert rms(mid[BLOCK * 20 :]) == pytest.approx(rms(voice), rel=0.05)


def _blocks(process, signal, size=512):
    return np.concatenate(
        [process(signal[i : i + size]) for i in range(0, len(signal) - size + 1, size)]
    )


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(x * x)) + 1e-12)


def test_compressor_narrows_the_gap_between_quiet_and_loud():
    from ytktv.audio.dsp import Compressor

    t = np.arange(SR) / SR
    quiet = (0.03 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)
    loud = (0.6 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)

    def settled(signal, amount):
        compressor = Compressor(SR)
        return _blocks(lambda x: compressor.process(x, amount), signal)[SR // 2 :]

    untouched = settled(quiet, 0.0)
    assert np.array_equal(untouched, quiet[SR // 2 : SR // 2 + len(untouched)])
    gaps = [_rms_db(settled(loud, a)) - _rms_db(settled(quiet, a)) for a in (0.0, 0.25, 1.0)]
    assert gaps[0] > gaps[1] + 4 > gaps[2] + 8  # more knob, less difference
    assert _rms_db(settled(quiet, 0.5)) > _rms_db(quiet)  # quiet singing comes up
    assert _rms_db(settled(loud, 0.5)) < _rms_db(loud)  # loud singing comes down
    assert np.max(np.abs(settled(loud, 1.0))) < 1.0

    # Turning the knob to zero glides back to the untouched signal without a step.
    compressor = Compressor(SR)
    _blocks(lambda x: compressor.process(x, 1.0), loud)
    released = _blocks(lambda x: compressor.process(x, 0.0), loud)
    assert np.max(np.abs(np.diff(released))) < 0.05
    assert np.allclose(released[-512:], loud[len(released) - 512 : len(released)])


def test_feedback_guard_cuts_a_squeal_and_leaves_voices_alone():
    from ytktv.audio.dsp import FeedbackGuard

    rng = np.random.default_rng(3)
    t = np.arange(SR * 2) / SR
    squeal = 0.3 * np.minimum(1, t * 4) * np.sin(2 * np.pi * 2300 * t)
    squeal = (squeal + 0.003 * rng.standard_normal(len(t))).astype(np.float32)
    guard = FeedbackGuard(SR)
    out = _blocks(guard.process, squeal)
    assert len(guard.notches) == 1
    freq, depth = guard.notches[0]
    assert abs(freq - 2300) < 15 and depth <= -24
    assert _rms_db(out[-SR // 2 :]) < _rms_db(squeal[-SR // 2 :]) - 20
    assert _rms_db(out[: SR // 20]) > _rms_db(squeal[: SR // 20]) - 1  # not before it is found

    # A sung note has overtones and is left alone, with or without vibrato.
    for vibrato in (0.0, 0.01):
        pitch = 220 * (1 + vibrato * np.sin(2 * np.pi * 5.5 * t))
        phase = 2 * np.pi * np.cumsum(pitch) / SR
        voice = sum((0.5 ** (h - 1)) * np.sin(h * phase) for h in range(1, 12)) * 0.2
        guard = FeedbackGuard(SR)
        voice = voice.astype(np.float32)
        assert np.array_equal(_blocks(guard.process, voice), voice[: len(voice) // 512 * 512])
        assert guard.notches == []
    guard = FeedbackGuard(SR)
    _blocks(guard.process, (0.1 * rng.standard_normal(SR)).astype(np.float32))
    assert guard.notches == []  # nor is noise

    # Notches that are no longer needed are dropped.
    guard = FeedbackGuard(SR)
    _blocks(guard.process, squeal[:SR])
    assert guard.notches
    _blocks(guard.process, np.zeros(int(SR * (FeedbackGuard._KEEP_SECONDS + 1)), dtype=np.float32))
    assert guard.notches == []


def test_mic_chain_compresses_before_the_fader_and_can_switch_the_guard_off():
    from ytktv.core.models import MicParams

    t = np.arange(SR) / SR
    loud = (0.6 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)

    def level(params):
        chain = MicChain(SR)
        # A test tone is as pure as a squeal, so the guard is left out of this part.
        out = _blocks(lambda x: chain.process(x, params, False), loud)
        return _rms_db(out[SR // 2 :, 0]), chain

    base = MicParams(reverb=0.0, echo=0.0, comp=0.6, fader=0.8)
    full, chain = level(base)
    assert chain.compressor.reduction_db > 3
    lower, chain = level(MicParams(reverb=0.0, echo=0.0, comp=0.6, fader=0.5))
    # The fader only scales the result: the compressor works just as hard as before.
    assert chain.compressor.reduction_db > 3
    assert abs((full - lower) - 20 * np.log10(fader_gain(0.8) / fader_gain(0.5))) < 0.5

    squeal = (0.3 * np.sin(2 * np.pi * 2300 * t)).astype(np.float32)
    chain = MicChain(SR)
    _blocks(lambda x: chain.process(x, base, True), squeal)
    assert chain.guard.notches
    _blocks(lambda x: chain.process(x, base, False), squeal[: SR // 4])
    assert chain.guard.notches == []  # switched off: the notches are removed
