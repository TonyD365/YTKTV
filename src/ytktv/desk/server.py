"""The desk's server: rooms pair with it and stay connected over a WebSocket.

Every connection is authenticated both ways without the room's key ever being sent:
the desk signs the room's challenge with its private key, and the room answers the
desk's challenge with an HMAC of its key. Everything the desk sends after that is
signed too, so a machine pretending to be the desk cannot unbind or control a room.
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ytktv.desk.store import DeskStore
from ytktv.rooms import crypto

DESK_PORT = 8770


class PairIn(BaseModel):
    code: str
    name: str = ""


class Channel:
    """One room's authenticated connection; messages are signed and numbered."""

    def __init__(self, ws: WebSocket, store: DeskStore, room_nonce: str) -> None:
        self.ws, self.store, self.room_nonce, self.seq = ws, store, room_nonce, 0

    async def send(self, message: dict[str, Any]) -> None:
        self.seq += 1
        body = json.dumps({**message, "seq": self.seq}, sort_keys=True)
        signature = self.store.sign(f"{self.room_nonce}|{body}".encode())
        await self.ws.send_text(json.dumps({"body": body, "sig": signature}))


class Hub:
    """The rooms connected right now, so the desk can push messages to them."""

    def __init__(self) -> None:
        self.channels: dict[str, Channel] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def online(self) -> set[str]:
        return set(self.channels)

    async def send(self, room_id: str, message: dict[str, Any]) -> bool:
        channel = self.channels.get(room_id)
        if channel is None:
            return False
        await channel.send(message)
        return True

    def send_soon(self, room_id: str, message: dict[str, Any]) -> None:
        """Push from another thread (the desk's UI)."""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self.send(room_id, message), self.loop)


def create_desk_app(store: DeskStore, hub: Hub | None = None, cert_hash: str = "") -> FastAPI:
    """The Desk's server. *cert_hash* is its TLS certificate's, which staff terminals check."""
    from ytktv.desk.staff import add_staff_routes

    hub = hub or Hub()
    app = FastAPI(title="YTKTV Desk")
    app.state.hub = hub
    add_staff_routes(app, store, hub, cert_hash)

    @app.get("/api/desk")
    def desk() -> dict[str, str]:
        return {"desk_id": store.desk_id, "desk_key": store.public_key}

    @app.post("/api/pair")
    def pair(body: PairIn) -> dict[str, str]:
        try:
            room, key = store.pair(body.code.strip(), body.name.strip())
        except KeyError as exc:
            raise HTTPException(403, "wrong or expired code") from exc
        return {
            "room_id": room.room_id,
            "key": key,
            "name": room.name,
            "desk_id": store.desk_id,
            "desk_key": store.public_key,
        }

    @app.websocket("/ws/room")
    async def room_socket(ws: WebSocket) -> None:
        # The room may go away, or give up on a desk it does not trust, at any point.
        with contextlib.suppress(WebSocketDisconnect):
            await _room_socket(ws)

    async def _room_socket(ws: WebSocket) -> None:
        await ws.accept()
        hub.loop = asyncio.get_running_loop()
        hello = json.loads(await ws.receive_text())
        room_id, room_nonce = str(hello.get("room_id", "")), str(hello.get("nonce", ""))
        channel = Channel(ws, store, room_nonce)
        key = store.key(room_id)
        if key is None or len(room_nonce) < 16:
            await channel.send({"type": "unbind"})  # signed, so the room can trust it
            await ws.close()
            return
        desk_nonce = crypto.nonce()
        await channel.send({"type": "challenge", "nonce": desk_nonce})
        answer = json.loads(await ws.receive_text())
        expected = crypto.mac(key, f"room|{room_id}|{desk_nonce}".encode())
        if not hmac.compare_digest(str(answer.get("mac", "")), expected):
            await ws.close(code=4401)
            return
        hub.channels[room_id] = channel
        store.seen(room_id)
        await channel.send({"type": "ack"})
        room = store.room(room_id)
        if room is not None:  # a room that restarted learns whether it is open
            await channel.send(room.message())
        await channel.send(products_message(store))
        try:
            while True:
                message = json.loads(await ws.receive_text())
                store.seen(room_id)
                if isinstance(message, dict):
                    receive(store, room_id, message)
        except WebSocketDisconnect:
            pass
        finally:
            if hub.channels.get(room_id) is channel:
                del hub.channels[room_id]

    return app


def receive(store: DeskStore, room_id: str, message: dict[str, Any]) -> None:
    """A service call or an order from a room. Rooms only order while they are open."""
    kind = message.get("type")
    room = store.room(room_id)
    if room is None or not room.is_open:
        return
    if kind == "heartbeat":
        store.note_song(room_id, str(message.get("song", "")))
    elif kind == "call":
        store.add_call(room_id, str(message.get("kind", "Other")), str(message.get("note", "")))
    elif kind == "order":
        items = message.get("items")
        if isinstance(items, list):
            pairs = [
                (int(i["product_id"]), int(i["qty"]))
                for i in items
                if isinstance(i, dict)
                and str(i.get("product_id", "")).isdigit()
                and str(i.get("qty", "")).isdigit()
            ]
            if store.add_order(room_id, pairs):
                store.add_call(
                    room_id,
                    "Order",
                    ", ".join(
                        f"{p.name} × {q}"
                        for p in store.products(True)
                        for pid, q in pairs
                        if p.product_id == pid
                    ),
                )


def products_message(store: DeskStore) -> dict[str, Any]:
    return {
        "type": "products",
        "currency": store.setting("currency", "$"),
        "items": [
            {"product_id": p.product_id, "name": p.name, "category": p.category, "price": p.price}
            for p in store.products(active_only=True)
        ],
    }


def tell_all_products(store: DeskStore, hub: Hub) -> None:
    for room_id in hub.online():
        hub.send_soon(room_id, products_message(store))


def tell(store: DeskStore, hub: Hub, room_id: str) -> None:
    """Send a room its current open/closed state after the desk changed it."""
    room = store.room(room_id)
    if room is not None:
        hub.send_soon(room_id, room.message())


def unbind(store: DeskStore, hub: Hub, room_id: str) -> None:
    """Forget a room; if it is connected it turns back into a stand-alone machine now."""
    hub.send_soon(room_id, {"type": "unbind"})
    store.remove(room_id)
