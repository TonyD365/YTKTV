"""Run separation in a separate Python process.

Packaged builds for Windows and Linux do not carry the heavy separation
libraries. They download a private Python environment with the right GPU
build instead and talk to a worker process running inside it.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import IO, Any

log = logging.getLogger(__name__)

PREFIX = "@@YTKTV "
WORKER_SCRIPT = Path(__file__).with_name("sep_worker.py")
WORKER_FLAG = "--separation-worker"


def runtime_launcher(python: Path | str) -> list[str]:
    """Start the worker with a separate Python environment (the downloaded runtime)."""
    return [str(python), "-u", str(WORKER_SCRIPT)]


def builtin_launcher() -> list[str]:
    """Start the worker with this app's own libraries, in a new process."""
    if getattr(sys, "frozen", False):
        return [sys.executable, WORKER_FLAG]
    return [sys.executable, "-u", "-m", "ytktv", WORKER_FLAG]


class WorkerError(RuntimeError):
    pass


class SubprocessSeparator:
    """A :class:`~ytktv.separation.base.Separator` backed by a worker process."""

    def __init__(
        self,
        launcher: list[str],
        model: str,
        model_dir: Path,
        work_dir: Path,
        directml: bool = False,
        log_path: Path | None = None,
    ) -> None:
        """*launcher* is the command that starts the worker, without its arguments."""
        self._command = [
            *launcher,
            "--model",
            model,
            "--model-dir",
            str(model_dir),
            "--work-dir",
            str(work_dir),
        ]
        if directml:
            self._command.append("--directml")
        self._log_path = log_path
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._log_file: IO[Any] | None = None
        self.device_kind = ""
        self.device_label = ""

    def _read_message(self, process: subprocess.Popen[str]) -> dict[str, Any]:
        assert process.stdout is not None
        while True:
            line = process.stdout.readline()
            if not line:
                raise WorkerError(f"separation worker exited (code {process.poll()})")
            if line.startswith(PREFIX):
                message: dict[str, Any] = json.loads(line[len(PREFIX) :])
                return message

    def _ensure_started(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        self._close_log()
        stderr: Any = subprocess.DEVNULL
        if self._log_path is not None:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_file = self._log_path.open("w", encoding="utf-8", errors="replace")
            stderr = self._log_file
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        # The worker must use its own environment, not anything from a frozen parent.
        for name in ("PYTHONHOME", "PYTHONPATH"):
            env.pop(name, None)
        process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        hello = self._read_message(process)
        self.device_kind = str(hello.get("kind", ""))
        self.device_label = str(hello.get("device", ""))
        self._process = process
        return process

    def start(self) -> str:
        """Start the worker and return a description of the device it will use."""
        with self._lock:
            self._ensure_started()
            return self.device_label

    def separate(self, source: Path, out_path: Path, pitch_path: Path | None = None) -> None:
        request = {"source": str(source), "output": str(out_path)}
        if pitch_path is not None:
            request["pitch"] = str(pitch_path)
        with self._lock:
            process = self._ensure_started()
            assert process.stdin is not None
            try:
                process.stdin.write(json.dumps(request))
                process.stdin.write("\n")
                process.stdin.flush()
                reply = self._read_message(process)
            except (OSError, WorkerError):
                self._kill()
                raise
            if not reply.get("ok"):
                raise WorkerError(str(reply.get("error", "separation failed")))

    def cancel(self) -> None:
        """Abandon the song being separated right now (it raises :class:`WorkerError`).

        Safe to call from another thread while :meth:`separate` is waiting; the
        worker is restarted for the next song.
        """
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.kill()
            except OSError:
                log.debug("could not cancel the separation worker", exc_info=True)

    def _close_log(self) -> None:
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def _kill(self) -> None:
        if self._process is not None:
            try:
                self._process.kill()
                self._process.wait(timeout=5)
            except Exception:
                log.debug("could not stop the separation worker", exc_info=True)
            self._process = None
        self._close_log()

    def close(self) -> None:
        with self._lock:
            self._kill()
