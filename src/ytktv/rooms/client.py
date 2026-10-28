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
from ytktv.rooms import binding, discovery
from ytktv.rooms.protocol import DeskImpostor, RoomSession

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

    def _locate(self) -> None:
        """Follow the desk to its current IP address, found by its ID."""
        settings = self.store.settings
        try:
            address = discovery.find(settings.desk_id)
        except Exception as exc:  # no multicast on this network: keep the last address
            log.debug("desk discovery: %s", exc)
            return
        if address and binding.desk_url(address) != settings.desk_url:
            settings.desk_url = binding.desk_url(address)
            self.store.save()

    async def _session(self) -> None:
        settings = self.store.settings
        if not self.online:
            await asyncio.to_thread(self._locate)
        session = RoomSession(settings.room_id, settings.room_key, settings.desk_key)
        url = settings.desk_url.replace("http", "ws", 1) + "/ws/room"
        ssl_context = binding.tls_context() if url.startswith("wss") else None
        async with websockets.connect(url, open_timeout=5, ssl=ssl_context) as ws:
            await ws.send(session.hello())
            try:
                async with asyncio.timeout(10):
                    first = session.open(str(await ws.recv()))
                    if first.get("type") == "challenge":
                        await ws.send(session.answer(first))
                        first = session.open(str(await ws.recv()))
            except DeskImpostor:
                log.warning("ignored a machine pretending to be the front desk")
                return
            if first.get("type") != "ack":
                self._handle(first)  # a signed unbind: the desk no longer knows this room
                return
            self._set_online(True)
            while not self._stop.is_set() and binding.is_bound(self.store.settings):
                self.store.settings.desk_last_seen = time.time()
                self.store.save()
                await ws.send(json.dumps({"type": "heartbeat"}))
                try:
                    async with asyncio.timeout(HEARTBEAT):
                        raw = await ws.recv()
                except TimeoutError:
                    continue
                try:
                    self._handle(session.open(str(raw)))
                except DeskImpostor:
                    log.warning("ignored a message the desk did not sign")

    def _handle(self, message: dict[str, Any]) -> None:
        kind = str(message.get("type", ""))
        if kind == "unbind":
            binding.clear(self.store.settings)
            self.store.save()
        if kind != "ack":
            self.on_event(kind, message)
