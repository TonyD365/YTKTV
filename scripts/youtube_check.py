"""Can YTKTV still find and play songs on YouTube? Run every night by youtube-check.yml.

Does what a room does when someone picks a song, with the yt-dlp YTKTV installs: search,
suggestions, look up a video, get its stream, and download the first second of it.
Exits 1 with a short report when a step fails.
"""

from __future__ import annotations

import ssl
import sys
import time
from urllib.request import Request, urlopen

from ytktv.youtube.search import YouTube

QUERY = "karaoke instrumental"


def main() -> int:
    youtube = YouTube()
    failures: list[str] = []
    blocked = False  # YouTube's "confirm you're not a bot" for this machine's address

    def step(name: str, run):  # type: ignore[no-untyped-def]
        started = time.monotonic()
        try:
            result = run()
        except Exception as error:  # noqa: BLE001 - report every kind of failure
            nonlocal blocked
            blocked = blocked or "not a bot" in str(error)
            failures.append(f"{name}: {type(error).__name__}: {error}")
            print(f"FAIL {name}: {error}")
            return None
        print(f"ok   {name} ({time.monotonic() - started:.1f} s)")
        return result

    import yt_dlp

    print(f"yt-dlp {yt_dlp.version.__version__}")
    songs = step("search", lambda: youtube.search(QUERY) or _fail("no results"))
    step("suggestions", lambda: youtube.suggest("karaoke") or _fail("no suggestions"))
    if songs:
        video_id = songs[0].video_id
        print(f"     using {video_id}: {songs[0].title}")
        step("look up", lambda: youtube.lookup(video_id) or _fail("not found"))
        source = step("stream", lambda: youtube.resolve(video_id, max_height=720))
        if source is not None:
            url = source.audio_url or source.video_url
            step("download", lambda: _first_bytes(url, source.headers))

    if failures:
        # Search worked but YouTube wants a sign-in from this (cloud) address: it blocks
        # data centres like GitHub's at times, not home or venue connections. Not a YTKTV
        # problem, so it is reported as "blocked" (exit 2), not as a failure.
        playing = ("look up", "stream", "download")
        if blocked and all(f.startswith(playing) for f in failures):
            print("\n".join(["", "YouTube asked this machine to sign in (bot check):", *failures]))
            return 2
        print("\n".join(["", "YouTube check failed:", *failures]))
        return 1
    print("\nYouTube works.")
    return 0


def _fail(message: str):  # type: ignore[no-untyped-def]
    raise RuntimeError(message)


def _first_bytes(url: str, headers: dict[str, str], size: int = 256 * 1024) -> int:
    request = Request(url, headers={**headers, "Range": f"bytes=0-{size - 1}"})
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    with urlopen(request, timeout=30, context=context) as response:
        data = response.read(size)
    if len(data) < 16 * 1024:
        raise RuntimeError(f"only {len(data)} bytes came back")
    return len(data)


if __name__ == "__main__":
    sys.exit(main())
