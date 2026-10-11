"""Parsing recorded yt-dlp output (offline; no request leaves the machine)."""

from __future__ import annotations

from tests.helpers import load_fixture
from ytktv.player.mpv_player import edl_url
from ytktv.youtube.parse import extract_video_id, parse_media_source, parse_search_results
from ytktv.youtube.search import _TTLCache


def test_parse_search_results(benchmark):
    info = load_fixture("search.json")
    songs = benchmark(parse_search_results, info)
    assert len(songs) >= 20


def test_parse_media_source(benchmark):
    info = load_fixture("media.json")
    source = benchmark(parse_media_source, info)
    assert source.audio_url


def test_extract_video_id(benchmark):
    urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL123&index=4",
        "https://youtu.be/dQw4w9WgXcQ?si=abcdef",
        "dQw4w9WgXcQ",
        "just a normal search query about a song",
    ]
    benchmark(lambda: [extract_video_id(u) for u in urls])


def test_edl_url(benchmark):
    source = parse_media_source(load_fixture("media.json"))
    benchmark(edl_url, source.video_url, source.audio_url)


def test_search_cache_hit(benchmark):
    cache = _TTLCache(600.0)
    for i in range(128):
        cache.put((f"query {i}", 24), [i])
    benchmark(cache.get, ("query 64", 24))
