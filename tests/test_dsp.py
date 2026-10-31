def test_voice_changer_moves_the_pitch():
    import numpy as np

    from ytktv.audio import presets
    from ytktv.audio.dsp import VoiceChanger

    rate = 48000
    tone = np.sin(2 * np.pi * 440 * np.arange(rate) / rate).astype(np.float32)

    def main_frequency(voice):
        changer = VoiceChanger(rate)
        out = np.concatenate([changer.process(block, voice) for block in np.split(tone, 100)])
        spectrum = np.abs(np.fft.rfft(out[rate // 4 :]))
        return np.argmax(spectrum) * rate / len(out[rate // 4 :])

    assert abs(main_frequency("chipmunk") - 440 * 2 ** (7 / 12)) < 15
    assert abs(main_frequency("deep") - 440 * 2 ** (-5 / 12)) < 15
    assert np.array_equal(VoiceChanger(rate).process(tone[:480], "off"), tone[:480])
    robot = VoiceChanger(rate).process(tone[:4800], "robot")
    assert np.isfinite(robot).all() and not np.allclose(robot, tone[:4800])
    assert presets.clamp("voice", "robot") == "robot" and presets.clamp("voice", "x") == "off"
