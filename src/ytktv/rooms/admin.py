"""Admin settings of a room, which the staff terminal sets once the room is bound to it.

The desk's request arrives as a signed, numbered message (see protocol.RoomSession), so it
cannot be forged or replayed; on top of that only the settings listed here are accepted,
each checked for its type and range, and anything else in the message is ignored.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from ytktv.smart_lights import KINDS as LIGHT_KINDS

QUALITIES = (720, 1080, 1440, 2160)
_HOST = re.compile(r"^[A-Za-z0-9.\-:\[\]]{1,100}$")


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ValueError("expected true or false")
    return value


def _quality(value: Any) -> int:
    if value not in QUALITIES:
        raise ValueError(f"expected one of {QUALITIES}")
    return int(value)


def _screen(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or not -1 <= value <= 15:
        raise ValueError("expected a screen number")
    return value


def _folders(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("expected up to 20 folders")
    folders = [str(f).strip() for f in value if isinstance(f, str) and f.strip()]
    if any(len(f) > 500 or "\x00" in f for f in folders):
        raise ValueError("folder path too long")
    return folders


def _lights(value: Any) -> str:
    if value not in LIGHT_KINDS:
        raise ValueError(f"expected one of {list(LIGHT_KINDS)}")
    return str(value)


def _host(value: Any) -> str:
    if not isinstance(value, str) or (value and not _HOST.match(value.strip())):
        raise ValueError("expected an address such as 192.168.1.50")
    return value.strip()


def _device(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError("expected a device name")
    return value or None


# setting -> (label for the staff terminal, check that returns the cleaned value)
FIELDS: dict[str, tuple[str, Callable[[Any], Any]]] = {
    "max_height": ("Maximum video quality", _quality),
    "mv_screen": ("Show the MV on screen", _screen),
    "mv_fullscreen": ("Full screen on that display", _bool),
    "preload_queue": ("Download the next songs ahead of time", _bool),
    "output_device": ("Sound output", _device),
    "auto_separate": ("Prepare an instrumental for every selected song", _bool),
    "wait_for_instrumental": ("Wait for the instrumental before a song starts", _bool),
    "local_folders": ("Local song folders", _folders),
    "smart_lights": ("Smart lights", _lights),
    "smart_lights_host": ("Smart lights address", _host),
    "auto_update": ("Install new releases automatically", _bool),
}


def report(settings: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """What the room tells the staff terminal: its admin settings and what it can choose from."""
    return {
        "type": "admin_report",
        "settings": {name: getattr(settings, name) for name in FIELDS},
        **(extra or {}),
    }


def apply(settings: Any, values: Any) -> list[str]:
    """Take the desk's new values; returns the names that changed. Raises ValueError on a bad one.

    Nothing changes unless every value is valid.
    """
    if not isinstance(values, dict):
        raise ValueError("expected settings")
    cleaned = {}
    for name, value in values.items():
        if name not in FIELDS:
            continue  # not something the desk may set
        try:
            cleaned[name] = FIELDS[name][1](value)
        except ValueError as exc:
            raise ValueError(f"{name}: {exc}") from exc
    changed = [n for n, v in cleaned.items() if getattr(settings, n) != v]
    for name in changed:
        setattr(settings, name, cleaned[name])
    return changed
