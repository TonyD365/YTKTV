from __future__ import annotations

import json
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from ytktv.separation import runtime
from ytktv.separation.remote import SubprocessSeparator, WorkerError
from ytktv.separation.runtime import Gpu, Runtime, choose_variant, detect_gpu


def fake_run(answers: dict[str, tuple[int, str]]):
    """A stand-in for subprocess.run keyed by the program name."""

    def run(command, **_kwargs):
        if command[0] not in answers:
            raise FileNotFoundError(command[0])
        code, out = answers[command[0]]
        return subprocess.CompletedProcess(command, code, stdout=out, stderr="")

    return run


def test_nvidia_with_driver_is_detected_on_any_system():
    run = fake_run({"nvidia-smi": (0, "NVIDIA GeForce RTX 4070\nNVIDIA GeForce RTX 3060\n")})
    for system in ("Windows", "Linux"):
        gpu = detect_gpu(system, run)
        assert gpu == Gpu("nvidia", "NVIDIA GeForce RTX 4070", cuda=True)
        assert choose_variant(system, gpu) == "cuda"


@pytest.mark.parametrize(
    ("controllers", "vendor", "variant"),
    [
        ("Intel(R) UHD Graphics 770\nAMD Radeon RX 7800 XT\n", "amd", "directml"),
        ("Intel(R) Arc(TM) A770 Graphics\n", "intel", "directml"),
        # NVIDIA hardware whose driver is missing cannot run CUDA.
        ("NVIDIA GeForce GTX 1060\n", "nvidia", "directml"),
        ("Microsoft Basic Display Adapter\n", None, "cpu"),
        ("", None, "cpu"),
    ],
)
def test_windows_without_nvidia_driver(controllers, vendor, variant):
    gpu = detect_gpu("Windows", fake_run({"powershell": (0, controllers)}))
    assert (gpu.vendor if gpu else None) == vendor
    assert gpu is None or not gpu.cuda
    assert choose_variant("Windows", gpu) == variant


def test_linux_without_nvidia_uses_cpu():
    assert detect_gpu("Linux", fake_run({})) is None
    assert detect_gpu("Linux", fake_run({"nvidia-smi": (9, "NVIDIA-SMI has failed")})) is None
    assert choose_variant("Linux", Gpu("amd", "Radeon")) == "cpu"
    assert choose_variant("Linux", None) == "cpu"


def test_supported_only_for_packaged_windows_and_linux(monkeypatch):
    monkeypatch.delenv("YTKTV_SEPARATION_RUNTIME", raising=False)
    assert runtime.supported("Windows", frozen=True, machine="AMD64")
    assert runtime.supported("Linux", frozen=True)
    assert not runtime.supported("Darwin", frozen=True)
    assert not runtime.supported("Windows", frozen=False)
    monkeypatch.setenv("YTKTV_SEPARATION_RUNTIME", "1")
    assert runtime.supported("Darwin", frozen=False)


def test_install_commands_pick_the_right_torch_build(tmp_path):
    rt = Runtime(tmp_path, system="Linux")
    (_, venv), (_, install) = rt.install_commands(runtime.VARIANTS["cuda"], "uv")
    assert venv[-4:] == [str(rt.env_dir), "--python", "3.12", "--managed-python"]
    assert "audio-separator[gpu]" in install and install[-2:] == ["--torch-backend", "auto"]
    assert str(rt.python) in install and rt.python.name == "python"

    _, (_, cpu) = rt.install_commands(runtime.VARIANTS["cpu"], "uv")
    assert "audio-separator[cpu]" in cpu and cpu[-2:] == ["--torch-backend", "cpu"]

    windows = Runtime(tmp_path, system="Windows")
    _, (_, dml) = windows.install_commands(runtime.VARIANTS["directml"], "uv")
    assert "audio-separator[dml]" in dml and "--torch-backend" not in dml
    assert windows.python.name == "python.exe"


