"""The local web server behind phone song requests."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import socket
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ytktv.audio.sfx import SFX_NAMES
from ytktv.core.controller import KTVController
from ytktv.core.models import Song, VocalMode
from ytktv.youtube.parse import extract_video_id
from ytktv.youtube.search import HOT_CATEGORIES

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class SongSource(Protocol):
    def search(self, query: str, limit: int = 24) -> list[Song]: ...

    def hot(self, category: str) -> list[Song]: ...

    def lookup(self, video_id: str) -> Song | None: ...


class SongIn(BaseModel):
    video_id: str = Field(min_length=11, max_length=11, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(default="", max_length=300)
    channel: str = Field(default="", max_length=200)
    duration: int = Field(default=0, ge=0)
    thumbnail: str = Field(default="", max_length=600)

    def to_song(self) -> Song:
        return Song(
            video_id=self.video_id,
            title=self.title or self.video_id,
            channel=self.channel,
            duration=self.duration,
            thumbnail=self.thumbnail,
        )


class EnqueueIn(BaseModel):
    song: SongIn | None = None
    url: str | None = Field(default=None, max_length=300)
    singer: str = Field(default="", max_length=40)
    priority: bool = False


class MoveIn(BaseModel):
    index: int = Field(ge=0)


class SoundIn(BaseModel):
    vocal_mode: VocalMode | None = None
    pitch: int | None = Field(default=None, ge=-6, le=6)
    speed: float | None = Field(default=None, ge=0.5, le=1.5)
    music_volume: int | None = Field(default=None, ge=0, le=100)
    mic_volume: int | None = Field(default=None, ge=0, le=100)
    master_volume: int | None = Field(default=None, ge=0, le=100)
    guide_vocal: int | None = Field(default=None, ge=0, le=100)
    lights: bool | None = None


class DanmakuIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class _Broadcaster:
    """Fans controller events out to WebSocket clients on the server's loop."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[asyncio.Queue[tuple[str, Any]]] = set()

    def publish(self, topic: str, payload: Any) -> None:
        loop = self.loop
        if loop is None or topic not in ("state", "position", "toast", "danmaku"):
            return
        with contextlib.suppress(RuntimeError):  # loop already closed on shutdown
            loop.call_soon_threadsafe(self._fan_out, topic, payload)

    def _fan_out(self, topic: str, payload: Any) -> None:
        for client in self.clients:
            if client.qsize() < 100:
                client.put_nowait((topic, payload))


