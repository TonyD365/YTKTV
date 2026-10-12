from __future__ import annotations

import numpy as np

from ytktv.audio.phone_mic import (
    LIMIT_SECONDS,
    PREFIX,
    TARGET_SECONDS,
    PhoneMics,
    PhoneSource,
    Resampler,
    is_phone,
)

RATE = 48000


def pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()


def tone(seconds: float, rate: int = RATE, frequency: float = 440.0, start: float = 0.0):
    t = start + np.arange(int(seconds * rate)) / rate
    return (0.5 * np.sin(2 * np.pi * frequency * t)).astype(np.float32)


def test_sound_comes_out_as_it_went_in_once_the_buffer_has_filled():
    source = PhoneSource("Phone: test", RATE)
    signal = tone(0.5)
    packet = 256
    out = []
    for start in range(0, len(signal) - packet + 1, packet):
        source.feed(pcm(signal[start : start + packet]), RATE)
        out.append(source.read(packet))
    out = np.concatenate(out)
    # Silence while the first few milliseconds collect, then the same sound, in order.
    heard = int(np.argmax(np.abs(out) > 0.01))
    lead = heard // packet * packet  # playing starts with a whole packet
    assert abs(lead - TARGET_SECONDS * RATE) <= packet
    played = out[lead : lead + 8000]
    assert np.allclose(played, signal[: len(played)], atol=1e-3)
    assert source.gaps == 0 and source.dropped == 0


def test_a_backlog_is_skipped_so_the_delay_cannot_grow():
    source = PhoneSource("Phone: test", RATE)
    source.feed(pcm(tone(0.5)), RATE)  # half a second arrives in one burst
    assert source.buffered_seconds <= LIMIT_SECONDS + 1e-6
    assert source.dropped == int(0.5 * RATE) - int(LIMIT_SECONDS * RATE)
    # What is left is the newest sound, not the oldest.
    first = source.read(64)
    expected = tone(0.5)[-int(LIMIT_SECONDS * RATE) :][:64]
    assert np.allclose(first, expected, atol=1e-3)


def test_running_dry_gives_silence_then_refills_before_playing_again():
    source = PhoneSource("Phone: test", RATE)
    source.feed(pcm(tone(0.03)), RATE)
    assert np.any(source.read(512) != 0)
    rest = source.read(2048)  # more than is waiting
    assert source.gaps == 1 and np.all(rest[-512:] == 0)
    source.feed(pcm(tone(0.005)), RATE)  # a little arrives: not enough to start yet
    assert np.all(source.read(128) == 0) and source.peak == 0.0
    source.feed(pcm(tone(0.03)), RATE)
    assert np.any(source.read(128) != 0)


