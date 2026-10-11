from __future__ import annotations

import os
import time
from pathlib import Path

from tests.helpers import wait_for
from ytktv.core.models import StemStatus
from ytktv.separation.base import FakeSeparator, detect_accelerator
from ytktv.separation.cache import StemCache
from ytktv.separation.worker import StemManager


def fake_download(video_id: str, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "source.wav"
    path.write_bytes(b"x" * 1000)
    return path


def test_process_writes_stem_and_cleans_work_dir(tmp_path):
    cache = StemCache(tmp_path, 10**9)
    separator = FakeSeparator()
    events = []
    manager = StemManager(cache, separator, fake_download, on_change=lambda v, s: events.append(s))
    assert manager.status("abc") == StemStatus.NONE
    manager.process("abc")
    assert events == [StemStatus.DOWNLOADING, StemStatus.SEPARATING, StemStatus.READY]
    assert manager.path("abc") == cache.target("abc")
    assert not (cache.folder("abc") / "work").exists()
    assert manager.request("abc") == StemStatus.READY and len(separator.calls) == 1


def test_failure_is_reported_and_leaves_nothing_behind(tmp_path):
    def broken(video_id: str, dest: Path) -> Path:
        raise RuntimeError("403")

    cache = StemCache(tmp_path, 10**9)
    manager = StemManager(cache, FakeSeparator(), broken)
    manager.process("abc")
    assert manager.status("abc") == StemStatus.FAILED
    assert manager.path("abc") is None and not cache.folder("abc").exists()


def test_worker_processes_in_the_order_the_room_needs(tmp_path):
    cache = StemCache(tmp_path, 10**9)
    done = []
    manager = StemManager(
        cache,
        FakeSeparator(),
        fake_download,
        on_change=lambda v, s: done.append(v) if s == StemStatus.READY else None,
        order=lambda: ["c", "b", "a"],
    )
    for video_id in ("a", "b", "c"):  # requested before the worker starts
        assert manager.request(video_id) == StemStatus.QUEUED
    assert manager.request("a") == StemStatus.QUEUED  # duplicate request is a no-op
    manager.start()
    try:
        wait_for(lambda: len(done) == 3)
    finally:
        manager.stop()
    assert done == ["c", "b", "a"]


def test_cache_prunes_least_recently_used_but_keeps_protected(tmp_path):
    cache = StemCache(tmp_path, limit_bytes=2500)
    now = time.time()
    for age, video_id in enumerate(("old", "mid", "new")):
        cache.folder(video_id).mkdir()
        cache.target(video_id).write_bytes(b"x" * 1000)
        os.utime(cache.folder(video_id), (now - 100 + age * 10, now - 100 + age * 10))
    assert cache.size() == 3000
    cache.prune(keep={"old"})
    assert cache.get("old") and cache.get("new") and cache.get("mid") is None


def test_detect_accelerator_reports_something():
    accelerator = detect_accelerator()
    assert accelerator.kind in ("cuda", "mps", "directml", "cpu", "unavailable")
    assert accelerator.label
