"""Plain data models shared by every layer of the app."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class VocalMode(StrEnum):
    """Which audio the room hears for the current song."""

    ORIGINAL = "original"
    INSTRUMENTAL = "instrumental"  # AI-separated backing track
    LEFT = "left"  # left channel only (classic split-track KTV videos)
    RIGHT = "right"
    CENTER_CUT = "center_cut"  # instant L-R vocal reduction


class StemStatus(StrEnum):
    NONE = "none"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    SEPARATING = "separating"
    READY = "ready"
    FAILED = "failed"


class PlayStatus(StrEnum):
    IDLE = "idle"
    LOADING = "loading"
    PLAYING = "playing"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class Song:
    video_id: str
    title: str
    channel: str = ""
    duration: int = 0  # seconds, 0 when unknown
    thumbnail: str = ""

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "duration": self.duration,
            "thumbnail": self.thumbnail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Song:
        return cls(
            video_id=str(data["video_id"]),
            title=str(data.get("title") or data["video_id"]),
            channel=str(data.get("channel") or ""),
            duration=int(data.get("duration") or 0),
            thumbnail=str(data.get("thumbnail") or ""),
        )


def _new_id() -> str:
    return uuid.uuid4().hex[:10]


@dataclass(slots=True)
class QueueItem:
    song: Song
    singer: str = ""
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "singer": self.singer, "song": self.song.to_dict()}


@dataclass
class MicParams:
    """One mixer channel strip's knobs, laid out like a hardware console."""

    gain: float = 1.0  # GAIN trim, linear 0..2
    high_db: float = 0.0  # EQ, -12..+12 dB
    mid_db: float = 0.0
    low_db: float = 0.0
    reverb: float = 0.25  # FX send, 0..1
    echo: float = 0.15  # ECHO send, 0..1
    pan: float = 0.0  # -1 left .. +1 right
    fader: float = 0.8  # channel fader 0..1 (0.8 = unity)
    mute: bool = False
