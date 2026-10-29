"""The downloadable separation runtime for packaged Windows and Linux builds.

On first run the app looks at the graphics hardware, then downloads a private
Python environment holding the matching build of the separation libraries:
CUDA for NVIDIA cards, DirectML for other GPUs on Windows, CPU otherwise.
The environment is created with ``uv``, which ships inside the app.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ytktv import bootstrap
from ytktv.config import data_dir

log = logging.getLogger(__name__)

PYTHON_VERSION = "3.12"
MARKER = "runtime.json"
# Bump when the package list changes so existing installs are rebuilt.
RUNTIME_REVISION = 1

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
Report = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class Gpu:
    vendor: str  # "nvidia", "amd" or "intel"
    name: str
    cuda: bool = False  # an NVIDIA card whose driver is installed


@dataclass(frozen=True, slots=True)
class Variant:
    key: str
    title: str
    download_size: str
    packages: tuple[str, ...]
    torch_backend: str | None  # value for uv's --torch-backend; None leaves torch to the resolver
    directml: bool = False


VARIANTS: dict[str, Variant] = {
    "cuda": Variant(
        "cuda",
        "NVIDIA GPU (CUDA)",
        "about 2.5 GB",
        ("audio-separator[gpu]", "audioread"),
        "auto",  # uv picks the CUDA build that matches the installed driver
    ),
    "directml": Variant(
        "directml",
        "GPU (DirectML)",
        "about 1 GB",
        ("audio-separator[dml]", "audioread"),
        None,  # torch-directml pins its own torch
        directml=True,
    ),
    "cpu": Variant(
        "cpu",
        "CPU",
        "about 500 MB",
        ("audio-separator[cpu]", "audioread"),
        "cpu",
    ),
}
# What to try next when a variant cannot be installed or does not start.
FALLBACK = {"cuda": "cpu", "directml": "cpu"}


def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("errors", "replace")
    kwargs.setdefault("creationflags", getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return subprocess.run(command, **kwargs)


def supported(
    system: str | None = None, frozen: bool | None = None, machine: str | None = None
) -> bool:
    """Whether this build gets its separation runtime by download."""
    if os.environ.get("YTKTV_SEPARATION_RUNTIME") == "1":
        return True
    system = system or platform.system()
    machine = (machine if machine is not None else platform.machine()).lower()
    frozen = bootstrap.is_frozen() if frozen is None else frozen
    return frozen and system in ("Windows", "Linux")


def runtime_python(system: str | None = None, machine: str | None = None) -> str:
    """The Python uv puts in the separation runtime.

    On Windows on ARM it is the x64 one: some separation libraries have no ARM builds
    for Windows yet, and Windows runs x64 programs under emulation. Only the separation
    worker runs there; YTKTV itself stays native.
    """
    system = system or platform.system()
    machine = (machine if machine is not None else platform.machine()).lower()
    if system == "Windows" and machine in ("arm64", "aarch64"):
        return f"cpython-{PYTHON_VERSION}-windows-x86_64-none"
    return PYTHON_VERSION


def _classify(name: str) -> str | None:
    lowered = name.lower()
    if "nvidia" in lowered or "geforce" in lowered or "quadro" in lowered or "rtx" in lowered:
        return "nvidia"
    if "amd" in lowered or "radeon" in lowered:
        return "amd"
    if "intel" in lowered:
        return "intel"
    return None  # e.g. "Microsoft Basic Display Adapter", virtual adapters


def detect_gpu(system: str | None = None, run: Runner = _run) -> Gpu | None:
    """The best graphics card for separation, or None when only the CPU can be used.

    An NVIDIA card only counts when its driver is installed (``nvidia-smi``
    answers); the CUDA libraries are downloadable but the driver is not.
    """
    system = system or platform.system()
    try:
        result = run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=15)
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if result.returncode == 0 and names:
            return Gpu("nvidia", names[0], cuda=True)
    except (OSError, subprocess.SubprocessError):
        pass
    if system != "Windows":
        return None
    try:
        result = run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }",
            ],
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    found: dict[str, str] = {}
    for line in result.stdout.splitlines():
        vendor = _classify(line)
        if vendor and vendor not in found:
            found[vendor] = line.strip()
    # Discrete cards before integrated graphics. An NVIDIA card that got here has no
    # working driver, so it cannot run CUDA; DirectML can still use it.
    for vendor in ("nvidia", "amd", "intel"):
        if vendor in found:
            return Gpu(vendor, found[vendor])
    return None


def choose_variant(system: str, gpu: Gpu | None, machine: str = "") -> str:
    """The runtime to install; *machine* is platform.machine() of the PC it is for."""
    if gpu is None or machine.lower() in ("arm64", "aarch64"):
        # ARM (Windows on ARM laptops, Raspberry Pi-class boxes): no CUDA or DirectML
        # builds there, but the CPU runtime works.
        return "cpu"
    if gpu.cuda:
        return "cuda"
    if system == "Windows":
        return "directml"
    return "cpu"  # AMD and Intel GPUs on Linux have no practical runtime here


def find_uv() -> str | None:
    name = "uv.exe" if platform.system() == "Windows" else "uv"
    bundled = bootstrap.bundle_dir()
    if bundled and (bundled / name).exists():
        return str(bundled / name)
    on_path = shutil.which("uv")
    if on_path:
        return on_path
    try:
        from uv import find_uv_bin

        return str(find_uv_bin())
    except Exception:
        return None


class Runtime:
    """Installs and locates the separation environment under *root*."""

    def __init__(self, root: Path | None = None, system: str | None = None) -> None:
        self.root = root or data_dir() / "separation-runtime"
        self.system = system or platform.system()

    @property
    def env_dir(self) -> Path:
        return self.root / "env"

    @property
    def python(self) -> Path:
        if self.system == "Windows":
            return self.env_dir / "Scripts" / "python.exe"
        return self.env_dir / "bin" / "python"

    def installed_variant(self) -> str | None:
        try:
            marker = json.loads((self.root / MARKER).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if marker.get("revision") != RUNTIME_REVISION or not self.python.exists():
            return None
        variant = marker.get("variant")
        return variant if variant in VARIANTS else None

    def install_commands(self, variant: Variant, uv: str) -> list[tuple[str, list[str]]]:
        """(description, command) pairs, in order."""
        base = [uv, "--no-progress", "--color", "never"]
        install = [*base, "pip", "install", "--python", str(self.python), *variant.packages]
        if variant.torch_backend:
            install += ["--torch-backend", variant.torch_backend]
        venv = [
            *base,
            "venv",
            str(self.env_dir),
            "--python",
            runtime_python(self.system),
            "--managed-python",
        ]
        return [
            (f"Downloading Python {PYTHON_VERSION}", venv),
            (f"Downloading the separation libraries ({variant.download_size})", install),
        ]

    def install(self, key: str, report: Report = lambda _line: None, run: Runner = _run) -> None:
        """Download and install *key*. Raises on failure and leaves nothing half-installed."""
        variant = VARIANTS[key]
        uv = find_uv()
        if uv is None:
            raise RuntimeError("the uv installer is missing from this build")
        self.remove()
        self.root.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ)
        # Keep everything uv downloads inside our folder so removing it removes all of it.
        env["UV_PYTHON_INSTALL_DIR"] = str(self.root / "python")
        env["UV_CACHE_DIR"] = str(self.root / "cache")
        env.pop("VIRTUAL_ENV", None)
        try:
            for description, command in self.install_commands(variant, uv):
                report(description + "...")
                result = run(command, env=env, timeout=3 * 60 * 60)
                if result.returncode != 0:
                    detail = (result.stderr or result.stdout or "").strip()[-600:]
                    raise RuntimeError(f"{description} failed: {detail}")
            marker = {"variant": key, "revision": RUNTIME_REVISION, "python": PYTHON_VERSION}
            (self.root / MARKER).write_text(json.dumps(marker), encoding="utf-8")
        except BaseException:
            self.remove()
            raise
        finally:
            shutil.rmtree(self.root / "cache", ignore_errors=True)

    def install_with_fallback(self, key: str, report: Report = lambda _line: None) -> str:
        """Install *key*, or a simpler variant if that fails. Returns the one installed."""
        while True:
            try:
                report(
                    f"Installing the {VARIANTS[key].title} runtime ({VARIANTS[key].download_size})"
                )
                self.install(key, report)
                return key
            except Exception as exc:
                fallback = FALLBACK.get(key)
                if fallback is None:
                    raise
                log.warning("%s runtime failed to install (%s); trying %s", key, exc, fallback)
                title = VARIANTS[key].title
                report(f"The {title} runtime could not be installed; using {fallback}.")
                key = fallback

    def remove(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


def self_test(report: Report = print) -> int:
    """Install a runtime and separate a short generated clip. Used by the release build."""
    import math
    import struct
    import tempfile
    import wave

    from ytktv.separation.remote import SubprocessSeparator, runtime_launcher

    bootstrap.ensure_ffmpeg()
    override = os.environ.get("YTKTV_SEPARATION_ROOT")
    runtime = Runtime(Path(override) if override else None)
    system = platform.system()
    wanted = os.environ.get("YTKTV_SEPARATION_VARIANT") or choose_variant(
        system, detect_gpu(), platform.machine()
    )
    report(f"python: {sys.version.split()[0]}  variant: {wanted}")
    installed = runtime.install_with_fallback(wanted, report)
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / "tone.wav"
        with wave.open(str(source), "wb") as clip:
            clip.setnchannels(2)
            clip.setsampwidth(2)
            clip.setframerate(44100)
            frames = bytearray()
            for i in range(44100 * 6):
                sample = int(9000 * math.sin(2 * math.pi * 220 * i / 44100))
                frames += struct.pack("<hh", sample, sample)
            clip.writeframes(bytes(frames))
        output = Path(folder) / "instrumental.flac"
        separator = SubprocessSeparator(
            runtime_launcher(runtime.python),
            "UVR-MDX-NET-Inst_HQ_3.onnx",
            Path(folder) / "models",
            Path(folder) / "work",
            directml=VARIANTS[installed].directml,
            log_path=Path(folder) / "worker.log",
        )
        try:
            report("device: " + separator.start())
            separator.separate(source, output)
            size = output.stat().st_size
        except Exception as exc:
            report(f"FAILED: {exc}")
            log_file = Path(folder) / "worker.log"
            if log_file.exists():
                report(log_file.read_text(encoding="utf-8", errors="replace")[-3000:])
            return 1
        finally:
            separator.close()
    report(f"OK: wrote {size} bytes with the {installed} runtime")
    return 0
