"""The desk's server: rooms pair with it and stay connected over a WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ytktv.desk.store import DeskStore

DESK_PORT = 8770


class PairIn(BaseModel):
    code: str
    name: str = ""


class Hub:
    """The rooms connected right now, so the desk can push messages to them."""

    def __init__(self) -> None:
        self.sockets: dict[str, WebSocket] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def online(self) -> set[str]:
        return set(self.sockets)

    async def send(self, room_id: str, message: dict[str, Any]) -> bool:
        ws = self.sockets.get(room_id)
        if ws is None:
            return False
        await ws.send_text(json.dumps(message))
        return True

    def send_soon(self, room_id: str, message: dict[str, Any]) -> None:
        """Push from another thread (the desk's UI)."""
        if self.loop is not None:
            asyncio.run_coroutine_threadsafe(self.send(room_id, message), self.loop)


def create_desk_app(store: DeskStore, hub: Hub | None = None) -> FastAPI:
    hub = hub or Hub()
    app = FastAPI(title="YTKTV Desk")
    app.state.hub = hub

    @app.post("/api/pair")
    def pair(body: PairIn) -> dict[str, str]:
        try:
            room, key = store.pair(body.code.strip(), body.name.strip())
        except KeyError as exc:
            raise HTTPException(403, "wrong or expired code") from exc
        return {"room_id": room.room_id, "key": key, "name": room.name}

    @app.websocket("/ws/room")
    async def room_socket(ws: WebSocket) -> None:
        await ws.accept()
        hub.loop = asyncio.get_running_loop()
        hello = json.loads(await ws.receive_text())
        room_id = str(hello.get("room_id", ""))
        if not store.verify(room_id, str(hello.get("key", ""))):
            await ws.send_text(json.dumps({"type": "unbind"}))
            await ws.close()
            return
        hub.sockets[room_id] = ws
        store.seen(room_id)
        await ws.send_text(json.dumps({"type": "ack"}))
        try:
            while True:
                json.loads(await ws.receive_text())
                store.seen(room_id)
        except WebSocketDisconnect:
            pass
        finally:
            if hub.sockets.get(room_id) is ws:
                del hub.sockets[room_id]

    return app


def unbind(store: DeskStore, hub: Hub, room_id: str) -> None:
    """Forget a room; if it is connected it turns back into a stand-alone machine now."""
    store.remove(room_id)
    hub.send_soon(room_id, {"type": "unbind"})