def test_install_writes_marker_and_failure_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, "find_uv", lambda: "uv")
    rt = Runtime(tmp_path / "rt", system="Linux")
    assert rt.installed_variant() is None

    def succeed(command, **kwargs):
        assert kwargs["env"]["UV_PYTHON_INSTALL_DIR"].startswith(str(rt.root))
        if "venv" in command:
            rt.python.parent.mkdir(parents=True)
            rt.python.write_text("")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    lines: list[str] = []
    rt.install("cpu", lines.append, run=succeed)
    assert rt.installed_variant() == "cpu"
    assert json.loads((rt.root / runtime.MARKER).read_text())["variant"] == "cpu"
    assert lines and not (rt.root / "cache").exists()

    def fail(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, stdout="", stderr="no matching wheel")

    with pytest.raises(RuntimeError, match="no matching wheel"):
        rt.install("cuda", run=fail)
    assert rt.installed_variant() is None and not rt.root.exists()


def test_install_falls_back_to_cpu(tmp_path, monkeypatch):
    rt = Runtime(tmp_path / "rt", system="Windows")
    attempts: list[str] = []

    def install(key, report=None, run=None):
        attempts.append(key)
        if key != "cpu":
            raise RuntimeError("gpu build unavailable")

    monkeypatch.setattr(rt, "install", install)
    assert rt.install_with_fallback("directml") == "cpu"
    assert attempts == ["directml", "cpu"]

    monkeypatch.setattr(rt, "install", lambda key, report=None: (_ for _ in ()).throw(OSError("x")))
    with pytest.raises(OSError):
        rt.install_with_fallback("cpu")


def test_stale_marker_is_ignored(tmp_path):
    rt = Runtime(tmp_path, system="Linux")
    rt.python.parent.mkdir(parents=True)
    rt.python.write_text("")
    (tmp_path / runtime.MARKER).write_text(json.dumps({"variant": "cuda", "revision": -1}))
    assert rt.installed_variant() is None
    marker = {"variant": "cuda", "revision": runtime.RUNTIME_REVISION}
    (tmp_path / runtime.MARKER).write_text(json.dumps(marker))
    assert rt.installed_variant() == "cuda"
    rt.python.unlink()
    assert rt.installed_variant() is None  # the environment itself is gone


FAKE_WORKER = textwrap.dedent(
    """
    import json, os, shutil, sys
    print("library noise that is not part of the protocol", flush=True)
    def send(message):
        print('@@YTKTV ' + json.dumps(message), flush=True)
    send({"event": "ready", "kind": "cpu", "device": "CPU (fake)"})
    for line in sys.stdin:
        request = json.loads(line)
        name = os.path.basename(request["source"])
        if name.startswith("crash"):
            sys.exit(3)
        if name.startswith("bad"):
            send({"ok": False, "error": "ValueError: bad audio"})
            continue
        shutil.copyfile(request["source"], request["output"])
        print("more noise", flush=True)
        send({"ok": True})
    """
)


@pytest.fixture
def separator(tmp_path):
    script = tmp_path / "fake_worker.py"
    script.write_text(FAKE_WORKER)
    sep = SubprocessSeparator(
        [sys.executable, "-u", str(script)],
        "model.onnx",
        tmp_path / "models",
        tmp_path / "work",
        log_path=tmp_path / "worker.log",
    )
    yield sep
    sep.close()


def test_worker_round_trip_and_device_report(separator, tmp_path):
    source = tmp_path / "song.wav"
    source.write_bytes(b"audio" * 100)
    assert separator.start() == "CPU (fake)"
    assert separator.device_kind == "cpu"
    for index in range(2):  # the same process serves several songs
        out = tmp_path / f"out{index}.flac"
        separator.separate(source, out)
        assert out.read_bytes() == source.read_bytes()


