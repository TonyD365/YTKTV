"""The desk's server: rooms pair with it and stay connected over a WebSocket.

Every connection is authenticated both ways without the room's key ever being sent:
the desk signs the room's challenge with its private key, and the room answers the
desk's challenge with an HMAC of its key. Everything the desk sends after that is
signed too, so a machine pretending to be the desk cannot unbind or control a room.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from lanpair import EnvelopeError, PublicIdentity, Sealer
from pydantic import BaseModel

from ytktv.desk.guard import PairingGuard
from ytktv.desk.metrics import Metrics
from ytktv.desk.store import DeskStore, Room
from ytktv.rooms import secure

log = logging.getLogger(__name__)
DESK_PORT = 8770


class PairIn(BaseModel):
    code: str
    name: str = ""
    identity: str = ""  # the room's public lanpair identity (hex)


class Channel:
    """One room's connection; every message is a lanpair envelope sealed to that room."""

    def __init__(
        self, ws: WebSocket, sealer: Sealer, room: PublicIdentity, room_id: str = ""
    ) -> None:
        self.ws, self.sealer, self.room, self.room_id = ws, sealer, room, room_id
        self.session: bytes | None = None  # the room's key for this connection

    async def send(self, message: dict[str, Any]) -> None:
        # Naming the room in the sealed body keeps a message for one room (an unbind for an
        # id the desk does not know) from being passed on to another.
        body = {**message, "room": self.room_id}
        await self.ws.send_bytes(self.sealer.seal(self.room, body, box_key=self.session))


class Hub:
    """The rooms connected right now, so the desk can push messages to them."""

    def __init__(self) -> None:
        self.channels: dict[str, Channel] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def online(self) -> set[str]:
        return set(self.channels)

    def report(self, room_id: str) -> dict[str, Any] | None:
        """The room's admin settings as it last reported them, while it is connected."""
        return self.reports.get(room_id) if room_id in self.channels else None

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


def create_desk_app(
    store: DeskStore,
    hub: Hub | None = None,
    cert_hash: str = "",
    metrics: Metrics | None = None,
    processor: Any = None,
) -> FastAPI:
    """The Desk's server. *cert_hash* is its TLS certificate's, which staff terminals check.
    *metrics*, when given, counts requests and room connections for the server console."""
    from ytktv.desk.staff import add_staff_routes

    hub = hub or Hub()
    guard = PairingGuard(store.forget_codes)
    sealer = Sealer(store.identity)
    opener = secure.opener(store.identity, store.seq_file)
    app = FastAPI(title="YTKTV Desk")
    app.state.guard = guard
    app.state.hub = hub
    app.state.metrics = metrics

    if metrics is not None:

        @app.middleware("http")
        async def count(request: Request, call_next: Any) -> Any:
            try:
                response = await call_next(request)
            except Exception as exc:
                metrics.request(500)
                metrics.event("error", f"{request.url.path}: {type(exc).__name__}")
                raise
            metrics.request(response.status_code)
            if response.status_code >= 500:
                metrics.event("error", f"{request.url.path}: HTTP {response.status_code}")
            return response

    add_staff_routes(app, store, hub, cert_hash, guard)
    from ytktv.desk.processing import add_processing_routes

    # Songs separated (and lyrics written) here for the rooms, when that is switched on.
    app.state.processor = processor
    add_processing_routes(app, store, lambda: app.state.processor)

    @app.get("/api/desk")
    def desk() -> dict[str, str]:
        return {
            "desk_id": store.desk_id,
            "desk_key": store.public_key,
            "desk_identity": store.identity_hex,
        }

    @app.post("/api/pair")
    def pair(body: PairIn, request: Request) -> dict[str, str]:
        address = request.client.host if request.client else "?"
        if not guard.allowed(address):
            raise HTTPException(429, "too many wrong codes; wait five minutes")
        if not secure.valid_public(body.identity.strip()):
            raise HTTPException(426, "update this room's YTKTV to pair with this Desk")
        try:
            room, _identity = store.pair(
                body.code.strip(), body.name.strip(), identity=body.identity.strip()
            )
            guard.succeeded()
        except KeyError as exc:
            guard.missed(address)
            raise HTTPException(403, "wrong or expired code") from exc
        return {
            "room_id": room.room_id,
            "name": room.name,
            "desk_id": store.desk_id,
            "desk_identity": store.identity_hex,
        }

    @app.websocket("/ws/room")
    async def room_socket(ws: WebSocket) -> None:
        # The room may go away, or give up on a desk it does not trust, at any point.
        with contextlib.suppress(WebSocketDisconnect):
            await _room_socket(ws)

    async def _room_socket(ws: WebSocket) -> None:
        await ws.accept()
        hub.loop = asyncio.get_running_loop()
        try:
            hello = json.loads(await ws.receive_text())
            room_id = str(hello.get("room_id", ""))
            claimed = secure.public(str(hello.get("identity", "")))
        except (ValueError, TypeError, AttributeError):
            await ws.close(code=4400)  # not a room of this version
            return
        known = store.room_identity(room_id)
        channel = Channel(ws, sealer, claimed, room_id)
        if known is None:
            # Sealed to the identity the room gave: only that room can read it, and it can
            # check that this desk sent it.
            await channel.send({"type": "unbind"})
            await ws.close()
            return
        if known != claimed:
            await ws.close(code=4401)
            return
        opener.add_peer(known)
        try:
            sender, auth = opener.open(await _receive(ws))
            if sender != known or not isinstance(auth, dict) or auth.get("room") != room_id:
                raise EnvelopeError("not this room")
            session = bytes.fromhex(str(auth.get("session", "")))
            if auth.get("type") != "auth" or len(session) != 32:
                raise EnvelopeError("no session key")
        except (EnvelopeError, ValueError):
            await ws.close(code=4401)
            return
        mine = secure.session_key(opener)
        await channel.send({"type": "ack", "session": mine.hex()})
        channel.session = session
        hub.channels[room_id] = channel
        store.seen(room_id)
        if metrics is not None:
            metrics.event("room", f"{_room_name(store, room_id)} connected")
        room = store.room(room_id)
        if room is not None:  # a room that restarted learns whether it is open
            await channel.send(room.message())
            songs = member_message(store, room_id)
            if songs is not None:
                await channel.send(songs)
        await channel.send(products_message(store))
        if room is not None:
            await channel.send(folders_message(room))
        try:
            while True:
                try:
                    sender, message = opener.open(await _receive(ws))
                except EnvelopeError:
                    log.warning("ignored a room message that its room did not seal")
                    continue
                if sender != known:
                    continue
                store.seen(room_id)
                if isinstance(message, dict) and message.get("type") == "admin_report":
                    hub.reports[room_id] = clean_report(message)
                elif isinstance(message, dict):
                    receive(store, room_id, message)
        except WebSocketDisconnect:
            pass
        finally:
            opener.remove_session_key(mine)
            if hub.channels.get(room_id) is channel:
                del hub.channels[room_id]
                if metrics is not None:
                    metrics.event("room", f"{_room_name(store, room_id)} disconnected")

    return app


