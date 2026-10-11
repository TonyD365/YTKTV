"""Separation with UVR models through the ``audio-separator`` package.

The package picks the fastest device by itself: CUDA on NVIDIA, Metal (MPS)
plus CoreML on Apple Silicon, DirectML on Windows when installed, else CPU.
"""

from __future__ import annotations

import logging
import platform
import shutil
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class UvrSeparator:
    def __init__(self, model: str, model_dir: Path, work_dir: Path) -> None:
        self.model = model
        self.model_dir = model_dir
        self.work_dir = work_dir
        self._lock = threading.Lock()
        self._separator: Any = None

    def _ensure_loaded(self) -> Any:
        if self._separator is None:
            from audio_separator.separator import Separator

            self.model_dir.mkdir(parents=True, exist_ok=True)
            self.work_dir.mkdir(parents=True, exist_ok=True)
            separator = Separator(
                log_level=logging.WARNING,
                model_file_dir=str(self.model_dir),
                output_dir=str(self.work_dir),
                output_format="FLAC",  # lossless and sample-exact, so it stays in sync
                output_single_stem="Instrumental",
                use_directml=platform.system() == "Windows",
            )
            separator.load_model(model_filename=self.model)
            self._separator = separator
        return self._separator

    def separate(self, source: Path, out_path: Path) -> None:
        with self._lock:
            separator = self._ensure_loaded()
            outputs = separator.separate(str(source))
            if not outputs:
                raise RuntimeError("separation produced no output")
            produced = Path(outputs[0])
            if not produced.is_absolute():
                produced = self.work_dir / produced
            if not produced.exists():
                produced = self.work_dir / produced.name
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(produced), out_path)
