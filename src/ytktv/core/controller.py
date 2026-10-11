"""KTVController: the single entry point for every command in the app.

The desktop UI, the phone web page and the player callbacks all go through
this class, so they can never disagree about what is playing.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Protocol

from ytktv import __version__
from ytktv.config import SettingsStore
from ytktv.core.events import EventBus
from ytktv.core.library import Library
from ytktv.core.models import PlayStatus, QueueItem, Song, StemStatus, VocalMode
from ytktv.core.queue import SongQueue
from ytktv.player.base import PlayerBackend
from ytktv.youtube.parse import MediaSource

if TYPE_CHECKING:
    from ytktv.audio.engine import AudioEngine
    from ytktv.separation.worker import StemManager

log = logging.getLogger(__name__)

PITCH_RANGE = 6  # semitones either way
SPEEDS = (0.8, 0.9, 1.0, 1.1, 1.2)
_POSITION_INTERVAL = 0.5
_OPEN_RETRIES = 2


class StreamResolver(Protocol):
    def resolve(self, video_id: str, max_height: int = 1080) -> MediaSource: ...

    def forget_stream(self, video_id: str, max_height: int = 1080) -> None: ...


class KTVController:
    def __init__(
        self,
        store: SettingsStore,
        player: PlayerBackend,
        resolver: StreamResolver,
        library: Library | None = None,
        bus: EventBus | None = None,
        stems: StemManager | None = None,
        audio: AudioEngine | None = None,
        accelerator: str = "",
    ) -> None:
        self.store = store
        self.settings = store.settings
        self.player = player
        self.resolver = resolver
        self.library = library or Library()
        self.bus = bus or EventBus()
        self.stems = stems
        self.audio = audio
        self.accelerator = accelerator

        self.queue = SongQueue()
        self.queue.load_history(self.library.history)
        self.current: QueueItem | None = None
        self.status = PlayStatus.IDLE
        self.position = 0.0
        self.duration = 0.0
        self.pitch = 0
        self.speed = 1.0
        try:
            self.vocal_mode = VocalMode(self.settings.default_vocal_mode)
        except ValueError:
            self.vocal_mode = VocalMode.ORIGINAL

        self._lock = threading.RLock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ytktv-play")
        self._prefetcher = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ytktv-prefetch")
        self._last_position_emit = 0.0
        self._started = False  # has the current song actually produced playback?
        self._retries: dict[str, int] = {}
        self._save_timer: threading.Timer | None = None
        self._closed = False

        player.on_end = self._on_player_end
        player.on_position = self._on_player_position
        if stems is not None:
            stems.on_change = self._on_stem_change
            stems.order = self._stem_order
        self._apply_volume()
        player.set_audio_device(self.settings.output_device)

    # -- queue ------------------------------------------------------------

    def enqueue(self, song: Song, singer: str = "", priority: bool = False) -> QueueItem:
        item = self.queue.add(song, singer=singer, priority=priority)
        if self.stems is not None and self.settings.auto_separate:
            self.stems.request(song.video_id)
        with self._lock:
            start = self.current is None and self.status == PlayStatus.IDLE
            if start:
                self.status = PlayStatus.LOADING
        if start:
            self._executor.submit(self._advance, None)
        else:
            self._prefetch_next()
        self.toast(f"Added: {song.title}")
        self._emit_state()
        return item

    def remove(self, item_id: str) -> bool:
        ok = self.queue.remove(item_id)
        if ok:
            self._emit_state()
        return ok

    def prioritize(self, item_id: str) -> bool:
        ok = self.queue.prioritize(item_id)
        if ok:
            self._prefetch_next()
            self._emit_state()
        return ok

    def move(self, item_id: str, index: int) -> bool:
        ok = self.queue.move(item_id, index)
        if ok:
            self._prefetch_next()
            self._emit_state()
        return ok

    def shuffle(self) -> None:
        self.queue.shuffle()
        self._prefetch_next()
        self._emit_state()

    def clear_queue(self) -> None:
        self.queue.clear()
        self._emit_state()

    # -- transport --------------------------------------------------------

    def skip(self) -> None:
        with self._lock:
            current_id = self.current.id if self.current else None
            if current_id is None and self.status != PlayStatus.IDLE:
                return  # already switching songs
        self._executor.submit(self._advance, current_id, True)

    def replay(self) -> None:
        if self.current is None:
            return
        self.player.seek(0.0)
        self.set_pause(False)

    def toggle_pause(self) -> None:
        self.set_pause(self.status != PlayStatus.PAUSED)

    def set_pause(self, paused: bool) -> None:
        with self._lock:
            if self.status not in (PlayStatus.PLAYING, PlayStatus.PAUSED):
                return
            self.status = PlayStatus.PAUSED if paused else PlayStatus.PLAYING
        self.player.set_pause(paused)
        self._emit_state()

    def seek(self, seconds: float) -> None:
        if self.current is not None:
            self.player.seek(seconds)

    def _fade_out(self) -> None:
        """Short volume ramp so skipping does not cut the music off abruptly."""
        settings = self.settings
        target = settings.music_volume * settings.master_volume / 100.0
        for step in range(8, -1, -1):
            self.player.set_volume(target * step / 8)
            time.sleep(0.035)

    def _advance(self, expected_id: str | None, fade: bool = False) -> None:
        """Finish the current song and start the next playable one.

        *expected_id* is the item that was current when the request was made;
        if something else is current by the time we run, the request is stale
        (e.g. Skip pressed just as the song ended) and is dropped.
        """
        while not self._closed:
            with self._lock:
                current_id = self.current.id if self.current else None
                if current_id != expected_id:
                    return
                playing = self.status == PlayStatus.PLAYING
            if fade and playing:
                self._fade_out()
            fade = False
            with self._lock:
                if (self.current.id if self.current else None) != expected_id:
                    return
                if self.current is not None and self._started:
                    self.queue.add_history(self.current.song)
                    self.library.save(self.queue.history())
                self._started = False
                item = self.queue.pop_next()
                self.current = item
                self.status = PlayStatus.LOADING if item else PlayStatus.IDLE
                self.position = 0.0
                self.duration = float(item.song.duration) if item else 0.0
                self.pitch = 0
                self.speed = 1.0
            self._emit_state()
            if item is None:
                self.player.stop()
                self._apply_volume()
                return
            try:
                source = self.resolver.resolve(item.song.video_id, self.settings.max_height)
                self.player.set_pitch(0)
                self.player.set_speed(1.0)
                self._apply_vocal_mode()
                stem = self.stems.path(item.song.video_id) if self.stems else None
                self.player.play(
                    source,
                    instrumental=stem,
                    use_instrumental=self.vocal_mode == VocalMode.INSTRUMENTAL,
                )
                self._apply_volume()
            except Exception as exc:
                log.warning("could not play %s: %s", item.song.video_id, exc)
                self.toast(f"Could not play: {item.song.title}", error=True)
                expected_id = item.id
                continue
            with self._lock:
                if self.current is item:
                    self.status = PlayStatus.PLAYING
            self._emit_state()
            self._prefetch_next()
            return

    def _on_player_end(self, reason: str) -> None:
        with self._lock:
            item = self.current
        if item is None:
            return
        if reason == "error":
            self.resolver.forget_stream(item.song.video_id, self.settings.max_height)
            attempts = self._retries.get(item.id, 0)
            if not self._started and attempts < _OPEN_RETRIES:
                # YouTube sporadically refuses a stream's first open; fresh URLs fix it.
                self._retries = {item.id: attempts + 1}
                self._executor.submit(self._restart, item.id)
                return
            self.toast(f"Playback error: {item.song.title}", error=True)
        self._executor.submit(self._advance, item.id)

    def _restart(self, item_id: str) -> None:
        with self._lock:
            item = self.current
        if item is None or item.id != item_id:
            return
        try:
            source = self.resolver.resolve(item.song.video_id, self.settings.max_height)
            stem = self.stems.path(item.song.video_id) if self.stems else None
            self.player.play(
                source,
                instrumental=stem,
                use_instrumental=self.vocal_mode == VocalMode.INSTRUMENTAL,
            )
        except Exception as exc:
            log.warning("retry failed for %s: %s", item.song.video_id, exc)
            self.toast(f"Could not play: {item.song.title}", error=True)
            self._advance(item_id)

    def _on_player_position(self, position: float, duration: float) -> None:
        self.position = position
        if position > 1.0:
            self._started = True
        if duration > 0:
            self.duration = duration
        now = time.monotonic()
        if now - self._last_position_emit >= _POSITION_INTERVAL:
            self._last_position_emit = now
            self.bus.emit("position", {"position": position, "duration": self.duration})

    def _prefetch_next(self) -> None:
        upcoming = self.queue.peek()
        if upcoming is None:
            return
        video_id = upcoming.song.video_id

        def work() -> None:
            try:
                self.resolver.resolve(video_id, self.settings.max_height)
            except Exception:
                log.debug("prefetch failed for %s", video_id, exc_info=True)

        self._prefetcher.submit(work)

    # -- sound ------------------------------------------------------------

    def set_vocal_mode(self, mode: VocalMode | str) -> None:
        self.vocal_mode = VocalMode(mode)
        self.settings.default_vocal_mode = self.vocal_mode.value
        self._apply_vocal_mode()
        if (
            self.vocal_mode == VocalMode.INSTRUMENTAL
            and self.current is not None
            and self.stems is not None
        ):
            # Covers songs queued while auto-separation was off.
            self.stems.request(self.current.song.video_id)
        self._save_soon()
        self._emit_state()

    def _apply_vocal_mode(self) -> None:
        if self.vocal_mode == VocalMode.INSTRUMENTAL:
            self.player.set_channel_mode(VocalMode.ORIGINAL)
            self.player.use_instrumental(True)
        else:
            self.player.use_instrumental(False)
            self.player.set_channel_mode(self.vocal_mode)

    def set_pitch(self, semitones: int) -> None:
        self.pitch = max(-PITCH_RANGE, min(PITCH_RANGE, int(semitones)))
        self.player.set_pitch(self.pitch)
        self._emit_state()

    def set_speed(self, speed: float) -> None:
        self.speed = min(SPEEDS, key=lambda s: abs(s - speed))
        self.player.set_speed(self.speed)
        self._emit_state()

    def set_volume(self, name: str, value: int) -> None:
        """Set ``music``, ``mic`` or ``master`` volume (0..100)."""
        value = max(0, min(100, int(value)))
        if name not in ("music", "mic", "master"):
            raise ValueError(f"unknown volume {name!r}")
        setattr(self.settings, f"{name}_volume", value)
        self._apply_volume()
        self._save_soon()
        self._emit_state()

    def _apply_volume(self) -> None:
        settings = self.settings
        # Mic and master gains are read live by the audio engine from settings.
        self.player.set_volume(settings.music_volume * settings.master_volume / 100.0)

    def set_output_device(self, name: str | None) -> None:
        self.settings.output_device = name or None
        self.player.set_audio_device(self.settings.output_device)
        self.restart_audio()

    def restart_audio(self) -> None:
        if self.audio is not None:
            self.audio.start()
        self._save_soon()
        self.bus.emit("mixer", None)

    def mixer_changed(self) -> None:
        """Call after editing mic strip values in ``settings`` directly."""
        self._save_soon()

    def play_sfx(self, name: str) -> bool:
        return bool(self.audio and self.audio.play_sfx(name))

    # -- separation -------------------------------------------------------

    def attach_stems(self, stems: StemManager) -> None:
        """Enable separation after start-up (the runtime was just downloaded)."""
        previous = self.stems
        stems.on_change = self._on_stem_change
        stems.order = self._stem_order
        self.stems = stems
        if previous is not None:
            previous.stop()
        if self.settings.auto_separate:
            for video_id in self._stem_order():
                stems.request(video_id)
        self._emit_state()

    def _stem_order(self) -> list[str]:
        with self._lock:
            order = [self.current.song.video_id] if self.current else []
        order += [item.song.video_id for item in self.queue.snapshot()]
        return order

    def _on_stem_change(self, video_id: str, status: StemStatus) -> None:
        if status == StemStatus.READY and self.stems is not None:
            with self._lock:
                is_current = self.current is not None and self.current.song.video_id == video_id
            path = self.stems.path(video_id)
            if is_current and path is not None:
                self.player.attach_instrumental(path)
                self.player.use_instrumental(self.vocal_mode == VocalMode.INSTRUMENTAL)
        self._emit_state()

    def stem_status(self, video_id: str) -> StemStatus:
        return self.stems.status(video_id) if self.stems else StemStatus.NONE

    # -- favourites -------------------------------------------------------

    def toggle_favorite(self, song: Song) -> bool:
        """Returns True when the song is a favourite afterwards."""
        if self.library.is_favorite(song.video_id):
            self.library.remove_favorite(song.video_id)
            result = False
        else:
            self.library.add_favorite(song)
            result = True
        self.bus.emit("favorites", None)
        return result

    # -- state ------------------------------------------------------------

    def toast(self, message: str, error: bool = False) -> None:
        self.bus.emit("toast", {"message": message, "error": error})

    def _item_dict(self, item: QueueItem) -> dict[str, Any]:
        data = item.to_dict()
        data["stem"] = self.stem_status(item.song.video_id).value
        return data

    def state(self) -> dict[str, Any]:
        with self._lock:
            current = self.current
            status = self.status
        settings = self.settings
        return {
            "version": __version__,
            "status": status.value,
            "current": self._item_dict(current) if current else None,
            "queue": [self._item_dict(item) for item in self.queue.snapshot()],
            "history": [song.to_dict() for song in self.queue.history()[:50]],
            "position": self.position,
            "duration": self.duration,
            "vocal_mode": self.vocal_mode.value,
            "pitch": self.pitch,
            "speed": self.speed,
            "music_volume": settings.music_volume,
            "mic_volume": settings.mic_volume,
            "master_volume": settings.master_volume,
            "separation": self.stems is not None,
            "accelerator": self.accelerator,
        }

    def _emit_state(self) -> None:
        self.bus.emit("state", None)

    def _save_soon(self) -> None:
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(1.0, self.store.save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def close(self) -> None:
        self._closed = True
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
        self.store.save()
        self.library.save(self.queue.history())
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._prefetcher.shutdown(wait=False, cancel_futures=True)
        if self.stems is not None:
            self.stems.stop()
        if self.audio is not None:
            self.audio.stop()
        self.player.close()
