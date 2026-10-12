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
        self.want_pitch = False

    def request(self, video_id):
        self.requested.append(video_id)
        return StemStatus.QUEUED

    def status(self, video_id):
        return StemStatus.READY if video_id in self.ready else StemStatus.QUEUED

    def path(self, video_id):
        return self.tmp / f"{video_id}.flac" if video_id in self.ready else None

    def retain(self, wanted):
        self.retained = set(wanted)

    def pitch(self, video_id):
        path = self.tmp / f"{video_id}.melody.json"
        return path if path.exists() else None

    def stop(self):
        pass


def test_instrumental_attaches_mid_song_when_not_waiting(tmp_path):
    stems = FakeStems(tmp_path)
    controller, player, _ = make_controller(tmp_path, stems=stems)
    controller.settings.wait_for_instrumental = False
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


def test_removed_songs_are_dropped_from_separation(tmp_path):
    stems = FakeStems(tmp_path)
    controller, _, _ = make_controller(tmp_path, stems=stems)
    controller.settings.wait_for_instrumental = False
    try:
        songs = [make_song(i) for i in range(1, 4)]
        items = [controller.enqueue(song) for song in songs]
        wait_for(lambda: controller.status == PlayStatus.PLAYING)
        controller.remove(items[1].id)
        assert stems.retained == {songs[0].video_id, songs[2].video_id}
        controller.skip()
        wait_for(lambda: controller.current is not None and controller.current.id == items[2].id)
        assert stems.retained == {songs[2].video_id}
        controller.clear_queue()
        assert stems.retained == {songs[2].video_id}
    finally:
        controller.close()


def test_song_waits_for_its_instrumental_then_starts_with_it(tmp_path):
    stems = FakeStems(tmp_path)
    controller, player, _ = make_controller(tmp_path, stems=stems)
    try:
        controller.set_vocal_mode(VocalMode.INSTRUMENTAL)
        song = make_song(1)
        controller.enqueue(song)
        wait_for(lambda: controller.state()["loading"] == "Preparing instrumental")
        assert controller.status == PlayStatus.LOADING and player.play_count == 0

        stems.ready.add(song.video_id)
        stems.on_change(song.video_id, StemStatus.READY)
        wait_for(lambda: controller.status == PlayStatus.PLAYING)
        assert player.instrumental_active  # from the first note, no switch mid-song
        assert controller.state()["loading"] == ""
    finally:
        controller.close()


def test_choosing_original_or_skipping_ends_the_wait(tmp_path):
    stems = FakeStems(tmp_path)
    controller, player, _ = make_controller(tmp_path, stems=stems)
    try:
        controller.set_vocal_mode(VocalMode.INSTRUMENTAL)
        controller.enqueue(make_song(1))
        controller.enqueue(make_song(2))
        wait_for(lambda: controller.state()["loading"] == "Preparing instrumental")
        controller.skip()  # give up on song 1 while it is still waiting
        wait_for(
            lambda: controller.current is not None and controller.current.song.title == "Song 2"
        )
        wait_for(lambda: controller.state()["loading"] == "Preparing instrumental")
        assert player.play_count == 0 and controller.state()["history"] == []

        controller.set_vocal_mode(VocalMode.ORIGINAL)  # no need to wait any more
        wait_for(lambda: controller.status == PlayStatus.PLAYING)
        assert controller.current.song.title == "Song 2" and not player.instrumental_active
    finally:
        controller.close()


class FakePreloader:
    def __init__(self, tmp_path):
        self.tmp = tmp_path
        self.synced = []
        self.ready = set()
        self.on_change = None
        self.stopped = False

    def sync(self, upcoming, keep=None):
        self.synced.append((list(upcoming), set(keep or ())))

    def path(self, video_id):
        return self.tmp / f"{video_id}.mkv" if video_id in self.ready else None

    def status(self, video_id):
        return "ready" if video_id in self.ready else "loading"

    def stop(self):
        self.stopped = True


def test_upcoming_songs_are_preloaded_and_played_from_disk(tmp_path):
    preloader = FakePreloader(tmp_path)
    controller, player, resolver = make_controller(tmp_path, preloader=preloader)
    try:
        songs = [make_song(i) for i in range(1, 5)]
        for song in songs:
            controller.enqueue(song)
        wait_for(lambda: controller.status == PlayStatus.PLAYING)
        # The first song had no time to preload: it is streamed.
        assert player.source.video_url.startswith("https://")
        upcoming, keep = preloader.synced[-1]
        assert upcoming == [songs[1].video_id, songs[2].video_id]  # two ahead, not the whole queue
        assert keep == {songs[0].video_id}
        assert controller.state()["queue"][0]["preload"] == "loading"

        preloader.ready.add(songs[1].video_id)
        player.finish()
        wait_for(
            lambda: (
                controller.current.song.title == "Song 2"
                and controller.status == PlayStatus.PLAYING
            )
        )
        assert player.source.video_url == str(tmp_path / f"{songs[1].video_id}.mkv")
        assert preloader.synced[-1] == ([songs[2].video_id, songs[3].video_id], {songs[1].video_id})

        controller.settings.preload_queue = False
        controller.clear_queue()
        assert preloader.synced[-1] == ([], {songs[1].video_id})
    finally:
        controller.close()
    assert preloader.stopped


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


def test_guide_vocal_is_clamped_saved_and_sent_to_the_player(ktv):
    controller, player, _ = ktv
    controller.set_guide_vocal(30)
    assert player.guide == 0.3 and controller.state()["guide_vocal"] == 30
    controller.set_guide_vocal(250)
    assert controller.settings.guide_vocal == 100 and player.guide == 1.0


