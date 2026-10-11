from __future__ import annotations

import threading
from pathlib import Path

from tests.helpers import wait_for
from ytktv.core.preload import MediaPreloader


def make(tmp_path, fail=(), gate=None):
    started: list[str] = []

    def download(video_id: str, dest: Path) -> Path:
        started.append(video_id)
        if gate is not None:
            gate.wait(5)
        if video_id in fail:
            raise RuntimeError("403")
        dest.mkdir(parents=True, exist_ok=True)
        path = dest / "media.mkv"
        path.write_bytes(b"video")
        return path

    changed: list[str] = []
    preloader = MediaPreloader(tmp_path / "media", download, on_change=changed.append)
    preloader.start()
    return preloader, started, changed


def test_downloads_in_order_and_reports_ready(tmp_path):
    preloader, started, changed = make(tmp_path)
    try:
        assert preloader.status("a") == "none"
        preloader.sync(["a", "b"])
        wait_for(lambda: preloader.path("a") is not None and preloader.path("b") is not None)
        assert started == ["a", "b"] and changed == ["a", "b"]
        assert preloader.status("a") == "ready"
        preloader.sync(["a", "b"])  # nothing new: no second download
        assert started == ["a", "b"]
    finally:
        preloader.stop()
    assert not (tmp_path / "media").exists()


def test_songs_that_leave_the_queue_are_deleted_but_the_current_one_is_kept(tmp_path):
    preloader, _, _ = make(tmp_path)
    try:
        preloader.sync(["a", "b"])
        wait_for(lambda: preloader.path("b") is not None)
        file_a, file_b = preloader.path("a"), preloader.path("b")
        preloader.sync(["c"], keep={"a"})  # a is now playing, b was removed
        assert file_a.exists() and preloader.path("a") == file_a
        assert not file_b.exists() and preloader.path("b") is None
        wait_for(lambda: preloader.path("c") is not None)
        preloader.sync([], keep=set())  # a finished
        assert not file_a.exists()
    finally:
        preloader.stop()


def test_failed_download_is_not_retried_in_a_loop_and_falls_back_to_streaming(tmp_path):
    preloader, started, changed = make(tmp_path, fail={"a"})
    try:
        preloader.sync(["a", "b"])
        wait_for(lambda: preloader.path("b") is not None)
        assert started == ["a", "b"]
        assert preloader.path("a") is None and preloader.status("a") == "none"
        assert changed == ["a", "b"]
    finally:
        preloader.stop()


def test_download_finishing_after_removal_is_discarded(tmp_path):
    gate = threading.Event()
    preloader, started, _ = make(tmp_path, gate=gate)
    try:
        preloader.sync(["a"])
        wait_for(lambda: started == ["a"])
        assert preloader.status("a") == "loading"
        preloader.sync([])  # removed from the queue while still downloading
        gate.set()
        wait_for(lambda: not (tmp_path / "media" / "a").exists())
        assert preloader.path("a") is None
    finally:
        gate.set()
        preloader.stop()


def test_leftovers_from_a_previous_run_are_cleared(tmp_path):
    stale = tmp_path / "media" / "old"
    stale.mkdir(parents=True)
    (stale / "media.mkv").write_bytes(b"x")
    preloader, _, _ = make(tmp_path)
    try:
        assert not stale.exists()
    finally:
        preloader.stop()
