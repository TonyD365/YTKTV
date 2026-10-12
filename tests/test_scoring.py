from __future__ import annotations

import json
import math

import numpy as np
import pytest

from tests.helpers import make_controller, make_song, wait_for
from tests.test_controller import FakeStems
from ytktv.audio.engine import Mixer, PitchTap
from ytktv.config import Settings
from ytktv.core.models import PlayStatus, StemStatus
from ytktv.core.scoring import MIN_FRAMES, Melody, ScoreKeeper, grade_for
from ytktv.separation import pitch_core
from ytktv.separation.base import FakeSeparator
from ytktv.separation.cache import StemCache
from ytktv.separation.worker import StemManager

SR = 48000


def voice(midi: float, seconds: float = 0.3) -> np.ndarray:
    """A voice-like tone (a few harmonics) at a MIDI note."""
    hz = 440.0 * 2 ** ((midi - 69) / 12)
    t = np.arange(int(SR * seconds)) / SR
    return (
        0.2 * sum(a * np.sin(2 * np.pi * hz * (k + 1) * t) for k, a in enumerate((1, 0.5, 0.3)))
    ).astype(np.float32)


def detect(samples: np.ndarray) -> float | None:
    reduced, rate = pitch_core.decimate(samples.astype(np.float64), SR)
    return pitch_core.detect(reduced[: pitch_core.FRAME], rate)


@pytest.mark.parametrize("midi", [40, 48, 57, 60, 64, 69, 76, 83])
def test_detects_sung_notes_across_the_vocal_range(midi):
    assert detect(voice(midi)) == pytest.approx(midi, abs=0.1)


