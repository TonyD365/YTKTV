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

    def suggest(self, text: str, limit: int = 8) -> list[str]:
        return [f"{text} karaoke", f"{text} lyrics"]

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


def pair_room(store, name: str = "Kids"):
    """Pair a room with a lanpair identity of its own; returns (room, the room's seed)."""
    from ytktv.rooms import secure

    seed = secure.new_seed()
    room, _ = store.pair(store.new_code(), name, identity=secure.public_hex(secure.identity(seed)))
    return room, seed


def room_identity(seed: str) -> str:
    from ytktv.rooms import secure

    return secure.public_hex(secure.identity(seed))


def room_handshake(ws, session):
    """The room's side of the handshake over a TestClient socket; returns the first reply."""
    ws.send_text(session.hello())
    ws.send_text(session.auth())
    return session.open(ws.receive_bytes())


# A key for signing SHA256SUMS in tests (conftest makes it the only trusted update key).
def _test_update_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def update_public_key() -> str:
    import base64

    from cryptography.hazmat.primitives import serialization

    raw = (
        _test_update_key()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    return base64.b64encode(raw).decode()


def signed(sums, key=None):
    """A fetch for download_update: *sums* for SHA256SUMS, its signature for SHA256SUMS.sig."""
    import base64

    data = sums.encode() if isinstance(sums, str) else sums
    signature = base64.b64encode((key or _test_update_key()).sign(data))
    return lambda url: signature if url.endswith(".sig") else data
