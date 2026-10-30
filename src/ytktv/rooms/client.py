"""Keeps a bound room connected to the staff terminal."""

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
from ytktv.rooms.state import RoomState

log = logging.getLogger(__name__)
HEARTBEAT = 5.0
POLL = 0.5  # how quickly calls and orders go out
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
        # A bound room stays closed until the desk opens it; a stand-alone one never closes.
        self.state = RoomState(closed=binding.is_bound(store.settings))
        self.products: list[dict[str, Any]] = []
        self.currency = "$"
        # Calls and orders wait here until the desk is reachable.
        self._outbox: list[dict[str, Any]] = []
        self._outbox_lock = threading.Lock()
        self.now_singing: Callable[[], str] = lambda: ""  # set by the console
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.admin_report: Callable[[], dict[str, Any]] | None = None
        self._reported: dict[str, Any] | None = None

    def call(self, kind: str, note: str = "") -> bool:
        """Ask for the staff. False when this room is not open."""
        return self._post({"type": "call", "kind": kind[:40], "note": note[:200]})

    def order(self, items: list[tuple[int, int]]) -> bool:
        wanted = [{"product_id": p, "qty": q} for p, q in items if q > 0]
        return bool(wanted) and self._post({"type": "order", "items": wanted})

    def _post(self, message: dict[str, Any]) -> bool:
        if self.state.closed or not binding.is_bound(self.store.settings):
            return False
        with self._outbox_lock:
            self._outbox.append(message)
        return True

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
                log.warning("ignored a machine pretending to be the staff terminal")
                return
            if first.get("type") != "ack":
                self._handle(first)  # a signed unbind: the desk no longer knows this room
                return
            self._set_online(True)
            while not self._stop.is_set() and binding.is_bound(self.store.settings):
                now = time.time()
                if now - self.store.settings.desk_last_seen >= HEARTBEAT:
                    self.store.settings.desk_last_seen = now
                    self.store.save()
                    await ws.send(json.dumps({"type": "heartbeat", "song": self.now_singing()}))
                    report = self.admin_report() if self.admin_report else None
                    if report is not None and report != self._reported:
                        # The staff terminal's Admin Settings show what this room has now.
                        await ws.send(json.dumps(report))
                        self._reported = report
                with self._outbox_lock:
                    outbox, self._outbox = self._outbox, []
                for message in outbox:
                    await ws.send(json.dumps(message))
                try:
                    async with asyncio.timeout(POLL):
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
            self.state = RoomState(closed=False)
        if kind == "local_folders":
            # The staff terminal decides which folders this room sings from.
            folders = [str(f) for f in message.get("folders", []) if str(f).strip()]
            self.store.settings.local_folders = folders
            self.store.save()
        if kind == "products":
            self.products = [i for i in message.get("items", []) if isinstance(i, dict)]
            self.currency = str(message.get("currency", "$"))
        self.state.apply(message)
        if kind != "ack":
            self.on_event(kind, message)
