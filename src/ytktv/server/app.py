"""The local web server behind phone song requests."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import socket
import threading
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ytktv.audio.sfx import SFX_NAMES
from ytktv.core.controller import KTVController
from ytktv.core.models import Song, VocalMode
from ytktv.youtube.parse import extract_video_id
from ytktv.youtube.search import ARTISTS, HOT_CATEGORIES

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
    scoring: bool | None = None
    show_lyrics: bool | None = None
    lyrics_offset: float | None = Field(default=None, ge=-10, le=10)


class PlaylistIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    from_queue: bool = False


class PlaylistImportIn(BaseModel):
    url: str = Field(min_length=1, max_length=400)


class PlaylistEnqueueIn(BaseModel):
    shuffle: bool = False
    singer: str = Field(default="", max_length=40)


class MicIn(BaseModel):
    """Any subset of one channel strip's controls."""

    gain: float | None = Field(default=None, ge=0, le=2)
    low_db: float | None = Field(default=None, ge=-12, le=12)
    mid_db: float | None = Field(default=None, ge=-12, le=12)
    high_db: float | None = Field(default=None, ge=-12, le=12)
    reverb: float | None = Field(default=None, ge=0, le=1)
    echo: float | None = Field(default=None, ge=0, le=1)
    comp: float | None = Field(default=None, ge=0, le=1)
    pan: float | None = Field(default=None, ge=-1, le=1)
    fader: float | None = Field(default=None, ge=0, le=1)
    mute: bool | None = None


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class ReactionIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=8)


class DanmakuIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)


# Controller events that are forwarded to phones over the WebSocket.
_PUSHED_TOPICS = frozenset({"state", "position", "toast", "danmaku", "score", "playlists", "mixer"})


def client_id(request: Request) -> str:
    """A short name for the device a request came from, so a phone can find its own songs.

    Phones are told apart by their address on the network. The address itself is not
    handed out to the other phones, only a fingerprint of it.
    """
    host = request.client.host if request.client else ""
    return hashlib.sha256(host.encode()).hexdigest()[:10] if host else ""


