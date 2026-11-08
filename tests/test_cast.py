"""Cast to Chromecast without a Chromecast, a display or a real ffmpeg."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from ytktv import cast


class FakeProcess:
    """Stands in for ffmpeg: takes frames, writes the playlist as soon as it starts."""

    def __init__(self, command: list[str], **_kwargs: Any) -> None:
        self.command = command
        self.frames = 0
        self.closed = threading.Event()
        folder = Path(command[-1]).parent
        (folder / cast.PLAYLIST).write_text("#EXTM3U\n")
        (folder / "seg0.ts").write_bytes(b"ts")
        process = self

        class Pipe:
            def write(self, data: bytes) -> None:
                if process.closed.is_set():
                    raise ValueError("closed")
                process.frames += 1

            def flush(self) -> None:
                pass

            def close(self) -> None:
                process.closed.set()

        self.stdin = Pipe()

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        pass


class FakeTarget:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.played: list[tuple[str, str]] = []
        self.stopped = 0
        self.lost: Callable[[], None] = lambda: None

    def play(self, url: str, content_type: str) -> None:
        if self.fail:
            raise cast.CastError("refused")
        self.played.append((url, content_type))

    def on_lost(self, callback: Callable[[], None]) -> None:
        self.lost = callback

    def stop(self) -> None:
        self.stopped += 1


DEVICE = cast.Device("Living Room TV", "8f1c7b5e-0000-4000-8000-000000000001", "192.168.1.30")


def make_stream() -> tuple[cast.CastStream, list[FakeProcess]]:
    started: list[FakeProcess] = []

    def popen(command: list[str], **kwargs: Any) -> FakeProcess:
        started.append(FakeProcess(command, **kwargs))
        return started[-1]

    return cast.CastStream("ffmpeg", width=64, height=36, fps=50, popen=popen), started


def test_ffmpeg_command_is_low_latency_hls(tmp_path: Path) -> None:
    command = cast.ffmpeg_command("/bin/ffmpeg", 1280, 720, 20, tmp_path)
    joined = " ".join(command)
    assert command[0] == "/bin/ffmpeg"
    assert "-s 1280x720" in joined and "-framerate 20" in joined and "-i pipe:0" in joined
    assert "-preset ultrafast" in joined and "-tune zerolatency" in joined
    assert "-g 20" in joined  # a keyframe every second
    assert "-hls_time 1" in joined and "delete_segments" in joined
    assert command[-1] == str(tmp_path / cast.PLAYLIST)


def test_stream_feeds_frames_and_cleans_up() -> None:
    stream, started = make_stream()
    stream.start()
    assert stream.running and stream.wait_ready(timeout=1)
    stream.push(b"\x01" * stream.frame_size)
    stream.push(b"short")  # ignored: wrong size
    folder, token = stream.folder, stream.token
    assert folder is not None and stream.file(token, "seg0.ts") == folder / "seg0.ts"
    assert stream.file("wrong", "seg0.ts") is None
    stream.stop()
    assert started[0].frames > 0 and started[0].closed.is_set()
    assert not folder.exists() and stream.file(token, cast.PLAYLIST) is None


def test_stream_serves_only_its_own_files() -> None:
    stream, _ = make_stream()
    stream.start()
    try:
        for name in ("../secret", "stream.m3u8/..", "seg1.mp4", "x.ts", "seg9.ts"):
            assert stream.file(stream.token, name) is None
    finally:
        stream.stop()


def test_caster_start_stop() -> None:
    stream, _ = make_stream()
    target = FakeTarget()
    changes: list[str] = []
    caster = cast.Caster(
        stream, "http://192.168.1.2:8000/", lambda _d: target, lambda s, _t: changes.append(s)
    )
    caster.start(DEVICE)
    assert caster.state == cast.CASTING and stream.running
    token = stream.token
    assert len(token) >= 32
    url = f"http://192.168.1.2:8000/cast/{token}/stream.m3u8"
    assert target.played == [(url, cast.CONTENT_TYPE)]
    caster.stop()
    assert stream.token == "" and stream.file(token, "stream.m3u8") is None
    assert caster.state == cast.IDLE and not stream.running and target.stopped == 1
    assert changes == [cast.CONNECTING, cast.CASTING, cast.IDLE]


def test_caster_failure_stops_the_stream() -> None:
    stream, _ = make_stream()
    caster = cast.Caster(stream, "http://h", lambda _d: FakeTarget(fail=True))
    caster.start(DEVICE)
    assert caster.state == cast.FAILED and not stream.running


def test_tv_disconnecting_stops_casting() -> None:
    stream, _ = make_stream()
    target = FakeTarget()
    texts: list[str] = []
    caster = cast.Caster(stream, "http://h", lambda _d: target, lambda _s, t: texts.append(t))
    caster.start(DEVICE)
    target.lost()
    assert caster.state == cast.IDLE and not stream.running
    assert "stopped playing" in texts[-1]
    target.lost()  # a second notice changes nothing
    assert len(texts) == 3


def test_server_serves_the_stream(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from tests.helpers import make_controller
    from ytktv.server.app import create_app

    stream, _ = make_stream()
    controller, _player, _resolver = make_controller(tmp_path)
    client = TestClient(create_app(controller, object(), cast=stream))  # type: ignore[arg-type]
    assert client.get("/cast/x/stream.m3u8").status_code == 404  # not casting
    stream.start()
    try:
        base = f"/cast/{stream.token}"
        # The Chromecast asks by IP address, which the host check lets through.
        reply = client.get(f"{base}/stream.m3u8", headers={"host": "192.168.1.2:8000"})
        assert reply.status_code == 200 and reply.text.startswith("#EXTM3U")
        assert reply.headers["access-control-allow-origin"] == "*"
        assert client.get(f"{base}/seg0.ts").headers["content-type"] == "video/mp2t"
        assert client.get(f"{base}/..%2Fsecret").status_code == 404
        # Someone else on the Wi-Fi without the secret sees nothing.
        assert client.get("/cast/wrong/stream.m3u8").status_code == 404
        assert client.get(f"{base}/stream.m3u8", headers={"host": "evil.com"}).status_code == 403
    finally:
        stream.stop()


@pytest.mark.usefixtures("qapp")
def test_frame_bytes_letterboxes() -> None:
    from PySide6.QtGui import QColor, QImage

    from ytktv.ui.cast_card import frame_bytes

    image = QImage(20, 20, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    data = frame_bytes(image, 30, 10)
    assert len(data) == 30 * 10 * 3
    assert data[:3] == b"\x00\x00\x00"  # black bar at the left
    middle = (5 * 30 + 15) * 3
    assert data[middle : middle + 3] == b"\xff\xff\xff"
