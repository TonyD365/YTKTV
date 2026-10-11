"""Vocal/instrumental separation interface."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Protocol


class Separator(Protocol):
    def separate(self, source: Path, out_path: Path) -> None:
        """Write the instrumental (vocals removed) of *source* to *out_path*."""
        ...


class FakeSeparator:
    """Copies the input; lets tests exercise the pipeline without a model."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def separate(self, source: Path, out_path: Path) -> None:
        self.calls.append(source)
        shutil.copyfile(source, out_path)


def separation_installed() -> bool:
    return importlib.util.find_spec("audio_separator") is not None