def create_app(controller: KTVController, source: SongSource) -> FastAPI:
    broadcaster = _Broadcaster()

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        broadcaster.loop = asyncio.get_running_loop()
        unsubscribe = controller.bus.subscribe(broadcaster.publish)
        yield
        unsubscribe()
        broadcaster.loop = None

    app = FastAPI(title="YTKTV", docs_url=None, redoc_url=None, lifespan=lifespan)

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})

    @app.get("/api/state")
    def state() -> dict[str, Any]:
        return controller.state()

    @app.get("/api/search")
    def search(q: str, limit: int = 24) -> list[dict[str, Any]]:
        try:
            songs = source.search(q[:200], max(1, min(limit, 50)))
        except Exception as exc:
            log.warning("search failed: %s", exc)
            raise HTTPException(502, "YouTube search failed") from exc
        return [song.to_dict() for song in songs]

    @app.get("/api/categories")
    def categories() -> list[str]:
        return list(HOT_CATEGORIES)

    @app.get("/api/hot")
    def hot(category: str) -> list[dict[str, Any]]:
        if category not in HOT_CATEGORIES:
            raise HTTPException(404, "unknown category")
        try:
            return [song.to_dict() for song in source.hot(category)]
        except Exception as exc:
            raise HTTPException(502, "YouTube search failed") from exc

    @app.post("/api/queue")
    def enqueue(body: EnqueueIn) -> dict[str, Any]:
        song: Song | None = body.song.to_song() if body.song else None
        if song is None and body.url:
            video_id = extract_video_id(body.url)
            if video_id is None:
                raise HTTPException(400, "not a YouTube link")
            song = source.lookup(video_id)
        if song is None:
            raise HTTPException(400, "no song given")
        return controller.enqueue(
            song, singer=body.singer.strip(), priority=body.priority
        ).to_dict()

    @app.delete("/api/queue/{item_id}")
    def remove(item_id: str) -> dict[str, bool]:
        if not controller.remove(item_id):
            raise HTTPException(404, "not in queue")
        return {"ok": True}

    @app.post("/api/queue/{item_id}/top")
    def top(item_id: str) -> dict[str, bool]:
        if not controller.prioritize(item_id):
            raise HTTPException(404, "not in queue")
        return {"ok": True}

    @app.post("/api/queue/{item_id}/move")
    def move(item_id: str, body: MoveIn) -> dict[str, bool]:
        if not controller.move(item_id, body.index):
            raise HTTPException(404, "not in queue")
        return {"ok": True}

    @app.post("/api/player/{action}")
    def player(action: str) -> dict[str, bool]:
        actions = {
            "skip": controller.skip,
            "replay": controller.replay,
            "pause": controller.toggle_pause,
        }
        if action not in actions:
            raise HTTPException(404, "unknown action")
        actions[action]()
        return {"ok": True}

    @app.post("/api/sound")
    def sound(body: SoundIn) -> dict[str, Any]:
        if body.vocal_mode is not None:
            controller.set_vocal_mode(body.vocal_mode)
        if body.pitch is not None:
            controller.set_pitch(body.pitch)
        if body.speed is not None:
            controller.set_speed(body.speed)
        if body.guide_vocal is not None:
            controller.set_guide_vocal(body.guide_vocal)
        if body.lights is not None:
            controller.set_lights(body.lights)
        for name in ("music", "mic", "master"):
            value = getattr(body, f"{name}_volume")
            if value is not None:
                controller.set_volume(name, value)
        return controller.state()

    @app.post("/api/sfx/{name}")
    def sfx(name: str) -> dict[str, bool]:
        if name not in SFX_NAMES:
            raise HTTPException(404, "unknown effect")
        return {"ok": controller.play_sfx(name)}

    @app.post("/api/danmaku")
    def danmaku(body: DanmakuIn) -> dict[str, bool]:
        if not controller.send_danmaku(body.text):
            raise HTTPException(429, "too many messages, slow down")
        return {"ok": True}

    @app.get("/api/lyrics")
    def lyrics() -> list[dict[str, Any]]:
        return [line.to_dict() for line in controller.lyrics]

    @app.get("/api/favorites")
    def favorites() -> list[dict[str, Any]]:
        return [song.to_dict() for song in controller.library.favorites()]

    @app.post("/api/favorites")
    def toggle_favorite(body: SongIn) -> dict[str, bool]:
        return {"favorite": controller.toggle_favorite(body.to_song())}

    @app.websocket("/ws")
    async def websocket(ws: WebSocket) -> None:
        await ws.accept()
        inbox: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        broadcaster.clients.add(inbox)
        try:
            await ws.send_json({"type": "state", "data": controller.state()})
            while True:
                topic, payload = await inbox.get()
                if topic == "state":
                    # Collapse bursts: only the newest state matters.
                    while not inbox.empty() and inbox._queue[0][0] == "state":  # type: ignore[attr-defined]
                        inbox.get_nowait()
                    payload = controller.state()
                await ws.send_json({"type": topic, "data": payload})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            broadcaster.clients.discard(inbox)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def lan_ip() -> str:
    """Best guess at the address phones on the same network should use."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as sock:
        try:
            sock.connect(("10.255.255.255", 1))  # no packet is sent for UDP connect
            return str(sock.getsockname()[0])
        except OSError:
            return "127.0.0.1"


class ServerThread:
    """Runs uvicorn in a background thread so the Qt loop keeps the main one."""

    def __init__(self, app: FastAPI, port: int, host: str = "0.0.0.0") -> None:
        import uvicorn

        self.port = port
        config = uvicorn.Config(app, host=host, port=port, log_level="warning", access_log=False)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="ytktv-server", daemon=True)

    @property
    def url(self) -> str:
        return f"http://{lan_ip()}:{self.port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=3)
