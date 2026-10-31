import json

from tests.helpers import make_controller, make_song
from ytktv.youtube import music_import

SPOTIFY = (
    '<script id="__NEXT_DATA__" type="application/json">'
    + json.dumps(
        {
            "props": {
                "pageProps": {
                    "state": {
                        "data": {
                            "entity": {
                                "name": "Road Trip",
                                "trackList": [{"title": "Yesterday", "subtitle": "The Beatles"}],
                            }
                        }
                    }
                }
            }
        }
    )  # fmt: skip
    + "</script>"
)
APPLE = (
    '<script type="application/ld+json">{"@type": "MusicPlaylist", "name": "Hits"}</script>'
    '<script type="application/json" id="serialized-server-data">'
    + json.dumps([{"data": {"items": [{"title": "Housewife", "artistName": "Tate McRae"}]}}])
    + "</script>"
)


def test_reading_spotify_apple_and_plain_lists():
    assert music_import.is_music_link("https://open.spotify.com/playlist/37i9dQZEVX?si=1")
    assert music_import.is_music_link("https://music.apple.com/us/playlist/hits/pl.abc")
    assert not music_import.is_music_link("https://www.youtube.com/playlist?list=PL1")
    assert music_import.spotify_tracks(SPOTIFY) == ("Road Trip", [("Yesterday", "The Beatles")])
    assert music_import.apple_tracks(APPLE) == ("Hits", [("Housewife", "Tate McRae")])
    assert music_import.text_tracks("1. Yesterday - The Beatles\n\n晴天") == [
        ("Yesterday", "The Beatles"), ("晴天", ""),
    ]  # fmt: skip


def test_songs_are_found_on_youtube_and_saved(tmp_path, monkeypatch):
    searched = []

    def search(query, limit):
        searched.append(query)
        return [] if "Missing" in query else [make_song(len(searched))]

    found = music_import.find_on_youtube([("Yesterday", "The Beatles"), ("Missing", "")], search)
    assert len(found) == 1 and "Yesterday The Beatles karaoke" in searched

    controller, _, resolver = make_controller(tmp_path)
    try:
        resolver.search = search
        monkeypatch.setattr(music_import, "fetch_page", lambda url: SPOTIFY)
        name = controller.import_playlist("https://open.spotify.com/playlist/abc")
        assert name == "Road Trip" and len(controller.library.playlist(name)) == 1
        listed = controller.import_song_list("Yesterday - The Beatles\nLet It Be")
        assert len(controller.library.playlist(listed)) == 2
    finally:
        controller.close()