async def _receive(ws: WebSocket) -> bytes:
    """One frame from the room, text or bytes."""
    message = await ws.receive()
    if message.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(int(message.get("code", 1000)))
    data = message.get("bytes")
    if data is None:
        data = str(message.get("text", "")).encode()
    return bytes(data)


def _room_name(store: DeskStore, room_id: str) -> str:
    room = store.room(room_id)
    return room.name if room is not None else room_id


def receive(store: DeskStore, room_id: str, message: dict[str, Any]) -> None:
    """A service call or an order from a room. Rooms only order while they are open."""
    kind = message.get("type")
    room = store.room(room_id)
    if room is None or not room.is_open:
        return
    if kind == "heartbeat":
        store.note_song(room_id, str(message.get("song", "")))
    elif kind == "member_song":
        # Only for the member this room was opened for, and only while that is switched on.
        member = store.session_member(room_id) if member_songs_on(store) else None
        song = message.get("song")
        if member is not None and isinstance(song, dict):
            store.add_member_song(member.member_id, str(message.get("kind", "")), song)
    elif kind == "score":
        points = message.get("points")
        if isinstance(points, int) and 0 <= points <= 100:
            store.add_score(
                room_id,
                points,
                str(message.get("title", ""))[:80],
                str(message.get("singer", ""))[:40],
            )
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
    pictures = store.product_pictures()
    return {
        "type": "products",
        "currency": store.setting("currency", "$"),
        "items": [
            {
                "product_id": p.product_id,
                "name": p.name,
                "category": p.category,
                "price": p.price,
                "picture": pictures.get(str(p.product_id), ""),  # base64 JPEG, or ""
            }
            for p in store.products(active_only=True)
        ],
    }


def clean_report(message: dict[str, Any]) -> dict[str, Any]:
    """Keep a room's report small and plain: it is shown to staff, never executed."""
    raw = json.dumps(message)[:20_000]
    try:
        report = json.loads(raw)
    except ValueError:
        return {}
    return report if isinstance(report, dict) else {}


def folders_message(room: Room) -> dict[str, Any]:
    return {"type": "local_folders", "folders": room.local_folders}


def tell_all_products(store: DeskStore, hub: Hub) -> None:
    for room_id in hub.online():
        hub.send_soon(room_id, products_message(store))


def member_songs_on(store: DeskStore) -> bool:
    """Settings → Members: whether members' songs follow them into rooms."""
    return store.setting("member_songs", "1") != "0"


def member_message(store: DeskStore, room_id: str) -> dict[str, Any] | None:
    """The songs of the member this room is open for, or None. Sent to that room only."""
    room = store.room(room_id)
    if room is None or not room.is_open or not member_songs_on(store):
        return None
    member = store.session_member(room_id)
    if member is None:
        return None
    return {
        "type": "member_songs",
        "name": member.name[:40],
        "sung": store.member_songs(member.member_id, "sung"),
        "favourites": store.member_songs(member.member_id, "favourite"),
    }


def tell(store: DeskStore, hub: Hub, room_id: str) -> None:
    """Send a room its current open/closed state after the desk changed it."""
    room = store.room(room_id)
    if room is not None:
        hub.send_soon(room_id, room.message())
        songs = member_message(store, room_id)
        if songs is not None:
            hub.send_soon(room_id, songs)


def unbind(store: DeskStore, hub: Hub, room_id: str) -> None:
    """Forget a room; if it is connected it turns back into a stand-alone machine now."""
    hub.send_soon(room_id, {"type": "unbind"})
    store.remove(room_id)
