from __future__ import annotations

from tests.helpers import make_controller, make_song, wait_for
from ytktv.core.models import PlayStatus, StemStatus, VocalMode


def test_first_song_starts_playing_and_rest_queue_up(ktv):
    controller, player, _ = ktv
    controller.enqueue(make_song(1), singer="Ann")
    controller.enqueue(make_song(2))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    state = controller.state()
    assert state["current"]["song"]["title"] == "Song 1"
    assert state["current"]["singer"] == "Ann"
    assert [i["song"]["title"] for i in state["queue"]] == ["Song 2"]
    assert player.play_count == 1


def test_song_end_advances_then_goes_idle_and_records_history(ktv):
    controller, player, _ = ktv
    controller.enqueue(make_song(1))
    controller.enqueue(make_song(2))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    player.finish()
    wait_for(lambda: controller.current is not None and controller.current.song.title == "Song 2")
    player.finish()
    wait_for(lambda: controller.status == PlayStatus.IDLE)
    assert [s["title"] for s in controller.state()["history"]] == ["Song 2", "Song 1"]
    assert player.source is None


def test_skip_is_idempotent_for_the_same_song(ktv):
    controller, player, _ = ktv
    for i in range(1, 4):
        controller.enqueue(make_song(i))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    # Skip pressed twice in a row, plus the song ending: only one advance.
    current_id = controller.current.id
    controller._executor.submit(controller._advance, current_id)
    controller._executor.submit(controller._advance, current_id)
    wait_for(
        lambda: (
            controller.current.song.title == "Song 2" and controller.status == PlayStatus.PLAYING
        )
    )
    controller._executor.submit(lambda: None).result()
    assert controller.current.song.title == "Song 2"
    assert len(controller.queue) == 1


def test_unplayable_song_is_skipped_with_a_toast(ktv):
    controller, _, resolver = ktv
    toasts = []
    controller.bus.subscribe(
        lambda topic, payload: toasts.append(payload) if topic == "toast" else None
    )
    resolver.fail.add(make_song(1).video_id)
    controller.enqueue(make_song(1))
    controller.enqueue(make_song(2))
    wait_for(lambda: controller.current is not None and controller.current.song.title == "Song 2")
    assert any(t["error"] for t in toasts)
    assert controller.state()["history"] == []  # a song that never played is not "sung"


def test_stream_error_retries_then_moves_on(ktv):
    controller, player, resolver = ktv
    controller.enqueue(make_song(1))
    controller.enqueue(make_song(2))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    player.finish("error")
    wait_for(lambda: player.play_count == 2)
    assert controller.current.song.title == "Song 1"
    assert resolver.forgotten == [make_song(1).video_id]
    player.finish("error")
    wait_for(lambda: player.play_count == 3)
    player.finish("error")  # out of retries
    wait_for(lambda: controller.current.song.title == "Song 2")


def test_pause_replay_pitch_speed_and_reset_on_next_song(ktv):
    controller, player, _ = ktv
    controller.toggle_pause()  # nothing playing: ignored
    assert controller.status == PlayStatus.IDLE
    controller.enqueue(make_song(1))
    controller.enqueue(make_song(2))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)

    controller.toggle_pause()
    assert controller.status == PlayStatus.PAUSED and player.paused
    controller.replay()
    assert controller.status == PlayStatus.PLAYING and player.position == 0.0

    controller.set_pitch(99)
    assert controller.pitch == 6 and player.pitch == 6
    controller.set_speed(1.13)
    assert controller.speed == 1.1 and player.speed == 1.1

    controller.skip()
    wait_for(
        lambda: (
            controller.current.song.title == "Song 2" and controller.status == PlayStatus.PLAYING
        )
    )
    assert controller.pitch == 0 and player.pitch == 0 and player.speed == 1.0


def test_volumes_are_independent_and_scale_the_player(ktv):
    controller, player, _ = ktv
    controller.set_volume("music", 50)
    controller.set_volume("master", 50)
    assert player.volume == 25.0
    assert controller.settings.mic_volume == 80  # untouched
    controller.set_volume("mic", 130)
    assert controller.settings.mic_volume == 100
    assert controller.settings.music_volume == 50


def test_vocal_modes_map_to_player(ktv):
    controller, player, _ = ktv
    controller.set_vocal_mode("center_cut")
    assert player.channel_mode == VocalMode.CENTER_CUT
    controller.set_vocal_mode(VocalMode.INSTRUMENTAL)
    assert player.channel_mode == VocalMode.ORIGINAL
    assert controller.settings.default_vocal_mode == "instrumental"


class FakeStems:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.requested = []
        self.ready = set()
        self.on_change = None
        self.order = None

    def request(self, video_id):
        self.requested.append(video_id)
        return StemStatus.QUEUED

    def status(self, video_id):
        return StemStatus.READY if video_id in self.ready else StemStatus.QUEUED

    def path(self, video_id):
        return self.tmp / f"{video_id}.flac" if video_id in self.ready else None

    def stop(self):
        pass


def test_instrumental_attaches_when_separation_finishes_mid_song(tmp_path):
    stems = FakeStems(tmp_path)
    controller, player, _ = make_controller(tmp_path, stems=stems)
    try:
        controller.set_vocal_mode(VocalMode.INSTRUMENTAL)
        song = make_song(1)
        controller.enqueue(song)
        controller.enqueue(make_song(2))
        wait_for(lambda: controller.status == PlayStatus.PLAYING)
        assert stems.requested[:2] == [song.video_id, make_song(2).video_id]
        assert not player.instrumental_active
        assert controller.state()["current"]["stem"] == "queued"
        assert stems.order() == [song.video_id, make_song(2).video_id]

        stems.ready.add(song.video_id)
        stems.on_change(song.video_id, StemStatus.READY)
        assert player.instrumental_active
        assert controller.state()["current"]["stem"] == "ready"

        controller.set_vocal_mode(VocalMode.ORIGINAL)
        assert not player.instrumental_active
    finally:
        controller.close()


def test_favorites_toggle_and_persist(tmp_path):
    from ytktv.core.library import Library

    path = tmp_path / "library.json"
    controller, _, _ = make_controller(tmp_path, library=Library(path))
    try:
        assert controller.toggle_favorite(make_song(1)) is True
        assert controller.toggle_favorite(make_song(2)) is True
        assert controller.toggle_favorite(make_song(1)) is False
    finally:
        controller.close()
    assert [s.title for s in Library(path).favorites()] == ["Song 2"]