def test_silence_and_noise_are_not_notes():
    assert detect(np.zeros(SR // 4, dtype=np.float32)) is None
    rng = np.random.default_rng(0)
    assert detect((rng.standard_normal(SR // 4) * 0.1).astype(np.float32)) is None
    assert detect(voice(60) * 0.001) is None  # too quiet to be someone singing
    noisy = voice(57) + (rng.standard_normal(len(voice(57))) * 0.02).astype(np.float32)
    assert detect(noisy) == pytest.approx(57, abs=0.2)


def test_track_follows_a_melody_with_a_rest_and_drops_blips():
    song = np.concatenate([voice(57, 1.0), np.zeros(SR // 2, dtype=np.float32), voice(64, 1.0)])
    notes = pitch_core.track(song, SR, 0.05)
    assert len(notes) == 50
    assert notes[10] == pytest.approx(57, abs=0.2) and notes[40] == pytest.approx(64, abs=0.2)
    assert all(note is None for note in notes[22:28])
    assert pitch_core._despeckle([None, 60.0, None, 61.0, 61.0, None]) == [
        None,
        None,
        None,
        61.0,
        61.0,
        None,
    ]


def test_pitch_class_distance_ignores_octaves():
    assert pitch_core.pitch_class_distance(60, 72) == 0
    assert pitch_core.pitch_class_distance(60, 49) == pytest.approx(1)
    assert pitch_core.pitch_class_distance(60.5, 59.5) == pytest.approx(1)
    assert pitch_core.pitch_class_distance(60, 66) == pytest.approx(6)  # as far apart as it gets


# A melody with two phrases and a gap: 20 s at 50 ms per frame.
PHRASE = (
    [60.0] * 40 + [62.0] * 40 + [64.0] * 40 + [None] * 40 + [65.0] * 60 + [64.0] * 60 + [None] * 120
)
MELODY = Melody(0.05, tuple(PHRASE))


EVERY_FRAME = range(len(PHRASE))


def sing(keeper: ScoreKeeper, note_for, frames=EVERY_FRAME, late: float = 0.0) -> None:
    for i in frames:
        target = PHRASE[i]
        # 0.105 s: the keeper allows for microphone latency, then a little into the frame.
        keeper.feed(i * 0.05 + 0.105 + late, note_for(i, target))


def test_singing_the_tune_scores_high_in_any_octave():
    exact = ScoreKeeper(MELODY)
    sing(exact, lambda i, target: target)
    octave_down = ScoreKeeper(MELODY)
    sing(octave_down, lambda i, target: None if target is None else target - 12 + 0.3)
    assert exact.result().points == 100 and exact.result().grade == "Superstar!"
    assert octave_down.result().points == 100


def test_wrong_notes_score_low_and_near_misses_get_half_credit():
    wrong = ScoreKeeper(MELODY)
    sing(wrong, lambda i, target: None if target is None else target + 6)  # a tritone off
    near = ScoreKeeper(MELODY)
    sing(near, lambda i, target: None if target is None else target + 1.6)
    assert wrong.result().accuracy < 0.2  # only the frames next to a note change can match
    assert near.result().accuracy == pytest.approx(0.5, abs=0.1)
    assert wrong.result().points < near.result().points < 100
    assert wrong.result().grade == "Keep singing!"


def test_not_singing_or_singing_too_little_gives_no_score():
    silent = ScoreKeeper(MELODY)
    sing(silent, lambda i, target: None)
    assert silent.result() is None
    brief = ScoreKeeper(MELODY)
    sing(brief, lambda i, target: target, frames=range(MIN_FRAMES - 30))
    assert brief.result() is None  # under five seconds of melody went by


def test_singing_half_the_song_scores_lower_than_the_whole():
    whole, half = ScoreKeeper(MELODY), ScoreKeeper(MELODY)
    sing(whole, lambda i, target: target)
    sing(half, lambda i, target: target if i < 120 else None)
    assert half.result().participation == pytest.approx(120 / 240, abs=0.02)
    assert half.result().accuracy == pytest.approx(1.0)
    assert 40 < half.result().points < whole.result().points


def test_slightly_late_singing_is_forgiven_but_rests_do_not_count():
    late = ScoreKeeper(MELODY)
    sing(late, lambda i, target: target, late=0.1)  # two frames behind the beat
    assert late.result().accuracy > 0.95
    chatter = ScoreKeeper(MELODY)
    sing(chatter, lambda i, target: 70.0 if target is None else target)  # noise during rests
    assert chatter.result().points == 100  # only the sung parts are judged


def test_key_change_moves_the_target_and_seeking_back_does_not_count_twice():
    shifted = ScoreKeeper(MELODY, transpose=3.0)
    sing(shifted, lambda i, target: None if target is None else target + 3)
    assert shifted.result().points == 100
    unshifted = ScoreKeeper(MELODY)
    sing(unshifted, lambda i, target: None if target is None else target + 3)
    assert unshifted.result().accuracy < 0.3

    keeper = ScoreKeeper(MELODY)
    sing(keeper, lambda i, target: target)
    before = keeper.result()
    sing(keeper, lambda i, target: target, frames=range(0, 100))  # replayed from the start
    assert keeper.result() == before
    keeper.feed(-5.0, 60.0)
    keeper.feed(9999.0, 60.0)  # outside the song: ignored


def test_grades():
    assert [grade_for(p) for p in (100, 90, 80, 70, 10)] == [
        "Superstar!",
        "Amazing!",
        "Great!",
        "Nice!",
        "Keep singing!",
    ]


def test_microphone_audio_reaches_the_detector_through_the_mixer():
    """The whole live path: mic blocks -> mixer tap -> pitch -> keeper."""
    mixer = Mixer(Settings(), SR)
    keeper = ScoreKeeper(MELODY)
    block = 512
    phase = 0.0
    for i, target in enumerate(PHRASE):
        frames = int(SR * 0.05)
        if target is None:
            audio = np.zeros(frames, dtype=np.float32)
        else:
            hz = 440.0 * 2 ** ((target - 12 - 69) / 12)  # an octave below the original
            t = phase + np.arange(frames) / SR
            audio = (0.2 * (np.sin(2 * np.pi * hz * t) + 0.4 * np.sin(4 * np.pi * hz * t))).astype(
                np.float32
            )
        phase += frames / SR
        for start in range(0, frames, block):
            chunk = audio[start : start + block]
            mixer.mix([chunk, None, None, None], len(chunk))
        recent, rate = pitch_core.decimate(mixer.tap.latest(int(SR * 0.1)).astype(np.float64), SR)
        keeper.feed(i * 0.05 + 0.105, pitch_core.detect(recent[-pitch_core.FRAME :], rate))
    result = keeper.result()
    assert result is not None and result.points >= 90 and result.participation > 0.85


def test_pitch_tap_keeps_only_the_latest_audio():
    tap = PitchTap(8)
    tap.write(np.arange(6, dtype=np.float32))
    np.testing.assert_array_equal(tap.latest(4), [2, 3, 4, 5])
    tap.write(np.arange(6, 11, dtype=np.float32))  # wraps around
    np.testing.assert_array_equal(tap.latest(8), [3, 4, 5, 6, 7, 8, 9, 10])
    tap.write(np.arange(100, dtype=np.float32))  # more than it holds
    np.testing.assert_array_equal(tap.latest(99), np.arange(92, 100))


def fake_download(video_id, dest):
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "source.wav"
    path.write_bytes(b"x" * 100)
    return path


def test_melody_is_saved_with_the_stem_only_when_scoring_wants_it(tmp_path):
    cache = StemCache(tmp_path, 10**9)
    manager = StemManager(cache, FakeSeparator(), fake_download)
    manager.process("plain")
    assert manager.pitch("plain") is None
    manager.want_pitch = True
    manager.process("scored")
    melody = Melody.load(manager.pitch("scored"))
    assert melody.hop == 0.05 and melody.notes == (60.0, 60.0, None, 62.0)
    assert not (cache.folder("scored") / "work").exists()


def test_a_song_separated_before_scoring_is_redone_quietly(tmp_path):
    cache = StemCache(tmp_path, 10**9)
    separator = FakeSeparator()
    events = []
    manager = StemManager(cache, separator, fake_download, on_change=lambda v, s: events.append(s))
    manager.process("old")
    stem = manager.path("old").read_bytes()
    events.clear()

    manager.want_pitch = True
    assert manager.request("old") == StemStatus.READY  # the instrumental stays usable
    manager.start()
    try:
        wait_for(lambda: manager.pitch("old") is not None)
    finally:
        manager.stop()
    assert manager.path("old").read_bytes() == stem
    assert StemStatus.DOWNLOADING not in events and StemStatus.SEPARATING not in events
    assert len(separator.calls) == 2


def test_failed_melody_extraction_keeps_the_stem_and_is_not_retried(tmp_path):
    class NoMelody(FakeSeparator):
        def separate(self, source, out_path, pitch_path=None):
            self.calls.append(source)
            if pitch_path is not None:
                raise RuntimeError("worker crashed")
            out_path.write_bytes(b"stem")

    cache = StemCache(tmp_path, 10**9)
    separator = NoMelody()
    manager = StemManager(cache, separator, fake_download)
    manager.process("song")
    manager.want_pitch = True
    manager.request("song")
    manager.process("song")  # what the worker thread would do
    assert manager.path("song") is not None and manager.pitch("song") is None
    assert manager.status("song") == StemStatus.READY
    manager._pending.clear()
    manager.request("song")
    assert manager._pending == []  # gave up on this one instead of looping


def melody_file(stems: FakeStems, video_id: str) -> None:
    data = {"hop": 0.05, "notes": PHRASE}
    (stems.tmp / f"{video_id}.melody.json").write_text(json.dumps(data))


def test_controller_scores_a_song_and_announces_it(tmp_path):
    stems = FakeStems(tmp_path)
    controller, player, _ = make_controller(tmp_path, stems=stems)
    controller.settings.wait_for_instrumental = False
    scores = []
    controller.bus.subscribe(lambda topic, data: scores.append(data) if topic == "score" else None)
    heard, melody_events = [], []
    controller.bus.subscribe(lambda topic, data: heard.append(data) if topic == "pitch" else None)
    controller.bus.subscribe(
        lambda topic, _d: melody_events.append(1) if topic == "melody" else None
    )
    try:
        assert stems.want_pitch is True and controller.state()["scoring"] is True
        song = make_song(1)
        stems.ready.add(song.video_id)
        melody_file(stems, song.video_id)
        controller.enqueue(song, singer="Ann")
        controller.enqueue(make_song(2))  # no melody for this one
        wait_for(lambda: controller.state()["scoring_active"])
        assert controller.status == PlayStatus.PLAYING and controller.live_score() is None

        melody = controller.melody()
        assert melody["hop"] == 0.05 and list(melody["notes"]) == PHRASE
        assert melody["transpose"] == 0.0
        controller.set_pitch(2)
        keeper, position = controller._scoring_target()
        assert keeper.transpose == 2.0 and position == controller.position
        assert controller.melody()["transpose"] == 2.0
        controller._on_sung_pitch(1.5, 62.0)
        assert heard[-1] == {"position": 1.5, "note": 62.0} and melody_events
        sing(keeper, lambda i, target: None if target is None else target + 2)
        assert controller.live_score() == 100

        player.finish()
        wait_for(
            lambda: (
                controller.current.song.title == "Song 2"
                and controller.status == PlayStatus.PLAYING
            )
        )
        assert scores == [
            {
                "points": 100,
                "accuracy": 1.0,
                "participation": 1.0,
                "grade": "Superstar!",
                "title": "Song 1",
                "singer": "Ann",
                "rank": 1,
                "board": [{"rank": 1, "points": 100, "title": "Song 1", "singer": "Ann"}],
                "voices": [],
            }
        ]
        assert controller.state()["last_score"]["points"] == 100
        assert controller.state()["scoreboard"] == scores[0]["board"]
        assert controller.melody() is None  # nothing is being scored any more
        assert not controller.state()["scoring_active"]  # song 2 has no melody: not scored

        player.finish()
        wait_for(lambda: controller.status == PlayStatus.IDLE)
        assert len(scores) == 1  # no score card for a song that was not scored
    finally:
        controller.close()


def test_turning_scoring_off_and_on(tmp_path):
    stems = FakeStems(tmp_path)
    controller, _, _ = make_controller(tmp_path, stems=stems)
    controller.settings.wait_for_instrumental = False
    try:
        song = make_song(1)
        stems.ready.add(song.video_id)
        melody_file(stems, song.video_id)
        controller.enqueue(song)
        wait_for(lambda: controller._scoring_target() is not None)

        controller.set_scoring(False)
        assert controller._scoring_target() is None and stems.want_pitch is False
        assert controller.settings.scoring is False

        stems.requested.clear()
        controller.set_scoring(True)
        assert stems.want_pitch is True and stems.requested == [song.video_id]
        assert controller._scoring_target() is not None  # picks the current song back up

        controller.set_pause(True)
        assert controller._scoring_target() is None  # nothing is judged while paused
    finally:
        controller.close()


def test_worker_writes_the_melody_of_separated_vocals(tmp_path):
    soundfile = pytest.importorskip("soundfile")
    from ytktv.separation import sep_worker

    vocals = np.concatenate([voice(60, 1.0), np.zeros(SR // 2, dtype=np.float32), voice(67, 1.0)])
    path = tmp_path / "song_(Vocals)_model.flac"
    soundfile.write(str(path), np.stack([vocals, vocals], axis=1), SR)
    sep_worker.write_pitch(path, tmp_path / "melody.json")
    melody = Melody.load(tmp_path / "melody.json")
    assert melody.hop == 0.05 and len(melody.notes) == 50
    assert melody.notes[10] == pytest.approx(60, abs=0.2) and melody.notes[40] == pytest.approx(
        67, abs=0.2
    )
    assert melody.notes[25] is None
    assert math.isclose(len(melody.notes) * melody.hop, 2.5)


def test_scoreboard_ranks_the_evening_best_first():
    from ytktv.core.scoring import Scoreboard

    board = Scoreboard()
    assert board.top() == []
    assert board.add(70, "Song A", "Ann") == 1
    assert board.add(90, "Song B", "Bo") == 1
    assert board.add(80, "Song C", "") == 2
    assert board.add(90, "Song D", "Di") == 2  # a tie does not push the earlier score down
    assert [(e["rank"], e["points"], e["title"]) for e in board.top(3)] == [
        (1, 90, "Song B"),
        (2, 90, "Song D"),
        (3, 80, "Song C"),
    ]
    assert len(board.top()) == 4
    board.clear()
    assert board.top() == []


def test_scoring_loop_reports_what_was_sung():
    from ytktv.core.scoring import ScoringLoop

    keeper = ScoreKeeper(Melody(0.05, (60.0,) * 400))
    heard = []
    notes = iter([60.0, None, 61.5])
    loop = ScoringLoop(
        lambda: next(notes, None), lambda: (keeper, 1.0), lambda p, n: heard.append((p, n))
    )
    loop.INTERVAL = 0.001
    loop.start()
    try:
        wait_for(lambda: len(heard) >= 3)
    finally:
        loop.stop()
    assert heard[:3] == [(1.0, 60.0), (1.0, None), (1.0, 61.5)]


def test_a_duet_gets_a_score_for_each_microphone(tmp_path):
    stems = FakeStems(tmp_path)
    controller, player, _ = make_controller(tmp_path, stems=stems)
    controller.settings.wait_for_instrumental = False
    scores = []
    controller.bus.subscribe(lambda topic, data: scores.append(data) if topic == "score" else None)
    try:
        song = make_song(1)
        stems.ready.add(song.video_id)
        melody_file(stems, song.video_id)
        controller.enqueue(song, singer="Ann")
        wait_for(lambda: controller.state()["scoring_active"])
        keeper, _position = controller._scoring_target()
        hop = keeper.melody.hop
        for i, target in enumerate(keeper.melody.notes):
            position = i * hop + 0.09
            keeper.feed(position, target)
            keeper.feed_voice(0, position, target)  # microphone 1 is on every note
            keeper.feed_voice(1, position, None if target is None else target + 4)  # 2 is off
            keeper.feed_voice(2, position, None)  # microphone 3 is on but nobody sings into it
        voices = keeper.voice_results()
        assert sorted(voices) == [0, 1] and voices[0].points == 100 and voices[1].points < 60

        player.finish()
        wait_for(lambda: controller.status == PlayStatus.IDLE)
        (score,) = scores
        assert score["points"] == 100 and score["rank"] == 1  # the better voice is the headline
        assert [(v["mic"], v["points"] == 100) for v in score["voices"]] == [(1, True), (2, False)]
        board = controller.state()["scoreboard"]
        assert [entry["singer"] for entry in board] == ["Ann (Mic 1)", "Ann (Mic 2)"]
    finally:
        controller.close()


def test_one_singer_with_two_microphones_switched_on_is_scored_as_before(tmp_path):
    stems = FakeStems(tmp_path)
    controller, player, _ = make_controller(tmp_path, stems=stems)
    controller.settings.wait_for_instrumental = False
    scores = []
    controller.bus.subscribe(lambda topic, data: scores.append(data) if topic == "score" else None)
    try:
        song = make_song(1)
        stems.ready.add(song.video_id)
        melody_file(stems, song.video_id)
        controller.enqueue(song)
        wait_for(lambda: controller.state()["scoring_active"])
        keeper, _position = controller._scoring_target()
        for i, target in enumerate(keeper.melody.notes):
            position = i * keeper.melody.hop + 0.09
            keeper.feed(position, target)
            keeper.feed_voice(0, position, target)
            keeper.feed_voice(1, position, None)
        player.finish()
        wait_for(lambda: controller.status == PlayStatus.IDLE)
        (score,) = scores
        assert score["voices"] == [] and score["singer"] == ""
        assert [entry["singer"] for entry in controller.state()["scoreboard"]] == [""]
    finally:
        controller.close()


def test_engine_reports_the_pitch_of_each_live_microphone():
    from ytktv.audio.engine import AudioEngine

    settings = Settings()
    engine = AudioEngine(settings)
    mixer = Mixer(settings, 48000)
    engine.mixer, engine.sample_rate = mixer, 48000
    assert engine.mic_pitches() == {}  # not running
    engine._output = object()  # looks running
    if not engine.running:
        pytest.skip("cannot fake a running engine on this build")
    t = np.arange(512) / 48000
    for block in range(20):
        phase = 2 * np.pi * (block * 512 / 48000 + t)
        tone = (0.3 * np.sin(440.0 * phase)).astype(np.float32)
        mixer.mix([tone, None, np.zeros(512, dtype=np.float32), None], 512)
    notes = engine.mic_pitches()
    assert sorted(notes) == [0, 2]  # the channels that are switched on
    assert abs(notes[0] - 69.0) < 0.5 and notes[2] is None  # A4 on one, silence on the other
