"""Effect presets for the microphone channels, and the limits of each strip control."""

from __future__ import annotations

from typing import Any

# What a preset covers: the sound of the voice. Level, pan, mute and device stay as set.
PRESET_FIELDS = ("low_db", "mid_db", "high_db", "reverb", "echo")
PRESET_NAME_LENGTH = 30

BUILT_IN: dict[str, dict[str, float]] = {
    "Pop": {"low_db": 0.0, "mid_db": 1.0, "high_db": 2.0, "reverb": 0.25, "echo": 0.15},
    "Ballad": {"low_db": 1.0, "mid_db": 0.0, "high_db": 2.0, "reverb": 0.45, "echo": 0.25},
    "Rock": {"low_db": 2.0, "mid_db": 3.0, "high_db": 1.0, "reverb": 0.15, "echo": 0.08},
    "KTV Hall": {"low_db": 2.0, "mid_db": 0.0, "high_db": 3.0, "reverb": 0.6, "echo": 0.4},
    "Dry": {"low_db": 0.0, "mid_db": 0.0, "high_db": 0.0, "reverb": 0.0, "echo": 0.0},
}

# (minimum, maximum) for every strip value that can be set remotely.
LIMITS: dict[str, tuple[float, float]] = {
    "gain": (0.0, 2.0),
    "low_db": (-12.0, 12.0),
    "mid_db": (-12.0, 12.0),
    "high_db": (-12.0, 12.0),
    "reverb": (0.0, 1.0),
    "echo": (0.0, 1.0),
    "comp": (0.0, 1.0),
    "pan": (-1.0, 1.0),
    "fader": (0.0, 1.0),
}


def clean_name(name: str) -> str:
    cleaned = " ".join(str(name).replace("/", " ").split())[:PRESET_NAME_LENGTH]
    if not cleaned:
        raise ValueError("a preset needs a name")
    return cleaned


def clamp(field: str, value: Any) -> float | bool:
    """Coerce a strip value into its legal range. Raises KeyError for unknown fields."""
    if field == "mute":
        return bool(value)
    low, high = LIMITS[field]
    return max(low, min(high, float(value)))


def values_of(strip: Any) -> dict[str, float]:
    """The preset-relevant values of a strip, rounded so comparisons are stable."""
    return {field: round(float(getattr(strip, field)), 3) for field in PRESET_FIELDS}
