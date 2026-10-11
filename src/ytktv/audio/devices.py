"""Audio device discovery through sounddevice (PortAudio)."""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def _query() -> tuple[list[dict[str, Any]], int | None]:
    import sounddevice as sd

    devices = [dict(d) for d in sd.query_devices()]
    try:
        hostapi = int(sd.default.hostapi)
    except Exception:
        hostapi = None
    return devices, hostapi


def _names(channel_key: str) -> list[str]:
    try:
        devices, hostapi = _query()
    except Exception:
        log.warning("audio devices unavailable", exc_info=True)
        return []
    names: list[str] = []
    for device in devices:
        # Windows lists every device once per host API; keep the default API only.
        if hostapi is not None and device.get("hostapi") != hostapi:
            continue
        if device.get(channel_key, 0) > 0 and device["name"] not in names:
            names.append(device["name"])
    return names


def list_inputs() -> list[str]:
    return _names("max_input_channels")


def list_outputs() -> list[str]:
    return _names("max_output_channels")


def find_device(name: str | None, output: bool) -> int | None:
    """Return the device index for *name*, or None to use the system default."""
    if not name:
        return None
    key = "max_output_channels" if output else "max_input_channels"
    try:
        devices, hostapi = _query()
    except Exception:
        return None
    for index, device in enumerate(devices):
        if hostapi is not None and device.get("hostapi") != hostapi:
            continue
        if device["name"] == name and device.get(key, 0) > 0:
            return index
    return None  # unplugged: fall back to the default device


def default_sample_rate(device: int | None, output: bool) -> int:
    import sounddevice as sd

    try:
        info = sd.query_devices(device, "output" if output else "input")
        return int(info["default_samplerate"])
    except Exception:
        return 48000
