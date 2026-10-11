"""KTVController: the single entry point for every command in the app.

The desktop UI, the phone web page and the player callbacks all go through
this class, so they can never disagree about what is playing.
"""

from __future__ import annotations

import logging
import random
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
from ytktv.core.scoring import Melody, ScoreKeeper, ScoringLoop
from ytktv.player.base import PlayerBackend
from ytktv.youtube.parse import MediaSource

if TYPE_CHECKING:
    from ytktv.audio.engine import AudioEngine
    from ytktv.core.preload import MediaPreloader
    from ytktv.separation.worker import StemManager

log = logging.getLogger(__name__)

PITCH_RANGE = 6  # semitones either way
SPEEDS = (0.8, 0.9, 1.0, 1.1, 1.2)
_POSITION_INTERVAL = 0.5
_OPEN_RETRIES = 2
_PRELOAD_AHEAD = 2  # how many upcoming songs to keep downloaded
_DANMAKU_LENGTH = 60
_DANMAKU_BURST = 8  # messages allowed per window, across everyone
_DANMAKU_WINDOW = 4.0
_INSTRUMENTAL_WAIT = 180.0  # longest a song is held back for its instrumental


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
        preloader: MediaPreloader | None = None,
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
        self.preloader = preloader

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
        self.loading = ""  # what the room is waiting for while status is LOADING
        self._skip_wait: str | None = None
        self._awaiting_start = False  # play() was called and the first frame is pending
        self.lyrics: list[Any] = []  # timed lines for the current song, if its video has subtitles
        self._danmaku_times: list[float] = []
        self._keeper: ScoreKeeper | None = None  # scores the song that is playing
        self.last_score: dict[str, Any] | None = None
        self._scoring_loop: ScoringLoop | None = None
        self._wake = threading.Event()
        self._retries: dict[str, int] = {}
        self._save_timer: threading.Timer | None = None
        self._closed = False

        player.on_end = self._on_player_end
        player.on_position = self._on_player_position
        if stems is not None:
            stems.on_change = self._on_stem_change
            stems.order = self._stem_order
        if preloader is not None:
            preloader.on_change = lambda _video_id: self._emit_state()
        if stems is not None:
            stems.want_pitch = self.settings.scoring
        if audio is not None:
            self._scoring_loop = ScoringLoop(audio.mic_pitch, self._scoring_target)
            self._scoring_loop.start()
        self._apply_volume()
        player.set_guide(self.settings.guide_vocal / 100.0)
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

    def enqueue_many(self, songs: list[Song], singer: str = "", shuffle: bool = False) -> int:
        """Queue several songs at once (a playlist). Returns how many were added."""
        songs = list(songs)
        if shuffle:
            random.shuffle(songs)
        if not songs:
            return 0
        for song in songs:
            self.queue.add(song, singer=singer)
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
        self.toast(f"Added {len(songs)} songs")
        self._emit_state()
        return len(songs)

    def remove(self, item_id: str) -> bool:
        ok = self.queue.remove(item_id)
        if ok:
            self._sync_preload()
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
        self._sync_preload()
        self._emit_state()

    # -- transport --------------------------------------------------------

    def skip(self) -> None:
        with self._lock:
            current_id = self.current.id if self.current else None
            if current_id is None and self.status != PlayStatus.IDLE:
                return  # already switching songs
            self._skip_wait = current_id  # in case the song is still waiting to start
        self._wake.set()
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
                    self._announce_score(self.current)
                self._keeper = None
                self._started = False
                item = self.queue.pop_next()
                self.current = item
                self.status = PlayStatus.LOADING if item else PlayStatus.IDLE
                self.loading = "Loading video" if item else ""
                self._awaiting_start = False
                self.lyrics = []
                self.position = 0.0
                self.duration = float(item.song.duration) if item else 0.0
                self.pitch = 0
                self.speed = 1.0
            self._sync_preload()
            self.bus.emit("lyrics", {"id": item.id if item else None, "lines": []})
            self._emit_state()
            # Silence the previous song now: the next one may take a while to be ready.
            self.player.stop()
            self._apply_volume()
            if item is None:
                return
            if not self._wait_for_instrumental(item):
                expected_id = item.id  # skipped while waiting
                continue
            try:
                video_id = item.song.video_id
                local = self.preloader.path(video_id) if self.preloader else None
                if local is not None:
                    source = MediaSource(video_url=str(local))
                else:
                    source = self.resolver.resolve(video_id, self.settings.max_height)
                is_limited = getattr(self.resolver, "is_limited", None)
                if is_limited is not None and is_limited(video_id):
                    self.toast("YouTube limits this video to 360p. See Settings to unlock HD.")
                self.player.set_pitch(0)
                self.player.set_speed(1.0)
                self._apply_vocal_mode()
                stem = self.stems.path(video_id) if self.stems else None
                self._awaiting_start = True
                self.player.play(
                    source,
                    instrumental=stem,
                    use_instrumental=self.vocal_mode == VocalMode.INSTRUMENTAL,
                )
                self._apply_volume()
            except Exception as exc:
                self._awaiting_start = False
                log.warning("could not play %s: %s", item.song.video_id, exc)
                self.toast(f"Could not play: {item.song.title}", error=True)
                expected_id = item.id
                continue
            # Status stays LOADING until the player reports its first position.
            self._load_melody(item)
            self._load_lyrics(item)
            self._prefetch_next()
            return

    def _wait_for_instrumental(self, item: QueueItem) -> bool:
        """Hold a song until its instrumental is ready, so it never switches mid-song.

        Only applies in Instrumental mode. Returns False if the song was
        skipped during the wait. Choosing another vocal mode ends the wait.
        """
        if self.stems is None or not self.settings.wait_for_instrumental:
            return True
        video_id = item.song.video_id
        deadline = time.monotonic() + _INSTRUMENTAL_WAIT
        announced = False
        while not self._closed and time.monotonic() < deadline:
            with self._lock:
                if self._skip_wait == item.id:
                    self._skip_wait = None
                    return False
                if self.current is not item:
                    return False
            if self.vocal_mode != VocalMode.INSTRUMENTAL:
                break
            status = self.stems.status(video_id)
            if status == StemStatus.NONE:
                status = self.stems.request(video_id)
            if status in (StemStatus.READY, StemStatus.FAILED):
                break
            if not announced:
                announced = True
                with self._lock:
                    self.loading = "Preparing instrumental"
                self._emit_state()
            self._wake.wait(0.25)
            self._wake.clear()
        if announced:
            with self._lock:
                self.loading = "Loading video"
            self._emit_state()
        return True

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
            self._awaiting_start = True
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
        if self.status == PlayStatus.LOADING:
            if not self._awaiting_start:
                return  # a late report from the previous song
            with self._lock:
                if self.status == PlayStatus.LOADING and self._awaiting_start:
                    self._awaiting_start = False
                    self.status = PlayStatus.PLAYING
                    self.loading = ""
            self._emit_state()
        self.position = position
        if position > 1.0:
            self._started = True
        if duration > 0:
            self.duration = duration
        now = time.monotonic()
        if now - self._last_position_emit >= _POSITION_INTERVAL:
            self._last_position_emit = now
            self.bus.emit(
                "position",
                {"position": position, "duration": self.duration, "score": self.live_score()},
            )

    def _sync_preload(self) -> None:
        """Tell the background workers which songs still matter after a queue change."""
        if self.stems is not None:
            # A removed or skipped song must not keep the separator busy.
            self.stems.retain(set(self._stem_order()))
        if self.preloader is None:
            return
        with self._lock:
            keep = {self.current.song.video_id} if self.current else set()
        if not self.settings.preload_queue:
            self.preloader.sync([], keep)
            return
        upcoming = [item.song.video_id for item in self.queue.snapshot()[:_PRELOAD_AHEAD]]
        self.preloader.sync(upcoming, keep)

    def _prefetch_next(self) -> None:
        self._sync_preload()
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
        self._wake.set()
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

    def set_guide_vocal(self, percent: int) -> None:
        """How much of the original singer to keep in Instrumental mode (0..100)."""
        self.settings.guide_vocal = max(0, min(100, int(percent)))
        self.player.set_guide(self.settings.guide_vocal / 100.0)
        self._save_soon()
        self._emit_state()

    # -- scoring ----------------------------------------------------------

    def set_scoring(self, enabled: bool) -> None:
        self.settings.scoring = bool(enabled)
        if self.stems is not None:
            self.stems.want_pitch = self.settings.scoring
            if self.settings.scoring:
                # Songs separated before scoring was on have no melody yet: fetch it.
                for video_id in self._stem_order():
                    self.stems.request(video_id)
        with self._lock:
            item = self.current
            if not self.settings.scoring:
                self._keeper = None
        if self.settings.scoring and item is not None:
            self._load_melody(item)
        self._save_soon()
        self._emit_state()

    def _load_melody(self, item: QueueItem) -> None:
        """Start scoring *item* if scoring is on and its melody has been extracted."""
        if not self.settings.scoring or self.stems is None:
            return
        path = self.stems.pitch(item.song.video_id)
        if path is None:
            return
        try:
            melody = Melody.load(path)
        except Exception:
            log.warning("unreadable melody for %s", item.song.video_id, exc_info=True)
            return
        with self._lock:
            if self.current is item and self._keeper is None:
                self._keeper = ScoreKeeper(melody, transpose=float(self.pitch))

    def _scoring_target(self) -> tuple[ScoreKeeper, float] | None:
        with self._lock:
            if self._keeper is None or self.status != PlayStatus.PLAYING:
                return None
            return self._keeper, self.position

    def live_score(self) -> int | None:
        keeper = self._keeper
        result = keeper.result() if keeper is not None else None
        return result.points if result is not None else None

    def _announce_score(self, item: QueueItem) -> None:
        keeper = self._keeper
        result = keeper.result() if keeper is not None else None
        if result is None:
            return
        self.last_score = {**result.to_dict(), "title": item.song.title, "singer": item.singer}
        self.bus.emit("score", self.last_score)

    def set_lights(self, enabled: bool) -> None:
        self.settings.lights = bool(enabled)
        self._save_soon()
        self._emit_state()

    def send_danmaku(self, text: str) -> bool:
        """Fly a short message across the MV screen. False when empty or sent too fast."""
        text = " ".join(str(text).split())[:_DANMAKU_LENGTH]
        if not text:
            return False
        now = time.monotonic()
        with self._lock:
            self._danmaku_times = [t for t in self._danmaku_times if now - t < _DANMAKU_WINDOW]
            if len(self._danmaku_times) >= _DANMAKU_BURST:
                return False
            self._danmaku_times.append(now)
        self.bus.emit("danmaku", {"text": text})
        return True

    def _load_lyrics(self, item: QueueItem) -> None:
        fetch = getattr(self.resolver, "lyrics", None)
        if fetch is None or not self.settings.show_lyrics:
            return

        def work() -> None:
            try:
                lines = fetch(
                    item.song.video_id,
                    self.settings.max_height,
                    self.settings.lyrics_auto_captions,
                )
            except Exception:
                log.info("no lyrics for %s", item.song.video_id, exc_info=True)
                return
            with self._lock:
                if self.current is not item:
                    return
                self.lyrics = lines
            self.bus.emit("lyrics", {"id": item.id, "lines": [line.to_dict() for line in lines]})
            self._emit_state()

        self._prefetcher.submit(work)

    def set_pitch(self, semitones: int) -> None:
        self.pitch = max(-PITCH_RANGE, min(PITCH_RANGE, int(semitones)))
        self.player.set_pitch(self.pitch)
        keeper = self._keeper
        if keeper is not None:
            keeper.transpose = float(self.pitch)  # the melody moves with the key
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
        self._wake.set()
        if status == StemStatus.READY and self.stems is not None:
            with self._lock:
                is_current = self.current is not None and self.current.song.video_id == video_id
            path = self.stems.path(video_id)
            if is_current and path is not None:
                self.player.attach_instrumental(path)
                self.player.use_instrumental(self.vocal_mode == VocalMode.INSTRUMENTAL)
            with self._lock:
                playing = self.current if is_current else None
            if playing is not None:
                self._load_melody(playing)
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

    # -- playlists --------------------------------------------------------

    def playlists(self) -> list[dict[str, Any]]:
        library = self.library
        return [
            {"name": name, "count": len(library.playlist(name) or [])}
            for name in library.playlist_names()
        ]

    def create_playlist(self, name: str, songs: list[Song] | None = None) -> str:
        created = self.library.create_playlist(name, songs)
        self.bus.emit("playlists", None)
        return created

    def delete_playlist(self, name: str) -> bool:
        ok = self.library.delete_playlist(name)
        if ok:
            self.bus.emit("playlists", None)
        return ok

    def add_to_playlist(self, name: str, song: Song) -> bool:
        ok = self.library.add_to_playlist(name, song)
        if ok:
            self.bus.emit("playlists", None)
            self.toast(f"Added to {name}")
        return ok

    def remove_from_playlist(self, name: str, video_id: str) -> bool:
        ok = self.library.remove_from_playlist(name, video_id)
        if ok:
            self.bus.emit("playlists", None)
        return ok

    def save_queue_as_playlist(self, name: str) -> str:
        """Save what is playing plus everything queued as a new playlist."""
        with self._lock:
            songs = [self.current.song] if self.current else []
        songs += [item.song for item in self.queue.snapshot()]
        if not songs:
            raise ValueError("there is nothing in the queue to save")
        return self.create_playlist(name, songs)

    def import_playlist(self, url: str) -> str:
        """Import a YouTube playlist (network; call off the GUI thread). Returns its name."""
        fetch = getattr(self.resolver, "playlist", None)
        if fetch is None:
            raise ValueError("playlist import is not available")
        title, songs = fetch(url)
        name = self.create_playlist(self.library.unique_playlist_name(title), songs)
        self.toast(f"Imported {len(songs)} songs into {name}")
        return name

    def enqueue_playlist(self, name: str, shuffle: bool = False, singer: str = "") -> int:
        songs = self.library.playlist(name)
        if songs is None:
            raise KeyError(name)
        return self.enqueue_many(songs, singer=singer, shuffle=shuffle)

    # -- state ------------------------------------------------------------

    def toast(self, message: str, error: bool = False) -> None:
        self.bus.emit("toast", {"message": message, "error": error})

    def _item_dict(self, item: QueueItem) -> dict[str, Any]:
        data = item.to_dict()
        data["stem"] = self.stem_status(item.song.video_id).value
        data["preload"] = self.preloader.status(item.song.video_id) if self.preloader else "none"
        return data

    def state(self) -> dict[str, Any]:
        with self._lock:
            current = self.current
            status = self.status
        settings = self.settings
        return {
            "version": __version__,
            "status": status.value,
            "loading": self.loading if status == PlayStatus.LOADING else "",
            "current": self._item_dict(current) if current else None,
            "queue": [self._item_dict(item) for item in self.queue.snapshot()],
            "history": [song.to_dict() for song in self.queue.history()[:50]],
            "position": self.position,
            "duration": self.duration,
            "vocal_mode": self.vocal_mode.value,
            "pitch": self.pitch,
            "speed": self.speed,
            "guide_vocal": settings.guide_vocal,
            "lyrics": bool(self.lyrics),
            "lights": settings.lights,
            "scoring": settings.scoring,
            "scoring_active": self._keeper is not None,
            "last_score": self.last_score,
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
        self._wake.set()
        if self._scoring_loop is not None:
            self._scoring_loop.stop()
        if self.stems is not None:
            self.stems.stop()
        if self.preloader is not None:
            self.preloader.stop()
        if self.audio is not None:
            self.audio.stop()
        self.player.close()
