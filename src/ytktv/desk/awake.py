"""Keep a server computer awake, and start YTKTV Desk when the computer starts."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
LABEL = "com.ytktv.desk"


class KeepAwake:
    """While started, the computer does not go to sleep on its own (the screen still may)."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._windows = False

    def start(self) -> None:
        if self._process is not None or self._windows:
            return
        if sys.platform == "win32":
            import ctypes

            kernel = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
            kernel.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
            self._windows = True
            return
        if sys.platform == "darwin":
            command = ["caffeinate", "-i", "-w", str(os.getpid())]
        elif shutil.which("systemd-inhibit"):
            command = [
                "systemd-inhibit", "--what=sleep:idle", "--why=YTKTV Desk server",
                "sleep", "infinity",
            ]  # fmt: skip
        else:
            return
        with contextlib.suppress(OSError):
            self._process = subprocess.Popen(command)  # noqa: S603

    def stop(self) -> None:
        if self._windows:
            import ctypes

            kernel = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
            kernel.SetThreadExecutionState(ES_CONTINUOUS)
            self._windows = False
        if self._process is not None:
            self._process.terminate()
            self._process = None


def _command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "ytktv.desk"]


def _mac_file(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _linux_file(home: Path) -> Path:
    return home / ".config" / "autostart" / "ytktv-desk.desktop"


def start_at_login(on: bool, home: Path | None = None, platform: str = sys.platform) -> None:
    """Start YTKTV Desk when this user logs in (or stop doing so)."""
    home = home or Path.home()
    command = _command()
    if platform == "darwin":
        file = _mac_file(home)
        if not on:
            file.unlink(missing_ok=True)
            return
        arguments = "".join(f"<string>{part}</string>" for part in command)
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"'
            ' "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            f'<plist version="1.0"><dict><key>Label</key><string>{LABEL}</string>'
            f"<key>ProgramArguments</key><array>{arguments}</array>"
            "<key>RunAtLoad</key><true/></dict></plist>\n",
            encoding="utf-8",
        )
    elif platform == "win32":
        import winreg  # type: ignore[import-not-found,unused-ignore]

        key = winreg.OpenKey(  # type: ignore[attr-defined,unused-ignore]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined,unused-ignore]
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,  # type: ignore[attr-defined,unused-ignore]
        )
        with key:
            if on:
                value = subprocess.list2cmdline(command)
                winreg.SetValueEx(key, "YTKTV Desk", 0, winreg.REG_SZ, value)  # type: ignore[attr-defined,unused-ignore]
            else:
                with contextlib.suppress(FileNotFoundError):
                    winreg.DeleteValue(key, "YTKTV Desk")  # type: ignore[attr-defined,unused-ignore]
    else:
        file = _linux_file(home)
        if not on:
            file.unlink(missing_ok=True)
            return
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(
            "[Desktop Entry]\nType=Application\nName=YTKTV Desk\n"
            f"Exec={' '.join(command)}\nX-GNOME-Autostart-enabled=true\n",
            encoding="utf-8",
        )


def starts_at_login(home: Path | None = None, platform: str = sys.platform) -> bool:
    home = home or Path.home()
    if platform == "darwin":
        return _mac_file(home).exists()
    if platform == "win32":
        import winreg  # type: ignore[import-not-found,unused-ignore]

        try:
            key = winreg.OpenKey(  # type: ignore[attr-defined,unused-ignore]
                winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined,unused-ignore]
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            )
            with key:
                winreg.QueryValueEx(key, "YTKTV Desk")  # type: ignore[attr-defined,unused-ignore]
            return True
        except OSError:
            return False
    return _linux_file(home).exists()
