"""Stops anyone guessing pairing codes: a six-digit code would fall to enough tries."""

from __future__ import annotations

import threading
import time

PER_ADDRESS = 5  # wrong codes from one address before it has to wait
LOCKOUT = 300.0  # seconds that address waits
IN_TOTAL = 20  # wrong codes from anywhere before every open code is thrown away


class PairingGuard:
    def __init__(self, on_flood: object = None) -> None:
        self._lock = threading.Lock()
        self._misses: dict[str, list[float]] = {}
        self._total = 0
        self.on_flood = on_flood  # called when the codes should be thrown away

    def allowed(self, address: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            recent = [t for t in self._misses.get(address, []) if now - t < LOCKOUT]
            self._misses[address] = recent
            return len(recent) < PER_ADDRESS

    def missed(self, address: str, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        with self._lock:
            self._misses.setdefault(address, []).append(now)
            self._total += 1
            flood = self._total >= IN_TOTAL
            if flood:
                self._total = 0
        if flood and callable(self.on_flood):
            self.on_flood()

    def succeeded(self) -> None:
        with self._lock:
            self._total = 0
