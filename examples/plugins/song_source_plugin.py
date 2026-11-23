"""Adds a venue's own song list to search results. Copy it to build your own song source.

Put a ``songs.csv`` in this plugin's data folder, with one song on each line:

    video_id,title,channel
    dQw4w9WgXcQ,Example Song,Example Channel
"""

import csv
import re

from ytktv.core.models import Song

NAME = "CSV Song List"
VERSION = "1.0.0"
PERMISSIONS = ["songs"]
API_VERSION = 1

VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")


def read_songs(path):
    """The valid songs in a CSV file; a missing file is an empty list."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [
            Song(row["video_id"], row["title"].strip(), (row.get("channel") or "").strip())
            for row in csv.DictReader(file)
            if VIDEO_ID.fullmatch(row.get("video_id") or "") and (row.get("title") or "").strip()
        ]


def setup(api):
    path = api.data_dir / "songs.csv"

    def search(query):
        words = query.casefold().split()
        return [
            song
            for song in read_songs(path)
            if words and all(w in f"{song.title} {song.channel}".casefold() for w in words)
        ]

    api.add_song_source(search)