def test_danmaku_is_cleaned_and_rate_limited(ktv):
    controller, _, _ = ktv
    seen = []
    controller.bus.subscribe(
        lambda topic, data: seen.append(data["text"]) if topic == "danmaku" else None
    )
    assert controller.send_danmaku("  hello \n  room  ")
    assert not controller.send_danmaku("   ")
    assert controller.send_danmaku("x" * 500)
    assert seen == ["hello room", "x" * 60]
    results = [controller.send_danmaku(f"spam {i}") for i in range(20)]
    assert results.count(True) == 6 and not results[-1]  # 8 per window, 2 already used


def test_lyrics_load_for_the_current_song_and_clear_on_the_next(tmp_path):
    from ytktv.youtube.lyrics import LyricLine

    controller, player, resolver = make_controller(tmp_path)
    calls = []

    def lyrics(video_id, max_height, allow_auto):
        calls.append((video_id, allow_auto))
        if video_id == make_song(2).video_id:
            return []
        return [LyricLine(1.0, 2.0, "la"), LyricLine(2.0, 3.0, "di")]

    resolver.lyrics = lyrics
    events = []
    controller.bus.subscribe(lambda topic, data: events.append(data) if topic == "lyrics" else None)
    try:
        controller.enqueue(make_song(1))
        controller.enqueue(make_song(2))
        wait_for(lambda: controller.state()["lyrics"])
        assert events[-1]["lines"] == [
            {"start": 1.0, "end": 2.0, "text": "la"},
            {"start": 2.0, "end": 3.0, "text": "di"},
        ]
        assert events[-1]["id"] == controller.current.id

        player.finish()
        wait_for(
            lambda: (
                controller.current.song.title == "Song 2"
                and controller.status == PlayStatus.PLAYING
            )
        )
        wait_for(lambda: len(calls) == 2)
        assert not controller.state()["lyrics"]  # nothing to show for this video
        assert calls == [(make_song(1).video_id, True), (make_song(2).video_id, True)]
        assert any(e["lines"] == [] for e in events)

        controller.set_show_lyrics(False)
        assert controller.state()["show_lyrics"] is False
        controller.enqueue(make_song(3))
        player.finish()
        wait_for(
            lambda: (
                controller.current.song.title == "Song 3"
                and controller.status == PlayStatus.PLAYING
            )
        )
        assert len(calls) == 2  # turned off: not even fetched

        controller.set_show_lyrics(True)  # switched on in the middle of a song
        wait_for(lambda: controller.state()["lyrics"])
        assert calls[-1] == (make_song(3).video_id, True)
        assert events[-1]["lines"] and events[-1]["id"] == controller.current.id
        controller.set_show_lyrics(False)
        assert not controller.state()["lyrics"] and events[-1]["lines"] == []
    finally:
        controller.close()


def test_low_quality_restricted_video_tells_the_room_why(ktv):
    controller, _, resolver = ktv
    resolver.is_limited = lambda video_id: video_id == make_song(1).video_id
    toasts = []
    controller.bus.subscribe(
        lambda topic, data: toasts.append(data["message"]) if topic == "toast" else None
    )
    controller.enqueue(make_song(1))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    assert any("360p" in message for message in toasts)
    controller.enqueue(make_song(2))
    controller.skip()
    wait_for(
        lambda: (
            controller.current.song.title == "Song 2" and controller.status == PlayStatus.PLAYING
        )
    )
    assert sum("360p" in message for message in toasts) == 1


def test_queue_reports_how_long_until_each_song(ktv):
    controller, player, _ = ktv
    songs = [make_song(i) for i in range(1, 5)]
    for song in songs:
        controller.enqueue(song)
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    controller.duration, controller.position = 200.0, 50.0
    waits = [item["wait"] for item in controller.state()["queue"]]
    first, second = songs[1].duration or 240, songs[2].duration or 240
    assert waits == [150, 150 + first, 150 + first + second]

    controller.speed = 1.2  # faster playback, shorter waits
    assert controller.state()["queue"][0]["wait"] == 125


def test_lyrics_timing_is_nudged_per_song_and_remembered(ktv):
    controller, player, _ = ktv
    assert controller.nudge_lyrics(1) == 0.0  # nothing is playing: nothing to move
    controller.enqueue(make_song(1))
    controller.enqueue(make_song(2))
    wait_for(lambda: controller.status == PlayStatus.PLAYING)
    toasts = []
    controller.bus.subscribe(
        lambda topic, data: toasts.append(data["message"]) if topic == "toast" else None
    )
    assert controller.state()["lyrics_offset"] == 0.0
    assert controller.nudge_lyrics(1) == 0.1
    assert controller.nudge_lyrics(1) == 0.2
    assert controller.nudge_lyrics(-5) == -0.3
    assert toasts[-1] == "Lyrics 0.3 s later"
    assert controller.state()["lyrics_offset"] == -0.3
    assert controller.set_lyrics_offset(99) == 10.0  # kept within reach
    controller.set_lyrics_offset(0.4)

    player.finish()
    wait_for(lambda: controller.current is not None and controller.current.song.title == "Song 2")
    assert controller.lyrics_offset == 0.0  # the next song starts in time
    assert controller.settings.lyrics_offsets == {make_song(1).video_id: 0.4}

    controller.enqueue(make_song(1))  # sung again later: its timing comes back
    player.finish()
    wait_for(lambda: controller.current is not None and controller.current.song.title == "Song 1")
    assert controller.lyrics_offset == 0.4
    controller.nudge_lyrics(-4)
    assert controller.settings.lyrics_offsets == {}  # back in time: nothing to remember
    assert toasts[-1] == "Lyrics back in time with the subtitles"
