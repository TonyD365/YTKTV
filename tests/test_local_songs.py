"""Songs from video files on this computer, and rooms that may sing only those."""

from __future__ import annotations

import subprocess

import pytest

from tests.helpers import make_controller, make_song, wait_for
from ytktv.core import local
from ytktv.core.local import AudioTrack, LocalSongs, StemRouter, instrumental_track
from ytktv.core.models import StemStatus

FFMPEG_SAYS = """Input #0, matroska,webm, from 'song.mkv':
  Stream #0:0: Video: h264, yuv420p, 1920x1080
  Stream #0:1(chi): Audio: aac, 48000 Hz, stereo
    Metadata:
      title           : 原唱
  Stream #0:2(chi): Audio: aac, 48000 Hz, stereo
    Metadata:
      title           : 伴奏
  Stream #0:3: Subtitle: ass
"""


def fake_ffmpeg(stderr: str):
    def run(command, **_kwargs):
        return subprocess.CompletedProcess(command, 1, stdout="", stderr=stderr)

    return run


def test_audio_tracks_and_which_is_the_instrumental(tmp_path):
    tracks = local.audio_tracks("ffmpeg", tmp_path / "song.mkv", run=fake_ffmpeg(FFMPEG_SAYS))
    assert [(t.index, t.label) for t in tracks] == [(0, "原唱 chi"), (1, "伴奏 chi")]
    assert instrumental_track(tracks) == 1
    assert instrumental_track(tracks, swapped=True) == 0
    karaoke_first = [AudioTrack(0, "Karaoke"), AudioTrack(1, "Vocal")]
    assert instrumental_track(karaoke_first) == 0
    assert instrumental_track([AudioTrack(0, "")]) is None
    unnamed = [AudioTrack(0, "eng"), AudioTrack(1, "eng")]
    assert instrumental_track(unnamed) == 1  # no names: the second track


def test_scan_finds_videos_and_their_lyrics(tmp_path):
    folder = tmp_path / "songs"
    (folder / "sub").mkdir(parents=True)
    (folder / "Teresa Teng - 月亮代表我的心.mkv").write_bytes(b"x")
    (folder / "sub" / "Yesterday.mp4").write_bytes(b"x")
    (folder / "notes.txt").write_text("not a song")
    (folder / "sub" / "Yesterday.lrc").write_text("[00:01.00]Yesterday\n", encoding="utf-8")
    changed: list[bool] = []
    songs = LocalSongs(lambda: [str(folder)], None, lambda: changed.append(True))
    assert songs.scan() == 2 and changed == [True]
    moon = songs.songs("月亮")[0]
    assert moon.channel == "Teresa Teng" and local.is_local(moon.video_id)
    assert songs.path(moon.video_id).name.endswith(".mkv")
    yesterday = songs.songs("yesterday")[0]
    assert [line.text for line in songs.lyrics(yesterday.video_id)] == ["Yesterday"]
    assert songs.lyrics(moon.video_id) == []


class FakeManager:
    def __init__(self) -> None:
        self.asked: list[str] = []
        self.stopped = False

    def request(self, video_id):
        self.asked.append(video_id)
        return StemStatus.QUEUED

    def status(self, video_id):
        return StemStatus.READY

    def path(self, video_id):
        return None

    def pitch(self, video_id):
        return None

    def retain(self, wanted):
        pass

    def start(self):
        pass

    def stop(self):
        self.stopped = True


def test_router_sends_two_track_files_to_the_track_copier(tmp_path, monkeypatch):
    library = LocalSongs(lambda: [], "ffmpeg")
    monkeypatch.setattr(library, "has_instrumental_track", lambda video_id: video_id == "local-a")
    tracks, ai = FakeManager(), FakeManager()
    router = StemRouter(library, tracks, ai)
    router.on_change = print
    router.request("local-a")
    router.request("local-b")  # one track: vocal separation
    router.request("dQw4w9WgXcQ")
    assert tracks.asked == ["local-a"] and ai.asked == ["local-b", "dQw4w9WgXcQ"]
    assert ai.on_change is print and router.separating

    alone = StemRouter(library, FakeManager(), None)  # no separation installed
    assert alone.request("dQw4w9WgXcQ") == StemStatus.NONE and not alone.separating
    newer = FakeManager()
    alone.on_change = print
    alone.attach_ai(newer)
    assert alone.ai is newer and newer.on_change is print


def test_local_song_plays_from_its_file_and_local_only_rooms(tmp_path):
    folder = tmp_path / "songs"
    folder.mkdir()
    (folder / "Song.mp4").write_bytes(b"x")
    library = LocalSongs(lambda: [str(folder)], None)
    library.scan()
    song = library.songs()[0]
    controller, player, _ = make_controller(tmp_path, local=library)
    try:
        controller.set_local_only(True)
        with pytest.raises(PermissionError, match="this computer only"):
            controller.enqueue(make_song(1))
        assert controller.enqueue_many([make_song(2), song]) == 1
        wait_for(lambda: player.source is not None)
        assert player.source.video_url == str(folder / "Song.mp4")
        assert controller.state()["local_only"] is True
        assert controller.local_matches("song") == [song]
    finally:
        controller.close()


def test_desk_marks_a_room_local_only():
    from ytktv.desk.store import DeskStore
    from ytktv.rooms.state import RoomState

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Kids")
    store.open_room(room.room_id, "Kim", 60)
    store.set_local_only(room.room_id, True)
    message = store.room(room.room_id).message()
    assert message["local_only"] is True
    state = RoomState()
    state.apply(message)
    assert state.local_only
    state.apply({"type": "close"})
    assert not state.local_only


def test_staff_terminal_sets_a_rooms_local_folders(tmp_path, qtbot):
    from ytktv.config import SettingsStore
    from ytktv.desk.server import folders_message
    from ytktv.desk.store import DeskStore
    from ytktv.rooms.client import RoomClient
    from ytktv.ui.local_songs_card import LocalSongsCard

    desk = DeskStore()
    room, _ = desk.pair(desk.new_code(), "Kids")
    desk.set_local_folders(room.room_id, ["/songs/a", " ", "D:\\Karaoke"])
    message = folders_message(desk.room(room.room_id))
    assert message == {"type": "local_folders", "folders": ["/songs/a", "D:\\Karaoke"]}

    store = SettingsStore(tmp_path / "settings.json")
    client = RoomClient.__new__(RoomClient)
    client.store, client.on_event = store, lambda *_: None
    from ytktv.rooms.state import RoomState

    client.state = RoomState()
    client._handle(message)
    assert store.settings.local_folders == ["/songs/a", "D:\\Karaoke"]

    store.settings.desk_url = "https://desk:8770"
    controller, _player, _ = make_controller(tmp_path)
    try:
        controller.settings.desk_url = "https://desk:8770"
        card = LocalSongsCard(controller)
        qtbot.addWidget(card)
        assert not card.add_button.isEnabled() and not card.remove_button.isEnabled()
    finally:
        controller.close()
