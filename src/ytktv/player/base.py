"""The interface the controller needs from a video player."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ytktv.core.models import VocalMode
from ytktv.youtube.parse import MediaSource

EndCallback = Callable[[str], None]  # "eof" or "error"
PositionCallback = Callable[[float, float], None]  # position, duration (seconds)


class PlayerBackend(Protocol):
    on_end: EndCallback | None
    on_position: PositionCallback | None

    def play(
        self,
        source: MediaSource,
        instrumental: Path | None = None,
        use_instrumental: bool = False,
    ) -> None: ...

    def stop(self) -> None: ...

    def set_pause(self, paused: bool) -> None: ...

    def seek(self, seconds: float) -> None: ...

    def set_volume(self, volume: float) -> None: ...

    def set_pitch(self, semitones: int) -> None: ...

    def set_speed(self, speed: float) -> None: ...

    def set_channel_mode(self, mode: VocalMode) -> None: ...

    def attach_instrumental(self, path: Path) -> None: ...

    def use_instrumental(self, enabled: bool) -> None: ...

    def set_audio_device(self, description: str | None) -> None: ...

    def levels(self) -> tuple[float, float]: ...

    def close(self) -> None: ...
