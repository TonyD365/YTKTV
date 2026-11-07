"""The Windows one-line installer (site/install.ps1) parses and answers -Help."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "site" / "install.ps1"


def test_the_script_is_plain_ascii():
    SCRIPT.read_bytes().decode("ascii")


@pytest.mark.skipif(sys.platform != "win32", reason="needs Windows PowerShell")
def test_the_script_parses_and_shows_help():
    parse = (
        "$e = $null; [void][Management.Automation.Language.Parser]::ParseFile("
        f"'{SCRIPT}', [ref]$null, [ref]$e); if ($e) {{ $e; exit 1 }}"
    )
    run = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass"]
    subprocess.run([*run, "-Command", parse], check=True, timeout=60)
    shown = subprocess.run(
        [*run, "-File", str(SCRIPT), "-Help"], capture_output=True, text=True, timeout=60
    )
    assert (
        shown.returncode == 0 and "irm https://tonyd365.github.io/YTKTV/install.ps1" in shown.stdout
    )
