"""libmpv-backed player.

Video is rendered through mpv's render API into a Qt OpenGL widget (see
``ytktv.ui.mv_window``); this class owns the mpv handle and everything that
is not drawing: loading, audio filters, track switching and events.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from ytktv.bootstrap import import_mpv
from ytktv.core.models import VocalMode
from ytktv.player.base import EndCallback, PositionCallback
from ytktv.youtube.parse import MediaSource

log = logging.getLogger(__name__)

_INSTRUMENTAL_TITLE = "YTKTV instrumental"

# Seamless Original / Instrumental switching: both tracks are decoded together and
# merged into one 4-channel stream (original L R, instrumental L R)...
_DUAL_GRAPH = (
    "[aid{original}]aresample=48000,aformat=channel_layouts=stereo[ytktv_a];"
    "[aid{instrumental}]aresample=48000,aformat=channel_layouts=stereo[ytktv_b];"
    "[ytktv_a][ytktv_b]amerge=inputs=2[ao]"
)
# ...then mixed back to stereo by two gain stages that accept live commands, so a
# switch is a crossfade with no gap and no decoder restart.
_MIX_LABEL = "ytktvmix"
_MIX_FILTER = (
    "@" + _MIX_LABEL + ":lavfi=[asplit[x][y];"
    "[x]pan=stereo|c0=c0|c1=c1,volume@orig={original:.4f}[o];"
    "[y]pan=stereo|c0=c2|c1=c3,volume@inst={instrumental:.4f}[i];"
    "[o][i]amix=inputs=2:normalize=0]"
)
_CROSSFADE_STEPS = 10
_CROSSFADE_SECONDS = 0.18
# Peak meter tap for the mixer's output meter.
_LEVEL_LABEL = "ytktvlevel"
_LEVEL_FILTER = "@" + _LEVEL_LABEL + ":lavfi=[astats=metadata=1:reset=1:length=0.05]"

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
        self._dual = False  # both tracks are in the graph and can be crossfaded
        self._mix = 0.0  # 0 = original, 1 = instrumental
        self._guide = 0.0  # share of the original vocals kept in instrumental mode
        self._fade_generation = 0
        self._rubberband_ok = True
        self._duration = 0.0
        self._volume = 100.0

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
            # Read well ahead so a slow network moment does not become an audible hitch.
            demuxer_readahead_secs=30,
            cache_pause_wait=2,
            volume_max=100,
            log_handler=self._log,
            loglevel="warn",
        )
        self.mpv.event_callback("end-file")(self._on_end_file)
        self.mpv.event_callback("file-loaded")(self._on_file_loaded)
        self.mpv.observe_property("time-pos", self._on_time_pos)
        self.mpv.observe_property("duration", self._on_duration)
        self._apply_filters()

    @staticmethod
    def _log(level: str, component: str, message: str) -> None:
        if "channel layouts overlap" in message:
            return  # expected: the two stereo tracks are merged on purpose
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

    def _on_duration(self, _name: str, value: float | None) -> None:
        self._duration = float(value or 0.0)

    def _on_time_pos(self, _name: str, value: float | None) -> None:
        # Runs for every video frame: keep it to a callback, no calls back into mpv.
        if value is not None and self.on_position is not None:
            self.on_position(float(value), self._duration)

    # -- PlayerBackend ----------------------------------------------------

    def play(
        self,
        source: MediaSource,
        instrumental: Path | None = None,
        use_instrumental: bool = False,
    ) -> None:
        with self._lock:
            self._loaded = False
            self._pending_instrumental = None
            self._want_instrumental = use_instrumental
            self._fade_generation += 1
            # With the instrumental known up front, both tracks load together and the
            # song starts already in the right mode.
            self._dual = instrumental is not None
            self._mix = self._instrumental_mix() if (self._dual and use_instrumental) else 0.0
        agent = source.headers.get("User-Agent")
        if agent:
            self.mpv["user-agent"] = agent
        self.mpv["audio-files"] = [str(instrumental)] if instrumental is not None else []
        self.mpv["lavfi-complex"] = (
            _DUAL_GRAPH.format(original=1, instrumental=2) if instrumental is not None else ""
        )
        self._apply_filters()
        self.mpv["aid"] = "auto"
        self.mpv.pause = False
        url = edl_url(source.video_url, source.audio_url) if source.audio_url else source.video_url
        self.mpv.loadfile(url)

    def stop(self) -> None:
        with self._lock:
            self._loaded = False
            self._pending_instrumental = None
            self._dual = False
            self._mix = 0.0
            self._fade_generation += 1
        self.mpv.command("stop")
        self.mpv["lavfi-complex"] = ""
        self.mpv["audio-files"] = []

    def set_pause(self, paused: bool) -> None:
        self.mpv.pause = paused

    def seek(self, seconds: float) -> None:
        try:
            self.mpv.seek(max(0.0, seconds), reference="absolute")
        except Exception:
            log.debug("seek failed", exc_info=True)

    def set_volume(self, volume: float) -> None:
        self._volume = max(0.0, min(100.0, volume))
        self.mpv.volume = self._volume

    def set_pitch(self, semitones: int) -> None:
        if semitones != self._pitch:
            self._pitch = semitones
            self._apply_filters()

    def set_speed(self, speed: float) -> None:
        self.mpv.speed = max(0.5, min(1.5, speed))

    def set_channel_mode(self, mode: VocalMode) -> None:
        if mode != self._channel_mode:
            self._channel_mode = mode
            self._apply_filters()

    def _filter_chain(self) -> str:
        filters: list[str] = []
        with self._lock:
            if self._dual:
                filters.append(_MIX_FILTER.format(original=1.0 - self._mix, instrumental=self._mix))
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
        filters.append(_LEVEL_FILTER)
        return ",".join(filters)

    def _apply_filters(self) -> None:
        try:
            self.mpv.af = self._filter_chain()
        except Exception:
            if self._pitch and self._rubberband_ok:
                # This libmpv build has no rubberband; fall back to ffmpeg filters.
                self._rubberband_ok = False
                self._apply_filters()
            else:
                log.exception("could not apply audio filters")

    def attach_instrumental(self, path: Path) -> None:
        """Add the instrumental to a song that is already playing."""
        with self._lock:
            if not self._loaded:
                self._pending_instrumental = path
                return
            if self._dual:
                return
        try:
            self.mpv.command("audio-add", str(path), "auto", _INSTRUMENTAL_TITLE)
            tracks = [t for t in self.mpv.track_list if t.get("type") == "audio"]
            added = next(int(t["id"]) for t in tracks if t.get("title") == _INSTRUMENTAL_TITLE)
            original = next(int(t["id"]) for t in tracks if t.get("title") != _INSTRUMENTAL_TITLE)
            with self._lock:
                self._dual = True
                self._mix = 0.0  # keep sounding exactly as before, then crossfade
            self._apply_filters()
            self.mpv["lavfi-complex"] = _DUAL_GRAPH.format(original=original, instrumental=added)
        except Exception:
            log.exception("could not attach instrumental track")
            with self._lock:
                self._dual = False
            self._apply_filters()
            return
        self.use_instrumental(self._want_instrumental)

    def use_instrumental(self, enabled: bool) -> None:
        """Crossfade to the instrumental or back. A no-op until the track is attached."""
        with self._lock:
            self._want_instrumental = enabled
            if not (self._dual and self._loaded):
                return
            target = self._instrumental_mix() if enabled else 0.0
            if self._mix == target:
                return
            self._fade_generation += 1
            generation = self._fade_generation
            start = self._mix
        threading.Thread(
            target=self._crossfade,
            args=(start, target, generation),
            name="ytktv-xfade",
            daemon=True,
        ).start()

    def _instrumental_mix(self) -> float:
        # The original is instrumental + vocals, so blending a little of it back in
        # brings the singer back at that level without changing the backing track.
        return 1.0 - self._guide

    def set_guide(self, level: float) -> None:
        """Keep this share (0..1) of the original vocals audible in instrumental mode."""
        with self._lock:
            self._guide = max(0.0, min(1.0, level))
            enabled = self._want_instrumental
        if enabled:
            self.use_instrumental(True)

    def _set_mix(self, mix: float) -> None:
        self.mpv.command("af-command", _MIX_LABEL, "volume", f"{1.0 - mix:.4f}", "volume@orig")
        self.mpv.command("af-command", _MIX_LABEL, "volume", f"{mix:.4f}", "volume@inst")

    def _crossfade(self, start: float, target: float, generation: int) -> None:
        failures = 0
        step = 1
        while step <= _CROSSFADE_STEPS:
            with self._lock:
                if generation != self._fade_generation:
                    return  # a newer switch (or a new song) took over
                mix = start + (target - start) * step / _CROSSFADE_STEPS
            try:
                self._set_mix(mix)
            except Exception:
                # The filter graph is briefly unavailable while mpv rebuilds it (right after
                # a track is attached). Wait and retry the same step.
                failures += 1
                if failures > 40:
                    log.warning("crossfade gave up: the audio filter is not accepting commands")
                    return
                time.sleep(0.05)
                continue
            with self._lock:
                if generation == self._fade_generation:
                    self._mix = mix
            step += 1
            time.sleep(_CROSSFADE_SECONDS / _CROSSFADE_STEPS)

    def levels(self) -> tuple[float, float]:
        """Peak level (0..1, left and right) of the music as it leaves the player."""
        try:
            stats = self.mpv._get_property(f"af-metadata/{_LEVEL_LABEL}")
        except Exception:
            return (0.0, 0.0)
        if not stats or self.mpv.pause:
            return (0.0, 0.0)
        gain = (self._volume / 100.0) ** 3  # mpv's volume control is cubic
        peaks = []
        for channel in ("1", "2"):
            try:
                high = abs(float(stats.get(f"lavfi.astats.{channel}.Max_level", 0.0)))
                low = abs(float(stats.get(f"lavfi.astats.{channel}.Min_level", 0.0)))
            except (TypeError, ValueError):
                high = low = 0.0
            peaks.append(max(high, low) * gain)
        return (peaks[0], peaks[1])

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
