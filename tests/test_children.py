from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import textwrap
import time

import pytest

from ytktv import children

TABLE = [
    (1, 0, "/sbin/launchd"),
    (100, 1, "/Applications/YTKTV.app/Contents/MacOS/YTKTV"),
    (110, 100, "/data/YTKTV/bin/ffmpeg -i https://example.invalid/a"),
    (120, 100, "/data/YTKTV/hd/deno run server.ts"),
    (121, 120, "/data/YTKTV/hd/deno worker"),
    (200, 1, "/data/YTKTV/bin/ffmpeg -i https://example.invalid/b"),
    (210, 1, "/Applications/YTKTV.app/Contents/MacOS/YTKTV --separation-worker"),
    (300, 1, "/usr/bin/ffmpeg -i something-else"),
    (400, 1, "/Applications/Other.app/Contents/MacOS/Other"),
]


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        listing = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in listing
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    # A finished child of ours stays listed until it is collected.
    state = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return bool(state.stdout.strip()) and not state.stdout.strip().startswith("Z")


def wait_gone(pid: int, seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.1)
    return False


def test_descendants_follow_the_whole_tree():
    assert children.descendants(100, TABLE) == [110, 120, 121]
    assert children.descendants(120, TABLE) == [121]
    assert children.descendants(400, TABLE) == []


def test_orphans_are_only_our_own_helpers_with_no_parent_left(monkeypatch):
    monkeypatch.setattr(children.os, "getpid", lambda: 999)
    # The helpers of a YTKTV that is still running (110, 120, 121) are left alone, and
    # so are other people's programs (300, 400) and the app itself (100).
    assert children.orphans(TABLE, ["/data/YTKTV"]) == [200, 210]
    assert children.orphans(TABLE, []) == [210]


SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX clean-up; Windows uses a job")
def test_stop_ends_helpers_but_spares_what_was_launched_to_outlive(monkeypatch):
    helper = subprocess.Popen(SLEEPER)
    monkeypatch.setattr(children, "_spared", set())
    children.launch_to_outlive(SLEEPER)
    (spared,) = children._spared
    try:
        assert alive(helper.pid) and alive(spared)
        children.stop()
        assert wait_gone(helper.pid)
        assert alive(spared)  # an installer or a restarted YTKTV must carry on
    finally:
        for pid in (helper.pid, spared):
            with contextlib.suppress(OSError):
                os.kill(pid, 9)
        helper.wait(timeout=5)


def test_a_helper_does_not_outlive_the_program_that_started_it(tmp_path):
    """The whole point, on every platform: quit, and the helper is gone."""
    script = tmp_path / "parent.py"
    script.write_text(
        textwrap.dedent(
            """
            import subprocess, sys
            from ytktv import children

            children.start([])
            helper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
            print(helper.pid, flush=True)
            children.stop()
            """
        ),
        encoding="utf-8",
    )
    done = subprocess.run([sys.executable, str(script)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    helper = int(done.stdout.strip())
    try:
        assert wait_gone(helper), "the helper was still running after its parent quit"
    finally:
        if sys.platform != "win32":
            with contextlib.suppress(OSError):
                os.kill(helper, 9)
