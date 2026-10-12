"""The HTTPS side door through which phones act as microphones.

It is a server of its own (see tls.py for why it needs HTTPS) with one page and one
WebSocket. A phone says its name and recording rate, then sends raw 16-bit mono sound
in small binary packets; the server answers pings and reports how much is buffered.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ytktv.audio.phone_mic import PhoneMics

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
RATES = range(8000, 96001)
MAX_PACKET = 1 << 16  # bytes; a packet is normally a few hundred


def create_mic_app(phones: PhoneMics, channel_of: Any = None) -> FastAPI:
    """*channel_of(name)* returns the mixer channel (1-based) a phone is on, or None."""
    app = FastAPI(title="YTKTV phone microphone", docs_url=None, redoc_url=None)

    @app.get("/", include_in_schema=False)
    def page() -> FileResponse:
        return FileResponse(STATIC / "mic.html", headers={"Cache-Control": "no-store"})

    @app.websocket("/ws")
    async def stream(ws: WebSocket) -> None:
        await ws.accept()
        key = uuid.uuid4().hex
        source = None
        rate = 48000

        async def report() -> None:
            while True:
                await asyncio.sleep(0.5)
                if source is None:
                    continue
                await ws.send_text(
                    json.dumps(
                        {
                            "name": source.name,
                            "channel": channel_of(source.name) if channel_of else None,
                            "buffer_ms": round(source.buffered_seconds * 1000),
                            "gaps": source.gaps,
                            "level": round(source.peak, 3),
                        }
                    )
                )

        reporter = asyncio.create_task(report())
        try:
            while True:
                message = await ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                data = message.get("bytes")
                if data is not None:
                    if source is not None and len(data) <= MAX_PACKET:
                        source.feed(data, rate)
                    continue
                try:
                    hello = json.loads(message.get("text") or "{}")
                except ValueError:
                    continue
                if "ping" in hello:
                    await ws.send_text(json.dumps({"pong": hello["ping"]}))
                elif "rate" in hello:
                    if int(hello["rate"]) not in RATES:
                        await ws.close(code=1003)
                        break
                    rate = int(hello["rate"])
                    source = phones.connect(key, str(hello.get("name") or ""))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            reporter.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await reporter
            phones.disconnect(key)

    return app