def test_worker_error_is_reported_and_worker_survives(separator, tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_bytes(b"x")
    with pytest.raises(WorkerError, match="bad audio"):
        separator.separate(bad, tmp_path / "out.flac")
    good = tmp_path / "good.wav"
    good.write_bytes(b"y")
    separator.separate(good, tmp_path / "good.flac")
    assert (tmp_path / "good.flac").exists()


def test_worker_crash_raises_and_restarts_next_time(separator, tmp_path):
    crash = tmp_path / "crash.wav"
    crash.write_bytes(b"x")
    with pytest.raises(WorkerError, match="exited"):
        separator.separate(crash, tmp_path / "out.flac")
    good = tmp_path / "good.wav"
    good.write_bytes(b"y")
    separator.separate(good, tmp_path / "good.flac")
    assert (tmp_path / "good.flac").exists()


def test_attach_stems_enables_separation_after_startup(tmp_path):
    from tests.helpers import make_controller, make_song, wait_for
    from tests.test_controller import FakeStems
    from ytktv.core.models import PlayStatus

    controller, _, _ = make_controller(tmp_path)
    try:
        controller.enqueue(make_song(1))
        controller.enqueue(make_song(2))
        wait_for(lambda: controller.status == PlayStatus.PLAYING)
        assert controller.state()["separation"] is False
        stems = FakeStems(tmp_path)
        controller.attach_stems(stems)
        assert controller.state()["separation"] is True
        assert stems.requested == [make_song(1).video_id, make_song(2).video_id]
        assert stems.on_change is not None and stems.order is not None
    finally:
        controller.close()


def test_worker_script_is_standalone():
    """It runs inside the downloaded environment, where the ytktv package does not exist."""
    folder = Path(runtime.__file__).parent
    worker = folder.joinpath("sep_worker.py").read_text()
    # Its one ytktv import has a plain-script fallback right next to it.
    assert worker.count("from ytktv") == 1 and "import pitch_core" in worker
    assert "import ytktv" not in worker
    core = folder.joinpath("pitch_core.py").read_text()
    assert "import ytktv" not in core and "from ytktv" not in core


def test_builtin_launcher_starts_the_app_in_worker_mode(monkeypatch):
    from ytktv.separation import remote

    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert remote.builtin_launcher() == [sys.executable, "-u", "-m", "ytktv", "--separation-worker"]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert remote.builtin_launcher() == [sys.executable, "--separation-worker"]
    assert remote.runtime_launcher("/env/python")[0] == "/env/python"


SLOW_WORKER = textwrap.dedent(
    """
    import json, os, shutil, sys, time
    def send(message):
        print('@@YTKTV ' + json.dumps(message), flush=True)
    send({"event": "ready", "kind": "cpu", "device": "CPU"})
    for line in sys.stdin:
        request = json.loads(line)
        if os.path.basename(request["source"]).startswith("slow"):
            time.sleep(30)
        shutil.copyfile(request["source"], request["output"])
        send({"ok": True})
    """
)


def test_cancel_aborts_the_running_song_and_the_worker_recovers(tmp_path):
    script = tmp_path / "slow_worker.py"
    script.write_text(SLOW_WORKER)
    launcher = [sys.executable, "-u", str(script)]
    separator = SubprocessSeparator(launcher, "m", tmp_path / "models", tmp_path / "work")
    slow = tmp_path / "slow.wav"
    slow.write_bytes(b"x")
    quick = tmp_path / "quick.wav"
    quick.write_bytes(b"y")
    try:
        separator.start()
        threading.Timer(0.5, separator.cancel).start()
        began = time.monotonic()
        with pytest.raises(WorkerError):
            separator.separate(slow, tmp_path / "slow.flac")
        assert time.monotonic() - began < 10  # did not wait out the 30 s job
        separator.separate(quick, tmp_path / "quick.flac")
        assert (tmp_path / "quick.flac").read_bytes() == b"y"
    finally:
        separator.close()
