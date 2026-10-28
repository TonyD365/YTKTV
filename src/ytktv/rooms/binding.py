"""Binding a room to the front desk, and the rule for undoing it."""

from __future__ import annotations

import json
import time
import urllib.request

from ytktv.config import Settings

# A binding is permanent. Only after the desk has been unreachable this long may the
# room unbind itself, and even then someone has to press Unbind in the room's settings.
UNBIND_AFTER = 7 * 24 * 3600


def is_bound(settings: Settings) -> bool:
    return bool(settings.desk_url and settings.room_id and settings.room_key)


def can_unbind(settings: Settings, now: float | None = None) -> bool:
    if not is_bound(settings):
        return False
    now = time.time() if now is None else now
    return now - settings.desk_last_seen >= UNBIND_AFTER


def bind(settings: Settings, desk_url: str, code: str, name: str, timeout: float = 5.0) -> None:
    """Pair with the desk using the code it shows. Raises on a wrong code or no desk."""
    desk_url = desk_url.rstrip("/")
    if "://" not in desk_url:
        desk_url = f"http://{desk_url}"
    body = json.dumps({"code": code.strip(), "name": name.strip()}).encode()
    request = urllib.request.Request(
        f"{desk_url}/api/pair", body, {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        reply = json.loads(response.read())
    settings.desk_url = desk_url
    settings.room_id = reply["room_id"]
    settings.room_key = reply["key"]
    settings.room_name = reply["name"]
    settings.desk_last_seen = time.time()


def clear(settings: Settings) -> None:
    settings.desk_url = settings.room_id = settings.room_key = settings.room_name = ""
    settings.desk_last_seen = 0.0