def test_a_phone_recording_at_another_rate_is_resampled_in_tune():
    source = PhoneSource("Phone: test", RATE)
    out = []
    position = 0.0
    for _ in range(200):  # 44.1 kHz phone, 441 samples (10 ms) per packet
        source.feed(pcm(tone(0.01, 44100, 440.0, position)), 44100)
        position += 0.01
        out.append(source.read(480))
    out = np.concatenate(out)[RATE // 2 : RATE // 2 + 32768]
    spectrum = np.abs(np.fft.rfft(out * np.hanning(len(out))))
    peak = np.argmax(spectrum) * RATE / len(out)
    assert abs(peak - 440.0) < 2.0  # still an A, not sharp or flat
    assert source.gaps <= 1

    resampler = Resampler(44100, 48000)
    whole = resampler.process(tone(1.0, 44100))
    assert abs(len(whole) - 48000) <= 2
    pieces = Resampler(44100, 48000)
    joined = np.concatenate(
        [pieces.process(chunk) for chunk in np.array_split(tone(1.0, 44100), 37)]
    )
    assert abs(len(joined) - len(whole)) <= 1  # the same whether in one piece or many
    assert np.allclose(joined[: len(whole) - 2], whole[: len(whole) - 2], atol=1e-4)


def test_phones_are_listed_for_the_mixer_and_kept_apart_by_name():
    phones = PhoneMics()
    changes = []
    phones.on_change = lambda: changes.append(phones.names())
    first = phones.connect("a", "  Tony's   iPhone ")
    second = phones.connect("b", "Tony's iPhone")
    assert first.name == "Phone: Tony's iPhone" and second.name == "Phone: Tony's iPhone 2"
    assert phones.connect("c", "").name == "Phone: phone"
    assert phones.names() == sorted([first.name, second.name, "Phone: phone"])
    assert is_phone(first.name) and not is_phone("USB Mic") and not is_phone(None)
    assert first.name.startswith(PREFIX)

    first.feed(pcm(tone(0.05)), RATE)
    assert np.any(phones.read(first.name, 256) != 0)
    assert np.all(phones.read("Phone: nobody", 256) == 0)  # not connected: silence

    phones.set_rate(44100)  # the audio engine restarted on another output device
    assert first.rate == 44100 and first.buffered_seconds == 0

    phones.disconnect("a")
    phones.disconnect("a")  # twice is harmless
    assert first.name not in phones.names() and len(changes) == 4


def test_a_phone_streams_into_a_mixer_channel_over_https(tmp_path):
    """The whole path except the phone's own browser: TLS, the socket, the mixer."""
    import json
    import socket
    import ssl
    import time

    from websockets.sync.client import connect

    from ytktv.audio.engine import AudioEngine
    from ytktv.config import Settings
    from ytktv.server import tls
    from ytktv.server.app import ServerThread
    from ytktv.server.mic_app import create_mic_app

    settings = Settings()
    phones = PhoneMics()
    changes = []
    phones.on_change = lambda: changes.append(phones.names())
    engine = AudioEngine(settings, phones)

    certificate = tls.ensure_certificate(tmp_path / "tls", "127.0.0.1")
    assert tls.ensure_certificate(tmp_path / "tls", "127.0.0.1") == certificate  # reused
    made = certificate[0].read_bytes()
    tls.ensure_certificate(tmp_path / "tls", "192.168.7.7")  # the address changed: a new one
    assert certificate[0].read_bytes() != made
    certificate = tls.ensure_certificate(tmp_path / "tls", "127.0.0.1")

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    channel_of = {"Phone: Kim": 2}
    server = ServerThread(
        create_mic_app(phones, channel_of.get), port, host="127.0.0.1", certificate=certificate
    )
    server.start()
    try:
        insecure = ssl.create_default_context()
        insecure.check_hostname = False
        insecure.verify_mode = ssl.CERT_NONE
        deadline = time.monotonic() + 10
        while True:
            try:
                phone = connect(f"wss://127.0.0.1:{port}/ws", ssl=insecure, open_timeout=3)
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.1)
        with phone:
            phone.send(json.dumps({"ping": 12.5}))
            assert json.loads(phone.recv(timeout=3)) == {"pong": 12.5}
            phone.send(json.dumps({"name": "Kim", "rate": 44100}))
            deadline = time.monotonic() + 3
            while not phones.names() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert phones.names() == ["Phone: Kim"]

            # Channel 2 of the mixer takes this phone; no sound card is involved.
            settings.mics[0].enabled = False
            settings.mics[1].enabled, settings.mics[1].device = True, "Phone: Kim"
            engine._phone_names[1] = "Phone: Kim"
            phones.set_rate(48000)

            position, heard = 0.0, 0.0
            for _ in range(60):  # 0.6 s of a 440 Hz tone in 10 ms packets
                phone.send(pcm(tone(0.01, 44100, 440.0, position)))
                position += 0.01
            deadline = time.monotonic() + 3
            while heard < 0.05 and time.monotonic() < deadline:
                out = np.zeros((480, 2), dtype=np.float32)
                engine._on_output(out, 480, None, None)
                heard = max(heard, float(np.max(np.abs(out))))
                time.sleep(0.005)
            assert heard > 0.05  # the phone's voice came out of the mixer
            assert engine.mixer.live_mics == (1,)

            report = json.loads(phone.recv(timeout=3))
            assert report["name"] == "Phone: Kim" and report["channel"] == 2
            assert set(report) >= {"buffer_ms", "gaps", "level"}
        deadline = time.monotonic() + 3
        while phones.names() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert phones.names() == []  # hanging up removes the phone from the device lists
        assert changes[0] == ["Phone: Kim"] and changes[-1] == []
    finally:
        server.stop()


def test_mixer_lists_phones_and_keeps_one_that_left_selected(qtbot, ktv, monkeypatch):
    from ytktv.ui.mixer_panel import MixerPanel

    controller, _, _ = ktv
    monkeypatch.setattr("ytktv.audio.devices.list_inputs", lambda: ["USB Mic"])
    monkeypatch.setattr("ytktv.audio.devices.list_outputs", lambda: ["Speakers"])
    controller.phones = PhoneMics()
    controller.phones.connect("a", "Kim")
    panel = MixerPanel(controller)
    qtbot.addWidget(panel)
    panel.refresh_devices()
    strip = panel.strips[1]
    items = [strip.device.itemText(i) for i in range(strip.device.count())]
    assert items == ["Off", "System Default", "USB Mic", "Phone: Kim"]

    strip.device.setCurrentText("Phone: Kim")
    strip._device_chosen(0)
    mic = controller.settings.mics[1]
    assert mic.enabled and mic.device == "Phone: Kim"
    assert controller.phone_channel("Phone: Kim") == 2 and controller.phone_channel("x") is None
    assert controller.mixer_state()["phones"] == ["Phone: Kim"]

    controller.phones.disconnect("a")  # the phone leaves; the channel waits for it
    panel.refresh_devices()
    assert strip.device.currentText() == "Phone: Kim" and mic.device == "Phone: Kim"
