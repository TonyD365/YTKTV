"""User settings and on-disk locations."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import platformdirs

from ytktv import APP_NAME
from ytktv.core.models import MicParams

log = logging.getLogger(__name__)


def data_dir() -> Path:
    path = Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = Path(platformdirs.user_cache_dir(APP_NAME, appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


MIC_CHANNELS = 4


@dataclass
class MicSettings(MicParams):
    device: str | None = None  # input device name; None = system default
    enabled: bool = False


def _default_mics() -> list[MicSettings]:
    return [MicSettings(enabled=i == 0) for i in range(MIC_CHANNELS)]


@dataclass
class Settings:
    server_port: int = 8765
    mv_screen: int = -1  # -1 = automatically use the extended display
    mv_fullscreen: bool = True
    max_height: int = 1080

    output_device: str | None = None  # None = system default
    music_volume: int = 80  # 0..100
    mic_volume: int = 80
    master_volume: int = 100
    mics: list[MicSettings] = field(default_factory=_default_mics)
    mic_monitor: bool = True  # mix microphones into the output automatically
    feedback_guard: bool = True  # notch out microphone feedback when it starts to squeal
    feedback_sensitivity: str = "low"  # "low", "medium" or "high" (see FeedbackGuard)
    # Effect presets saved by the user: name -> the EQ / reverb / echo values.
    mic_presets: dict[str, dict[str, float]] = field(default_factory=dict)
    # Lyrics shown earlier (+) or later (-) than their subtitles say, in seconds, per video.
    lyrics_offsets: dict[str, float] = field(default_factory=dict)
    local_folders: list[str] = field(default_factory=list)  # folders of video files to sing
    mic_preset: str = ""  # the preset the channels currently match, if any

    default_vocal_mode: str = "instrumental"
    auto_separate: bool = True
    separation_model: str = "UVR-MDX-NET-Inst_HQ_3.onnx"
    stem_cache_gb: float = 5.0
    # Hold a song back until its instrumental is ready instead of switching mid-song.
    wait_for_instrumental: bool = True
    # Download the next songs in the queue ahead of time so they play without buffering.
    preload_queue: bool = True
    # How much of the original singer stays audible in Instrumental mode (0..100).
    guide_vocal: int = 0
    # Show the video's own subtitles as karaoke lyrics on the MV screen.
    show_lyrics: bool = True  # the Lyrics button in the control bar
    # Music-reactive glow around the MV screen.
    lights: bool = True
    # Score each song by comparing the microphones with the original singer's melody.
    scoring: bool = True
    # Runtime variant the user said no to downloading; do not ask about it again.
    separation_declined: str = ""

    auto_update: bool = True
    # The first-run setup has been finished or skipped.
    setup_done: bool = False
    # Binding to a YTKTV Desk (staff terminal). Empty desk_url = a stand-alone machine.
    desk_url: str = ""
    room_id: str = ""
    room_key: str = ""
    desk_id: str = ""  # stays the same when the desk's IP address changes
    desk_key: str = ""  # the desk's public key: rooms obey only what it signs
    room_name: str = ""
    desk_last_seen: float = 0.0  # time.time() of the last contact with the desk

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Settings:
        known = {f.name for f in fields(cls)}
        clean = {k: v for k, v in data.items() if k in known}
        mics = clean.pop("mics", None)
        settings = cls(**clean)
        if isinstance(mics, list) and mics:
            mic_fields = {f.name for f in fields(MicSettings)}
            settings.mics = [
                MicSettings(**{k: v for k, v in m.items() if k in mic_fields})
                for m in mics
                if isinstance(m, dict)
            ]
        while len(settings.mics) < MIC_CHANNELS:
            settings.mics.append(MicSettings(enabled=False))
        return settings

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SettingsStore:
    """Loads and saves :class:`Settings` as JSON."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or data_dir() / "settings.json"
        self._lock = threading.Lock()
        self.settings = self._load()

    def _load(self) -> Settings:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            # Settings from before the setup wizard existed belong to someone who has
            # already set everything up by hand.
            data.setdefault("setup_done", True)
            return Settings.from_dict(data)
        except FileNotFoundError:
            return Settings()
        except Exception:
            log.exception("could not read %s; using defaults", self.path)
            return Settings()

    def save(self) -> None:
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.path.with_suffix(".tmp")
                tmp.write_text(json.dumps(self.settings.to_dict(), indent=2), encoding="utf-8")
                tmp.replace(self.path)
            except OSError:
                log.exception("could not save settings")
