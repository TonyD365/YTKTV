"""Room lights that follow the music: WLED strips and Philips Hue, over the home network.

They take the same colour and brightness as the TV's edge lights (the "glow" event), sent
from a background thread at a pace each kind of light can keep up with.
"""

from __future__ import annotations

import colorsys
import json
import logging
import threading
import time
import urllib.request
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

KINDS = {"off": "Off", "wled": "WLED", "hue": "Philips Hue"}
# Seconds between updates: WLED keeps up easily; a Hue bridge allows about one group
# command a second.
PACE = {"wled": 0.3, "hue": 1.0}
TIMEOUT = 2.0


def request(method: str, url: str, body: Any = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(url, data, {"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310 - LAN only
        raw = response.read()
    return json.loads(raw) if raw else None


def wled_state(level: float, hue: float) -> dict[str, Any]:
    r, g, b = colorsys.hsv_to_rgb(hue % 1.0, 0.9, 1.0)
    return {
        "on": True,
        "bri": max(8, round(level * 255)),
        "tt": 2,  # a 0.2 s fade between colours
        "seg": [{"col": [[round(r * 255), round(g * 255), round(b * 255)]]}],
    }


def hue_action(level: float, hue: float) -> dict[str, Any]:
    return {
        "on": True,
        "hue": round((hue % 1.0) * 65535),
        "sat": 254,
        "bri": max(1, round(level * 254)),
        "transitiontime": 5,  # tenths of a second
    }


def pair_hue(host: str, request: Callable[..., Any] = request) -> str:
    """Ask the Hue bridge for a key. Press its round link button first.

    Raises RuntimeError with the bridge's message when the button was not pressed.
    """
    reply = request("POST", f"http://{host}/api", {"devicetype": "ytktv#karaoke"})
    entry = reply[0] if isinstance(reply, list) and reply else {}
    if "success" in entry:
        return str(entry["success"]["username"])
    error = entry.get("error", {}).get("description", "no answer")
    raise RuntimeError(f"The Hue bridge said: {error}")


class SmartLights:
    """Sends the latest glow colour to the configured lights, never more often than PACE."""

    def __init__(self, settings: Any, request: Callable[..., Any] = request) -> None:
        self.settings = settings
        self.request = request
        self._latest: tuple[float, float] | None = None
        self._sent: tuple[float, float] | None = None
        self._wake = threading.Event()
        self._stop = False
        self._thread: threading.Thread | None = None
        self.last_error = ""

    def on_event(self, topic: str, payload: Any) -> None:
        """Subscribe this to the controller's bus."""
        if topic == "glow" and isinstance(payload, dict):
            self._latest = (float(payload.get("level", 0)), float(payload.get("hue", 0)))
            self._wake.set()

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="ytktv-lights", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop = True
        self._wake.set()

    def send(self, level: float, hue: float) -> None:
        """Set the lights once (also used by the Test button). Raises on network errors."""
        kind = self.settings.smart_lights
        host = self.settings.smart_lights_host.strip()
        if kind == "wled" and host:
            self.request("POST", f"http://{host}/json/state", wled_state(level, hue))
        elif kind == "hue" and host and self.settings.hue_key:
            url = f"http://{host}/api/{self.settings.hue_key}/groups/0/action"
            self.request("PUT", url, hue_action(level, hue))

    def _run(self) -> None:
        while not self._stop:
            self._wake.wait()
            self._wake.clear()
            if self._stop:
                return
            kind = self.settings.smart_lights
            latest = self._latest
            if kind not in PACE or latest is None or latest == self._sent:
                continue
            try:
                self.send(*latest)
                self._sent, self.last_error = latest, ""
            except Exception as exc:  # a light that is off or unplugged must not stop the music
                if str(exc) != self.last_error:
                    log.info("smart lights: %s", exc)
                self.last_error = str(exc)
            time.sleep(PACE[kind])
