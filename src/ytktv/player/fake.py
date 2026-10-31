"""An in-memory player used by tests, benchmarks and ``--no-video`` runs."""

from __future__ import annotations

from pathlib import Path

from ytktv.core.models import VocalMode
from ytktv.player.base import EndCallback, PositionCallback
from ytktv.youtube.parse import MediaSource


class FakePlayer:
    def __init__(self) -> None:
        self.on_end: EndCallback | None = None
        self.on_position: PositionCallback | None = None
        self.source: MediaSource | None = None
        self.audio_delay = 0.0
        self.paused = False
        self.volume = 100.0
        self.pitch = 0
        self.speed = 1.0
        self.channel_mode = VocalMode.ORIGINAL
        self.instrumental: Path | None = None
        self.instrumental_active = False
        self.guide = 0.0
        self.audio_device: str | None = None
        self.position = 0.0
        self.play_count = 0
        self.closed = False

    def play(
        self,
        source: MediaSource,
        instrumental: Path | None = None,
        use_instrumental: bool = False,
    ) -> None:
        self.source = source
        self.paused = False
        self.position = 0.0
        self.instrumental = instrumental
        self.instrumental_active = bool(instrumental) and use_instrumental
        self.play_count += 1
        if self.on_position:  # a real player reports position 0 once playback begins
            self.on_position(0.0, source.duration)

    def stop(self) -> None:
        self.source = None
        self.instrumental = None
        self.instrumental_active = False

    def set_pause(self, paused: bool) -> None:
        self.paused = paused

    def seek(self, seconds: float) -> None:
        self.position = seconds

    def set_volume(self, volume: float) -> None:
        self.volume = volume

    def set_pitch(self, semitones: int) -> None:
        self.pitch = semitones

    def set_speed(self, speed: float) -> None:
        self.speed = speed

    def set_audio_delay(self, seconds: float) -> None:
        self.audio_delay = seconds

    def set_channel_mode(self, mode: VocalMode) -> None:
        self.channel_mode = mode

    def attach_instrumental(self, path: Path) -> None:
        self.instrumental = path

    def use_instrumental(self, enabled: bool) -> None:
        self.instrumental_active = enabled and self.instrumental is not None

    def set_guide(self, level: float) -> None:
        self.guide = level

    def set_audio_device(self, description: str | None) -> None:
        self.audio_device = description

    def levels(self) -> tuple[float, float]:
        return (0.0, 0.0)

    def close(self) -> None:
        self.closed = True

    # Test helper: simulate the current file finishing.
    def finish(self, reason: str = "eof") -> None:
        if reason == "eof" and self.on_position:
            self.on_position(10.0, 10.0)
        self.source = None
        if self.on_end:
            self.on_end(reason)
