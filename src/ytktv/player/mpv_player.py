"""libmpv-backed player.

Video is rendered through mpv's render API into a Qt OpenGL widget (see
``ytktv.ui.mv_window``); this class owns the mpv handle and everything that
is not drawing: loading, audio filters, track switching and events.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from ytktv.bootstrap import import_mpv
from ytktv.core.models import VocalMode
from ytktv.player.base import EndCallback, PositionCallback
from ytktv.youtube.parse import MediaSource

log = logging.getLogger(__name__)

_INSTRUMENTAL_TITLE = "YTKTV instrumental"

_PAN_FILTERS = {
    VocalMode.LEFT: "lavfi=[pan=stereo|c0=c0|c1=c0]",
    VocalMode.RIGHT: "lavfi=[pan=stereo|c0=c1|c1=c1]",
    VocalMode.CENTER_CUT: "lavfi=[pan=stereo|c0=c0-c1|c1=c1-c0]",
}


def edl_url(video_url: str, audio_url: str) -> str:
    """Join separate video and audio streams into one mpv EDL source.

    This is the same trick mpv's own ytdl hook uses; ``%len%`` quoting keeps
    URLs with ``;`` or ``,`` in them intact.
    """

    def part(url: str) -> str:
        return f"!new_stream;!no_clip;!no_chapters;%{len(url.encode())}%{url}"

    return "edl://" + part(video_url) + ";" + part(audio_url)


def pitch_scale(semitones: int) -> float:
    return float(2.0 ** (semitones / 12.0))


class MpvPlayer:
    def __init__(self) -> None:
        self._mpv_module = import_mpv()
        self.on_end: EndCallback | None = None
        self.on_position: PositionCallback | None = None
        self._lock = threading.RLock()
        self._pitch = 0
        self._channel_mode = VocalMode.ORIGINAL
        self._loaded = False
        self._pending_instrumental: Path | None = None
        self._want_instrumental = False
        self._instrumental_aid: int | None = None
        self._rubberband_ok = True

        self.mpv = self._mpv_module.MPV(
            vo="libmpv",
            ytdl=False,
            idle="yes",
            keep_open="no",
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            hwdec="auto-safe",
            audio_display="no",
            cache="yes",
            demuxer_max_bytes="200MiB",
            volume_max=100,
            log_handler=self._log,
            loglevel="warn",
        )
        self.mpv.event_callback("end-file")(self._on_end_file)
        self.mpv.event_callback("file-loaded")(self._on_file_loaded)
        self.mpv.observe_property("time-pos", self._on_time_pos)

    @staticmethod
    def _log(level: str, component: str, message: str) -> None:
        levels = {"fatal": logging.ERROR, "error": logging.ERROR, "warn": logging.WARNING}
        log.log(levels.get(level, logging.DEBUG), "mpv[%s] %s", component, message.strip()[:300])

    # -- events (called on python-mpv's event thread) ---------------------

    def _on_end_file(self, event: Any) -> None:
        try:
            reason = int(event.data.reason)
        except Exception:
            return
        end_file = self._mpv_module.MpvEventEndFile
        if reason == end_file.EOF:
            kind = "eof"
        elif reason == end_file.ERROR:
            kind = "error"
        else:
            return  # stopped or replaced by us
        with self._lock:
            self._loaded = False
        if self.on_end:
            self.on_end(kind)

    def _on_file_loaded(self, _event: Any) -> None:
        with self._lock:
            self._loaded = True
            pending = self._pending_instrumental
            self._pending_instrumental = None
        if pending is not None:
            self.attach_instrumental(pending)

    def _on_time_pos(self, _name: str, value: float | None) -> None:
        if value is None or self.on_position is None:
            return
        try:
            duration = float(self.mpv.duration or 0.0)
        except Exception:
            duration = 0.0
        self.on_position(float(value), duration)

    # -- PlayerBackend ----------------------------------------------------

    def play(
        self,
        source: MediaSource,
        instrumental: Path | None = None,
        use_instrumental: bool = False,
    ) -> None:
        with self._lock:
            self._loaded = False
            self._instrumental_aid = None
            self._pending_instrumental = instrumental
            self._want_instrumental = use_instrumental
        agent = source.headers.get("User-Agent")
        if agent:
            self.mpv["user-agent"] = agent
        self.mpv["aid"] = "auto"
        self.mpv.pause = False
        url = edl_url(source.video_url, source.audio_url) if source.audio_url else source.video_url
        self.mpv.loadfile(url)

    def stop(self) -> None:
        with self._lock:
            self._loaded = False
            self._pending_instrumental = None
            self._instrumental_aid = None
        self.mpv.command("stop")

    def set_pause(self, paused: bool) -> None:
        self.mpv.pause = paused

    def seek(self, seconds: float) -> None:
        try:
            self.mpv.seek(max(0.0, seconds), reference="absolute")
        except Exception:
            log.debug("seek failed", exc_info=True)

    def set_volume(self, volume: float) -> None:
        self.mpv.volume = max(0.0, min(100.0, volume))

    def set_pitch(self, semitones: int) -> None:
        self._pitch = semitones
        self._apply_filters()

    def set_speed(self, speed: float) -> None:
        self.mpv.speed = max(0.5, min(1.5, speed))

    def set_channel_mode(self, mode: VocalMode) -> None:
        self._channel_mode = mode
        self._apply_filters()

    def _apply_filters(self) -> None:
        filters: list[str] = []
        pan = _PAN_FILTERS.get(self._channel_mode)
        if pan:
            filters.append(pan)
        if self._pitch:
            scale = pitch_scale(self._pitch)
            if self._rubberband_ok:
                filters.append(f"rubberband=pitch-scale={scale:.6f}")
            else:
                filters.append(
                    f"lavfi=[asetrate=48000*{scale:.6f},aresample=48000,atempo={1 / scale:.6f}]"
                )
        try:
            self.mpv.af = ",".join(filters)
        except Exception:
            if self._pitch and self._rubberband_ok:
                # This libmpv build has no rubberband; fall back to ffmpeg filters.
                self._rubberband_ok = False
                self._apply_filters()
            else:
                log.exception("could not apply audio filters")

    def attach_instrumental(self, path: Path) -> None:
        with self._lock:
            if not self._loaded:
                self._pending_instrumental = path
                return
            if self._instrumental_aid is not None:
                return
        try:
            self.mpv.command("audio-add", str(path), "auto", _INSTRUMENTAL_TITLE)
            for track in self.mpv.track_list:
                if track.get("type") == "audio" and track.get("title") == _INSTRUMENTAL_TITLE:
                    with self._lock:
                        self._instrumental_aid = int(track["id"])
        except Exception:
            log.exception("could not attach instrumental track")
            return
        self.use_instrumental(self._want_instrumental)

    def use_instrumental(self, enabled: bool) -> None:
        with self._lock:
            self._want_instrumental = enabled
            aid = self._instrumental_aid
            loaded = self._loaded
        if not loaded:
            return
        try:
            if enabled and aid is not None:
                self.mpv["aid"] = aid
            else:
                original = next(
                    (
                        int(t["id"])
                        for t in self.mpv.track_list
                        if t.get("type") == "audio" and t.get("title") != _INSTRUMENTAL_TITLE
                    ),
                    None,
                )
                if original is not None:
                    self.mpv["aid"] = original
        except Exception:
            log.exception("could not switch audio track")

    def audio_devices(self) -> list[dict[str, str]]:
        try:
            return [dict(d) for d in self.mpv.audio_device_list]
        except Exception:
            return []

    def set_audio_device(self, description: str | None) -> None:
        name = "auto"
        if description:
            for device in self.audio_devices():
                if device.get("description") == description:
                    name = device.get("name", "auto")
                    break
        try:
            self.mpv["audio-device"] = name
        except Exception:
            log.exception("could not select audio device %r", name)

    def close(self) -> None:
        self.on_end = None
        self.on_position = None
        try:
            self.mpv.terminate()
        except Exception:
            log.debug("mpv terminate failed", exc_info=True)
