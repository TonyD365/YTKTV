from __future__ import annotations

import json
from pathlib import Path

from tests.helpers import make_controller, make_song, wait_for
from ytktv.core.offline import OfflineSongs


def fake_download(video_id: str, dest: Path) -> Path:
    if video_id.endswith("bad"):
        raise OSError("no internet")
    dest.mkdir(parents=True, exist_ok=True)
    media = dest / "media.mp4"
    media.write_bytes(b"video " + video_id.encode())
    return media


def test_songs_are_kept_with_lyrics_and_survive_a_restart(tmp_path):
    lyrics = [{"start": 1.0, "end": 2.0, "text": "la"}]
    offline = OfflineSongs(tmp_path / "offline", fake_download, lambda _id: lyrics)
    offline.start()
    song = make_song(1)
    try:
        assert offline.add(song) and not offline.add(song)
        wait_for(lambda: offline.status(song.video_id) == "ready")
        assert offline.path(song.video_id).read_bytes().startswith(b"video")
        assert offline.lyrics(song.video_id) == lyrics
        assert [s.video_id for s in offline.songs()] == [song.video_id]
    finally:
        offline.stop()

    # An unfinished download (no song file) is cleared at the next start.
    (tmp_path / "offline" / "half").mkdir()
    again = OfflineSongs(tmp_path / "offline", fake_download)
    assert again.ids() == {song.video_id} and not (tmp_path / "offline" / "half").exists()
    again.remove(song.video_id)
    assert again.songs() == [] and again.status(song.video_id) == "none"


def test_failed_download_is_reported_and_can_be_retried(tmp_path):
    offline = OfflineSongs(tmp_path, fake_download)
    offline.start()
    song = make_song(2)
    bad = type(song)(video_id="songbad", title="Bad")
    try:
        offline.add(bad)
        wait_for(lambda: offline.status("songbad") == "failed")
        assert not (tmp_path / "songbad").exists()
        assert offline.add(bad)  # tried again on request
    finally:
        offline.stop()


def test_kept_song_plays_from_disk_with_kept_lyrics(tmp_path):
    offline = OfflineSongs(tmp_path / "offline", fake_download)
    song = make_song(3)
    folder = tmp_path / "offline" / song.video_id
    folder.mkdir(parents=True)
    (folder / "media.webm").write_bytes(b"x")
    (folder / "lyrics.json").write_text(json.dumps([{"start": 0, "end": 1, "text": "kept"}]))
    (folder / "song.json").write_text(json.dumps(song.to_dict()))
    controller, player, resolver = make_controller(tmp_path, offline=offline)
    try:
        controller.enqueue(song)
        wait_for(lambda: player.source is not None)
        assert player.source.video_url == str(folder / "media.webm")
        wait_for(lambda: bool(controller.lyrics))
        assert controller.lyrics[0].text == "kept"
        assert controller.offline_status(song.video_id) == "ready"
    finally:
        controller.close()
