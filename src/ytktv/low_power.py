"""Low-power mode for a Raspberry Pi or an old computer: 720p video and no light effects."""

from __future__ import annotations

import os
import platform
from typing import Any

MAX_HEIGHT = 720


def weak_computer(machine: str | None = None, cores: int | None = None) -> bool:
    """An ARM Linux board (a Raspberry Pi) or a computer with four cores or fewer."""
    machine = (machine or platform.machine()).lower()
    cores = cores if cores is not None else (os.cpu_count() or 1)
    arm_linux = platform.system() == "Linux" and machine in ("aarch64", "arm64", "armv7l")
    return arm_linux or cores <= 4


def apply(settings: Any, on: bool) -> None:
    settings.low_power = on
    if on:
        settings.max_height = min(settings.max_height, MAX_HEIGHT)
        settings.lights = False


def first_start(settings: Any, weak: bool | None = None) -> bool:
    """Turn it on once, on the first start of a weak computer; True when it did."""
    if settings.low_power_checked:
        return False
    settings.low_power_checked = True
    if weak if weak is not None else weak_computer():
        apply(settings, True)
        return True
    return False
