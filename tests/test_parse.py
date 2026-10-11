from __future__ import annotations

import pytest

from tests.helpers import load_fixture
from ytktv.player.mpv_player import edl_url, pitch_scale
from ytktv.youtube.parse import (
    entry_to_song,
    extract_video_id,
    parse_media_source,
    parse_search_results,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10s", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?list=PL1&v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("hello world", None),
        ("https://example.com/watch?v=short", None),
    ],
)
def test_extract_video_id(text, expected):
    assert extract_video_id(text) == expected


def test_parse_recorded_search_results():
    songs = parse_search_results(load_fixture("search.json"))
    assert len(songs) >= 20
    assert len({s.video_id for s in songs}) == len(songs)
    for song in songs:
        assert len(song.video_id) == 11
        assert song.title
        assert song.thumbnail.startswith("https://")


def test_entry_to_song_rejects_non_videos_and_live_streams():
    assert entry_to_song(None) is None
    assert entry_to_song({"id": "UCwTRjvjVge51X-ILJ4i22ew", "title": "a channel"}) is None
    assert entry_to_song({"id": "dQw4w9WgXcQ", "live_status": "is_live"}) is None
    song = entry_to_song({"id": "dQw4w9WgXcQ", "uploader": "Rick"})
    assert song is not None
    assert song.title == "dQw4w9WgXcQ" and song.channel == "Rick"
    assert song.thumbnail.endswith("/dQw4w9WgXcQ/mqdefault.jpg")


def test_parse_media_source_split_and_muxed():
    source = parse_media_source(load_fixture("media.json"))
    assert "itag=137" in source.video_url
    assert source.audio_url is not None and "itag=140" in source.audio_url
    assert source.headers["User-Agent"] == "Mozilla/5.0 Test"
    assert source.duration == 468

    muxed = parse_media_source({"url": "https://x.invalid/v", "vcodec": "avc1", "acodec": "mp4a"})
    assert muxed.video_url == "https://x.invalid/v" and muxed.audio_url is None

    with pytest.raises(ValueError):
        parse_media_source({"requested_formats": [{"vcodec": "none", "acodec": "none"}]})


def test_edl_url_quotes_by_byte_length():
    video, audio = "https://v.invalid/a;b,c", "https://a.invalid/ü"
    url = edl_url(video, audio)
    assert url.startswith("edl://!new_stream;!no_clip;!no_chapters;")
    assert f"%{len(video)}%{video}" in url
    assert f"%{len(audio.encode())}%{audio}" in url


def test_pitch_scale():
    assert pitch_scale(0) == 1.0
    assert pitch_scale(12) == pytest.approx(2.0)
    assert pitch_scale(-12) == pytest.approx(0.5)