class _Broadcaster:
    """Fans controller events out to WebSocket clients on the server's loop."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[asyncio.Queue[tuple[str, Any]]] = set()

    def publish(self, topic: str, payload: Any) -> None:
        loop = self.loop
        if loop is None or topic not in _PUSHED_TOPICS:
            return
        with contextlib.suppress(RuntimeError):  # loop already closed on shutdown
            loop.call_soon_threadsafe(self._fan_out, topic, payload)

    def _fan_out(self, topic: str, payload: Any) -> None:
        for client in self.clients:
            if client.qsize() < 100:
                client.put_nowait((topic, payload))


class OrderItem(BaseModel):
    product_id: int
    qty: int = Field(ge=1, le=20)


class ServiceIn(BaseModel):
    kind: str = Field(default="Other", max_length=40)
    note: str = Field(default="", max_length=200)
    items: list[OrderItem] = Field(default_factory=list, max_length=50)


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

    @app.exception_handler(PermissionError)
    async def room_closed(_request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=423)

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
        controller.remember_search(q)
        return [{**song.to_dict(), **controller.song_marks(song)} for song in songs]

    @app.get("/api/suggest")
    def suggest(q: str) -> list[str]:
        suggest_fn = getattr(source, "suggest", None)
        return suggest_fn(q[:100]) if suggest_fn else []

    @app.get("/api/artists")
    def artists() -> dict[str, list[str]]:
        return {group: list(names) for group, names in ARTISTS.items()}

    @app.get("/api/categories")
    def categories() -> list[str]:
        return list(HOT_CATEGORIES)

    @app.get("/api/hot")
    def hot(category: str) -> list[dict[str, Any]]:
        if category not in HOT_CATEGORIES:
            raise HTTPException(404, "unknown category")
        try:
            return [{**s.to_dict(), **controller.song_marks(s)} for s in source.hot(category)]
        except Exception as exc:
            raise HTTPException(502, "YouTube search failed") from exc

    @app.get("/api/me")
    def me(request: Request) -> dict[str, str]:
        return {"id": client_id(request)}

    @app.post("/api/queue")
    def enqueue(body: EnqueueIn, request: Request) -> dict[str, Any]:
        song: Song | None = body.song.to_song() if body.song else None
        if song is None and body.url:
            video_id = extract_video_id(body.url)
            if video_id is None:
                raise HTTPException(400, "not a YouTube link")
            song = source.lookup(video_id)
        if song is None:
            raise HTTPException(400, "no song given")
        return controller.enqueue(
            song, singer=body.singer.strip(), priority=body.priority, owner=client_id(request)
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
        if body.scoring is not None:
            controller.set_scoring(body.scoring)
        if body.show_lyrics is not None:
            controller.set_show_lyrics(body.show_lyrics)
        if body.lyrics_offset is not None:
            controller.set_lyrics_offset(body.lyrics_offset)
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

    @app.post("/api/service")
    def service(body: ServiceIn) -> dict[str, bool]:
        desk = controller.front_desk
        if desk is None:
            raise HTTPException(404, "this machine is not a room")
        ok = (
            desk.order([(i.product_id, i.qty) for i in body.items])
            if body.items
            else desk.call(body.kind, body.note)
        )
        if not ok:
            raise HTTPException(423, "This room is closed")
        return {"ok": True}

    @app.post("/api/game/{name}")
    def game(name: str) -> dict[str, str]:
        try:
            return controller.play_game(name)
        except ValueError as exc:
            raise HTTPException(404, "no such game") from exc

    @app.post("/api/danmaku")
    def danmaku(body: DanmakuIn) -> dict[str, bool]:
        if not controller.send_danmaku(body.text):
            raise HTTPException(429, "too many messages, slow down")
        return {"ok": True}

    @app.post("/api/reaction")
    def reaction(body: ReactionIn) -> dict[str, bool]:
        if not controller.send_reaction(body.emoji):
            raise HTTPException(429, "too many reactions, or not one of the room's emoji")
        return {"ok": True}

    @app.get("/api/lyrics")
    def lyrics() -> list[dict[str, Any]]:
        return [line.to_dict() for line in controller.lyrics]

    @app.get("/api/mixer")
    def mixer() -> dict[str, Any]:
        return controller.mixer_state()

    @app.post("/api/mixer/mics/{index}")
    def set_mic(index: int, body: MicIn) -> dict[str, Any]:
        if not 0 <= index < len(controller.settings.mics):
            raise HTTPException(404, "no such microphone channel")
        controller.set_mic(index, **body.model_dump(exclude_none=True))
        return controller.mixer_state()

    @app.post("/api/mixer/presets")
    def save_preset(body: PresetIn) -> dict[str, str]:
        try:
            return {"name": controller.save_preset(body.name)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/mixer/presets/{name}/apply")
    def apply_preset(name: str) -> dict[str, Any]:
        try:
            controller.apply_preset(name)
        except KeyError as exc:
            raise HTTPException(404, "no such preset") from exc
        return controller.mixer_state()

    @app.delete("/api/mixer/presets/{name}")
    def delete_preset(name: str) -> dict[str, bool]:
        if not controller.delete_preset(name):
            raise HTTPException(404, "no such saved preset")
        return {"ok": True}

    @app.get("/api/playlists")
    def playlists() -> list[dict[str, Any]]:
        return controller.playlists()

    @app.post("/api/playlists")
    def create_playlist(body: PlaylistIn) -> dict[str, str]:
        try:
            if body.from_queue:
                return {"name": controller.save_queue_as_playlist(body.name)}
            return {"name": controller.create_playlist(body.name)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/playlists/import")
    def import_playlist(body: PlaylistImportIn) -> dict[str, str]:
        try:
            return {"name": controller.import_playlist(body.url)}
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            log.warning("playlist import failed: %s", exc)
            raise HTTPException(502, "could not read that playlist from YouTube") from exc

    @app.get("/api/playlists/{name}")
    def playlist(name: str) -> list[dict[str, Any]]:
        songs = controller.library.playlist(name)
        if songs is None:
            raise HTTPException(404, "no such playlist")
        return [song.to_dict() for song in songs]

    @app.delete("/api/playlists/{name}")
    def delete_playlist(name: str) -> dict[str, bool]:
        if not controller.delete_playlist(name):
            raise HTTPException(404, "no such playlist")
        return {"ok": True}

    @app.post("/api/playlists/{name}/songs")
    def add_to_playlist(name: str, body: SongIn) -> dict[str, bool]:
        if controller.library.playlist(name) is None:
            raise HTTPException(404, "no such playlist")
        return {"added": controller.add_to_playlist(name, body.to_song())}

    @app.delete("/api/playlists/{name}/songs/{video_id}")
    def remove_from_playlist(name: str, video_id: str) -> dict[str, bool]:
        if not controller.remove_from_playlist(name, video_id):
            raise HTTPException(404, "not in that playlist")
        return {"ok": True}

    @app.post("/api/playlists/{name}/enqueue")
    def enqueue_playlist(name: str, body: PlaylistEnqueueIn, request: Request) -> dict[str, int]:
        try:
            added = controller.enqueue_playlist(
                name, body.shuffle, body.singer.strip(), client_id(request)
            )
        except KeyError as exc:
            raise HTTPException(404, "no such playlist") from exc
        return {"added": added}

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

    def __init__(
        self,
        app: FastAPI,
        port: int,
        host: str = "0.0.0.0",
        certificate: tuple[Path, Path] | None = None,
    ) -> None:
        """With *certificate* (certificate file, key file) the server speaks HTTPS."""
        import uvicorn

        self.port = port
        self._secure = certificate is not None
        tls: dict[str, Any] = {}
        if certificate is not None:
            tls = {"ssl_certfile": str(certificate[0]), "ssl_keyfile": str(certificate[1])}
        # log_config=None: uvicorn's own logging set-up asks the console whether it has
        # colours, and a windowed Windows build has no console at all (sys.stderr is
        # None), which made the server fail to start there. YTKTV's logging is enough.
        config = uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
            log_config=None,
            **tls,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, name="ytktv-server", daemon=True)

    @property
    def url(self) -> str:
        return f"{'https' if self._secure else 'http'}://{lan_ip()}:{self.port}"

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=3)
