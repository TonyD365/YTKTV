"""On-disk cache of instrumental tracks, keyed by video id."""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

STEM_NAME = "instrumental.flac"


class StemCache:
    def __init__(self, root: Path, limit_bytes: int) -> None:
        self.root = root
        self.limit_bytes = limit_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, video_id: str) -> Path:
        return self.root / video_id

    def target(self, video_id: str) -> Path:
        return self.folder(video_id) / STEM_NAME

    def get(self, video_id: str) -> Path | None:
        path = self.target(video_id)
        if not path.exists():
            return None
        with contextlib.suppress(OSError):
            os.utime(path.parent)  # mark as recently used for LRU
        return path

    def _entries(self) -> list[tuple[float, int, Path]]:
        entries = []
        for folder in self.root.iterdir():
            stem = folder / STEM_NAME
            if folder.is_dir() and stem.exists():
                entries.append((folder.stat().st_mtime, stem.stat().st_size, folder))
        return entries

    def size(self) -> int:
        return sum(size for _, size, _ in self._entries())

    def prune(self, keep: set[str] | None = None) -> None:
        """Delete least-recently-used stems until the cache fits its limit."""
        keep = keep or set()
        entries = sorted(self._entries())
        total = sum(size for _, size, _ in entries)
        for _, size, folder in entries:
            if total <= self.limit_bytes:
                break
            if folder.name in keep:
                continue
            shutil.rmtree(folder, ignore_errors=True)
            total -= size
            log.info("evicted stem %s", folder.name)
