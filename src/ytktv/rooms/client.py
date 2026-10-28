"""Keeps a bound room connected to the front desk."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import websockets

from ytktv.config import SettingsStore
from ytktv.rooms import binding

log = logging.getLogger(__name__)
HEARTBEAT = 5.0
RETRY = 5.0


class RoomClient:
    """A background thread that talks to the desk while this machine is bound.

    *on_event(kind, data)* gets ``("online", bool)`` and every message the desk sends,
    for example ``("unbind", {})``.
    """

    def __init__(self, store: SettingsStore, on_event: Callable[[str, Any], None]) -> None:
        self.store = store
        self.on_event = on_event
        self.online = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="room-client", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _set_online(self, online: bool) -> None:
        if online != self.online:
            self.online = online
            self.on_event("online", online)

    def _run(self) -> None:
        while not self._stop.is_set():
            if binding.is_bound(self.store.settings):
                try:
                    asyncio.run(self._session())
                except Exception as exc:  # the desk is off, unreachable or restarting
                    log.debug("desk connection: %s", exc)
                self._set_online(False)
            self._stop.wait(RETRY)

    async def _session(self) -> None:
        settings = self.store.settings
        url = settings.desk_url.replace("http", "ws", 1) + "/ws/room"
        async with websockets.connect(url, open_timeout=5) as ws:
            await ws.send(json.dumps({"room_id": settings.room_id, "key": settings.room_key}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 5))
            if reply.get("type") == "unbind":  # the desk no longer knows this room
                self._handle(reply)
                return
            self._set_online(True)
            while not self._stop.is_set() and binding.is_bound(self.store.settings):
                self.store.settings.desk_last_seen = time.time()
                self.store.save()
                await ws.send(json.dumps({"type": "heartbeat"}))
                try:
                    message = json.loads(await asyncio.wait_for(ws.recv(), HEARTBEAT))
                except TimeoutError:
                    continue
                self._handle(message)

    def _handle(self, message: dict[str, Any]) -> None:
        kind = str(message.get("type", ""))
        if kind == "unbind":
            binding.clear(self.store.settings)
            self.store.save()
        if kind != "ack":
            self.on_event(kind, message)
