"""Vocal/instrumental separation interface."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Protocol


class Separator(Protocol):
    def separate(self, source: Path, out_path: Path, pitch_path: Path | None = None) -> None:
        """Write the instrumental (vocals removed) of *source* to *out_path*.

        With *pitch_path*, also write the singer's melody there as JSON:
        ``{"hop": seconds, "notes": [MIDI note or null, ...]}``.
        """
        ...


class FakeSeparator:
    """Copies the input; lets tests exercise the pipeline without a model."""

    def __init__(self) -> None:
        self.calls: list[Path] = []

    def separate(self, source: Path, out_path: Path, pitch_path: Path | None = None) -> None:
        self.calls.append(source)
        shutil.copyfile(source, out_path)
        if pitch_path is not None:
            pitch_path.write_text('{"hop":0.05,"notes":[60.0,60.0,null,62.0]}', encoding="utf-8")


def separation_installed() -> bool:
    return importlib.util.find_spec("audio_separator") is not None
