"""Make sure the helper programs YTKTV starts do not outlive it.

Downloads run ffmpeg, HD unlock runs Deno and vocal separation runs a worker. When
YTKTV quit while one of them was busy, it kept running on its own: a download
finishing for nobody, and "YTKTV is running in the background" in the system
settings.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger(__name__)

_job: object | None = None  # Windows: the handle must stay open for as long as we run
_spared: set[int] = set()  # processes that are meant to carry on after YTKTV quits


def _process_table() -> list[tuple[int, int, str]]:
    """(pid, parent pid, command line) of every process, on macOS and Linux."""
    try:
        listing = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,command="], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    table = []
    for line in listing.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            table.append((int(parts[0]), int(parts[1]), parts[2]))
    return table


def descendants(root: int, table: list[tuple[int, int, str]]) -> list[int]:
    """Every process started by *root*, directly or through another one."""
    found: list[int] = []
    frontier = [root]
    while frontier:
        parents, frontier = set(frontier), []
        for pid, parent, _command in table:
            if parent in parents and pid not in found and pid != root:
                found.append(pid)
                frontier.append(pid)
    return found


def orphans(table: list[tuple[int, int, str]], folders: list[str]) -> list[int]:
    """Helpers left behind by a YTKTV that is gone: nobody's children, running from *folders*."""
    return [
        pid
        for pid, parent, command in table
        if parent == 1
        and pid != os.getpid()
        and (
            any(command.startswith(folder) for folder in folders)
            or " --separation-worker" in command
        )
    ]


def _end(pids: list[int], patience: float = 1.5) -> None:
    """Ask the processes to stop, and stop them for good if they have not after a moment."""
    for pid in pids:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + patience
    remaining = list(pids)
    while remaining and time.monotonic() < deadline:
        time.sleep(0.05)
        alive = []
        for pid in remaining:
            try:
                # Collect it if it is our own child, so that it does not linger as a zombie.
                if os.waitpid(pid, os.WNOHANG)[0] == 0:
                    alive.append(pid)
            except ChildProcessError:
                with contextlib.suppress(OSError):
                    os.kill(pid, 0)  # raises once the process is gone
                    alive.append(pid)
            except OSError:
                pass
        remaining = alive
    for pid in remaining:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGKILL)


def _tie_to_this_process_windows() -> None:
    """Put this process in a job that ends everything in it when the process goes away."""
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("a", "b", "c", "d", "e", "f")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error(), "CreateJobObject failed")  # type: ignore[attr-defined]
    limits = ExtendedLimits()
    # KILL_ON_JOB_CLOSE, and BREAKAWAY_OK so launch_to_outlive can start an installer.
    limits.BasicLimitInformation.LimitFlags = 0x2000 | 0x0800
    extended_limit_information = 9
    if not kernel32.SetInformationJobObject(
        job, extended_limit_information, ctypes.byref(limits), ctypes.sizeof(limits)
    ) or not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        raise OSError(ctypes.get_last_error(), "could not set up the job")  # type: ignore[attr-defined]
    global _job
    _job = job  # closed by Windows when this process ends, which ends the helpers too


def launch_to_outlive(command: list[str]) -> None:
    """Start a program that must keep running after YTKTV quits (an installer, a restart)."""
    if sys.platform == "win32":
        detached = getattr(subprocess, "DETACHED_PROCESS", 0)
        breakaway = 0x01000000  # CREATE_BREAKAWAY_FROM_JOB: do not end with our job
        try:
            subprocess.Popen(command, creationflags=detached | breakaway)
        except OSError:
            # Refused when we are not in a job that allows it; then there is no job
            # of ours to escape from either.
            subprocess.Popen(command, creationflags=detached)
        return
    process = subprocess.Popen(command, start_new_session=True)
    _spared.add(process.pid)


def start(folders: list[Path]) -> None:
    """Call once at start-up: clear out helpers a previous YTKTV left behind.

    On Windows this also arranges for every helper started from now on to end with
    YTKTV, however YTKTV ends. macOS and Linux have nothing like that, which is why
    :func:`stop` exists and why leftovers are looked for here.
    """
    try:
        if sys.platform == "win32":
            _tie_to_this_process_windows()
            return
        left = orphans(_process_table(), [str(folder) for folder in folders])
        if left:
            log.info("stopping %d helper process(es) left by an earlier run", len(left))
            _end(left)
    except Exception:
        log.warning("could not look after helper processes", exc_info=True)


def stop() -> None:
    """Call when quitting: end every helper this process started that is still running."""
    if sys.platform == "win32":
        return  # the job set up in start() does it
    try:
        table = _process_table()
        keep = set(_spared)
        for pid in _spared:
            keep.update(descendants(pid, table))
        _end([pid for pid in descendants(os.getpid(), table) if pid not in keep])
    except Exception:
        log.warning("could not stop helper processes", exc_info=True)
