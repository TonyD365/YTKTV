"""Shared test doubles, also used by the benchmarks."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from ytktv.config import SettingsStore
from ytktv.core.controller import KTVController
from ytktv.core.models import Song
from ytktv.player.fake import FakePlayer
from ytktv.youtube.parse import MediaSource, parse_search_results

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_song(index: int = 0) -> Song:
    video_id = f"{index:011d}"
    return Song(video_id=video_id, title=f"Song {index}", channel="Channel", duration=200)


class FakeResolver:
    def __init__(self) -> None:
        self.fail: set[str] = set()
        self.forgotten: list[str] = []

    def resolve(self, video_id: str, max_height: int = 1080) -> MediaSource:
        if video_id in self.fail:
            raise RuntimeError("unavailable")
        return MediaSource(video_url=f"https://example.invalid/{video_id}")

    def forget_stream(self, video_id: str, max_height: int = 1080) -> None:
        self.forgotten.append(video_id)


class FakeSource:
    """Stands in for YouTube search in server tests."""

    def __init__(self) -> None:
        self.songs = parse_search_results(load_fixture("search.json"))

    def search(self, query: str, limit: int = 24) -> list[Song]:
        return self.songs[:limit]

    def hot(self, category: str) -> list[Song]:
        return self.songs[:5]

    def lookup(self, video_id: str) -> Song | None:
        return Song(video_id=video_id, title="Looked up")


def make_controller(tmp_path: Path, **kwargs) -> tuple[KTVController, FakePlayer, FakeResolver]:
    player = FakePlayer()
    resolver = FakeResolver()
    controller = KTVController(
        SettingsStore(tmp_path / "settings.json"), player, resolver, **kwargs
    )
    return controller, player, resolver


def wait_for(condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.005)
