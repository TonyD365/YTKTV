"""YTKTV - turn any computer into a karaoke machine powered by YouTube."""

from __future__ import annotations

APP_NAME = "YTKTV"
GITHUB_REPO = "TonyD365/YTKTV"


def _detect_version() -> str:
    try:
        from ytktv._version import __version__ as generated

        return str(generated)
    except ImportError:
        pass
    try:
        from importlib.metadata import version

        return version("ytktv")
    except Exception:
        return "0.0.0"


__version__ = _detect_version()
