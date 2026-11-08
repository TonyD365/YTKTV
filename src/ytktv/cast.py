"""Chromecast: show the whole MV screen on a TV that cannot be a second display.

AirPlay and Miracast turn the TV into a display of its own. A Chromecast cannot, so the
MV window is filmed instead: its frames go into ffmpeg, which makes a live HLS stream
(H.264, one-second pieces) in a temporary folder. The phone remote's web server hands
those files out, and the Chromecast is told to play them. Only the picture travels;
the sound stays on the computer's speakers, where the microphones are mixed in.

Nothing here needs Qt, and pychromecast (the optional ``cast`` extra) is only imported
when a TV is searched for or connected to, so the pieces can be tested without either.
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Protocol

log = logging.getLogger(__name__)

PLAYLIST = "stream.m3u8"
CONTENT_TYPE = "application/x-mpegURL"
URL_PATH = "/cast/" + PLAYLIST
# Only ffmpeg's own file names are ever served, never a path someone made up.
_SERVED = re.compile(r"^(stream\.m3u8|seg\d{1,9}\.ts)$")


class CastError(Exception):
    """A TV could not be found, reached or told to play."""


@dataclass(frozen=True)
class Device:
    """A Chromecast found on the network."""

    name: str
    uuid: str
    host: str
    model: str = ""


def ffmpeg_command(ffmpeg: str, width: int, height: int, fps: int, folder: Path) -> list[str]:
    """Raw RGB frames on stdin in, a low-latency live HLS stream in *folder* out.

    A keyframe every second and one-second pieces let the TV start, and stay, close to
    live. The stream carries a silent sound track: some Chromecasts refuse HLS without one.
    """
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-framerate",
        str(fps),
        "-i",
        "pipe:0",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-tune",
        "zerolatency",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(fps),
        "-keyint_min",
        str(fps),
        "-sc_threshold",
        "0",
        "-b:v",
        "4M",
        "-maxrate",
        "4M",
        "-bufsize",
        "2M",
        "-c:a",
        "aac",
        "-b:a",
        "64k",
        "-shortest",
        "-f",
        "hls",
        "-hls_time",
        "1",
        "-hls_list_size",
        "4",
        "-hls_flags",
        "delete_segments+independent_segments+omit_endlist+temp_file",
        "-hls_segment_filename",
        str(folder / "seg%d.ts"),
        str(folder / PLAYLIST),
    ]


class CastStream:
    """ffmpeg turning the frames it is given into the live stream the TV plays.

    Frames are written at a steady rate from a thread of their own (the latest frame
    again when the screen has not produced a new one), so ffmpeg's clock never drifts
    from the real one and a slow frame never holds up the MV screen.
    """

    def __init__(
        self,
        ffmpeg: str,
        width: int = 1280,
        height: int = 720,
        fps: int = 20,
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self.ffmpeg = ffmpeg
        self.width, self.height, self.fps = width, height, fps
        self._popen = popen
        self._lock = threading.Lock()
        self._frame = bytes(self.frame_size)  # black until the first one arrives
        self._process: Any = None
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self.folder: Path | None = None
        self.on_ended: Callable[[], None] = lambda: None  # ffmpeg stopped by itself

    @property
    def frame_size(self) -> int:
        return self.width * self.height * 3

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def start(self) -> None:
        if self.running:
            return
        self.folder = Path(tempfile.mkdtemp(prefix="ytktv-cast-"))
        command = ffmpeg_command(self.ffmpeg, self.width, self.height, self.fps, self.folder)
        self._process = self._popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._running.set()
        self._thread = threading.Thread(target=self._feed, name="ytktv-cast", daemon=True)
        self._thread.start()

    def push(self, frame: bytes) -> None:
        """The newest picture of the MV screen, width x height RGB."""
        if len(frame) == self.frame_size:
            with self._lock:
                self._frame = frame

    def _feed(self) -> None:
        pipe: IO[bytes] = self._process.stdin
        step = 1.0 / self.fps
        due = time.monotonic()
        while self._running.is_set():
            with self._lock:
                frame = self._frame
            try:
                pipe.write(frame)
                pipe.flush()
            except (OSError, ValueError):
                if self._running.is_set():
                    log.warning("the cast stream's ffmpeg stopped")
                    self._running.clear()
                    self.on_ended()
                return
            due += step
            pause = due - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            else:
                due = time.monotonic()  # fell behind: do not try to catch up in a burst

    def wait_ready(
        self, timeout: float = 10.0, sleep: Callable[[float], None] = time.sleep
    ) -> bool:
        """Wait until the playlist exists, so the TV does not ask for it too early."""
        deadline = time.monotonic() + timeout
        while self.running and time.monotonic() < deadline:
            if self.file(PLAYLIST) is not None:
                return True
            sleep(0.1)
        return False

    def stop(self) -> None:
        self._running.clear()
        thread, process, folder = self._thread, self._process, self.folder
        self._thread, self._process, self.folder = None, None, None
        if process is not None:
            with contextlib.suppress(OSError, ValueError):
                process.stdin.close()
        if thread is not None:
            thread.join(timeout=2)
        if process is not None:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=2)
        if folder is not None:
            shutil.rmtree(folder, ignore_errors=True)

    def file(self, name: str) -> Path | None:
        """The stream file *name*, or None when it is not one (or not casting)."""
        folder = self.folder
        if folder is None or not _SERVED.match(name):
            return None
        path = folder / name
        return path if path.is_file() else None


class CastTarget(Protocol):
    """A connected TV (the pychromecast one, or a fake in tests)."""

    def play(self, url: str, content_type: str) -> None: ...

    def on_lost(self, callback: Callable[[], None]) -> None: ...

    def stop(self) -> None: ...


IDLE, CONNECTING, CASTING, FAILED = "idle", "connecting", "casting", "failed"


class Caster:
    """Starts and stops casting: the stream, the TV, and what the card shows.

    *on_change(state, text)* may be called from any thread.
    """

    def __init__(
        self,
        stream: CastStream,
        server_url: str,
        connect: Callable[[Device], CastTarget] | None = None,
        on_change: Callable[[str, str], None] = lambda _state, _text: None,
    ) -> None:
        self.stream = stream
        self.server_url = server_url.rstrip("/")
        self._connect = connect or ChromecastTarget
        self.on_change = on_change
        self.state = IDLE
        self.device: Device | None = None
        self._target: CastTarget | None = None
        self._lock = threading.RLock()
        stream.on_ended = lambda: self._ended("The video encoder stopped.")

    @property
    def url(self) -> str:
        return self.server_url + URL_PATH

    def _set(self, state: str, text: str) -> None:
        self.state = state
        self.on_change(state, text)

    def start(self, device: Device) -> None:
        """Blocks while the TV connects (a few seconds): call it off the GUI thread."""
        with self._lock:
            self._halt()
            self.device = device
            self._set(CONNECTING, f"Connecting to {device.name}…")
            try:
                self.stream.start()
                if not self.stream.wait_ready():
                    raise CastError("the video encoder did not start")
                target = self._connect(device)
                self._target = target
                target.on_lost(lambda: self._ended(f"{device.name} stopped playing."))
                target.play(self.url, CONTENT_TYPE)
            except Exception as exc:
                log.warning("casting to %s failed", device.name, exc_info=True)
                self._halt()
                self._set(FAILED, f"Could not cast to {device.name}: {exc}")
                return
            self._set(CASTING, f"Casting to {device.name}")

    def stop(self) -> None:
        with self._lock:
            was = self.state
            self._halt()
            if was != IDLE:
                self._set(IDLE, "Not casting")

    def _ended(self, text: str) -> None:
        """The TV went away or ffmpeg quit: clean up, say why."""
        with self._lock:
            if self.state != CASTING:
                return
            self._halt()
            self._set(IDLE, text)

    def _halt(self) -> None:
        target, self._target = self._target, None
        if target is not None:
            try:
                target.stop()
            except Exception:
                log.debug("could not stop the Chromecast", exc_info=True)
        self.stream.stop()
        self.state = IDLE


def discover(timeout: float = 4.0) -> list[Device]:
    """Chromecasts with a screen on the local network (not speakers or groups)."""
    try:
        from pychromecast import discovery
    except ImportError as exc:
        raise CastError("Chromecast support is not installed (the 'cast' extra)") from exc
    services, browser = discovery.discover_chromecasts(timeout=timeout)
    discovery.stop_discovery(browser)
    found = [
        Device(str(info.friendly_name), str(info.uuid), str(info.host), str(info.model_name))
        for info in services
        if info.cast_type in (None, "cast")
    ]
    return sorted(found, key=lambda device: device.name.lower())


class ChromecastTarget:
    """A real Chromecast, through pychromecast."""

    def __init__(self, device: Device) -> None:
        import uuid

        import pychromecast
        from pychromecast import discovery

        casts, self._browser = pychromecast.get_listed_chromecasts(
            uuids=[uuid.UUID(device.uuid)], known_hosts=[device.host], discovery_timeout=5
        )
        if not casts:
            discovery.stop_discovery(self._browser)
            raise CastError("not found on the network")
        self._cast = casts[0]
        self._cast.wait(timeout=10)
        self._lost: Callable[[], None] = lambda: None

    def play(self, url: str, content_type: str) -> None:
        media = self._cast.media_controller
        media.play_media(url, content_type, title="YTKTV", stream_type="LIVE")
        media.block_until_active(timeout=10)

    def on_lost(self, callback: Callable[[], None]) -> None:
        def lost() -> None:
            # Listeners run on pychromecast's own thread, which stop() waits for.
            threading.Thread(target=callback, name="ytktv-cast-lost", daemon=True).start()

        self._lost = lost
        target = self

        class Listener:
            def new_connection_status(self, status: Any) -> None:
                if status.status in ("LOST", "DISCONNECTED", "FAILED"):
                    target._lost()

            def new_media_status(self, status: Any) -> None:
                # Someone pressed stop on the TV, or it could not play the stream.
                if status.player_state == "IDLE" and status.idle_reason in (
                    "CANCELLED",
                    "ERROR",
                    "INTERRUPTED",
                    "FINISHED",
                ):
                    target._lost()

            def load_media_failed(self, _queue_item_id: int, _error_code: int) -> None:
                target._lost()

        listener: Any = Listener()  # pychromecast checks the methods, not the type
        self._cast.register_connection_listener(listener)
        self._cast.media_controller.register_status_listener(listener)

    def stop(self) -> None:
        from pychromecast import discovery

        self._lost = lambda: None
        try:
            self._cast.quit_app()
        finally:
            self._cast.disconnect(timeout=3)
            discovery.stop_discovery(self._browser)
