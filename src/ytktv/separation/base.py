"""Vocal/instrumental separation interface and hardware detection."""

from __future__ import annotations

import importlib.util
import platform
import shutil
import subprocess
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class Accelerator:
    kind: str  # "cuda", "mps", "directml", "cpu", "unavailable"
    label: str

    @property
    def is_gpu(self) -> bool:
        return self.kind in ("cuda", "mps", "directml")


def separation_installed() -> bool:
    return importlib.util.find_spec("audio_separator") is not None


def _apple_chip() -> str:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "Apple Silicon"
    except Exception:
        return "Apple Silicon"


def detect_accelerator() -> Accelerator:
    """Report which device separation will run on (GPU whenever one is usable)."""
    if not separation_installed():
        return Accelerator("unavailable", "Not installed")
    try:
        import torch
    except Exception:
        return Accelerator("cpu", "CPU")
    try:
        if torch.cuda.is_available():
            return Accelerator("cuda", f"GPU: {torch.cuda.get_device_name(0)} (CUDA)")
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available() and platform.machine() == "arm64":
            return Accelerator("mps", f"GPU: {_apple_chip()} (Metal)")
        if importlib.util.find_spec("torch_directml") is not None:
            return Accelerator("directml", "GPU: DirectML")
    except Exception:
        pass
    return Accelerator("cpu", "CPU")
