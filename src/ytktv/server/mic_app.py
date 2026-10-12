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


def self_test(report: Any = print) -> int:
    """Check that this build can serve the microphone page over HTTPS. 0 = fine.

    Makes a certificate, starts the server on this computer only, and fetches the
    page through TLS. A packaged build that lost a piece of the TLS or web stack
    fails here instead of on somebody's phone.
    """
    import socket
    import ssl
    import tempfile
    import time
    import urllib.request

    from ytktv.server import tls
    from ytktv.server.app import ServerThread

    try:
        with tempfile.TemporaryDirectory() as folder:
            certificate = tls.ensure_certificate(Path(folder), "127.0.0.1")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            server = ServerThread(
                create_mic_app(PhoneMics()), port, host="127.0.0.1", certificate=certificate
            )
            server.start()
            try:
                trusting = ssl.create_default_context(cafile=str(certificate[0]))
                deadline = time.monotonic() + 15
                while True:
                    try:
                        with urllib.request.urlopen(
                            f"https://127.0.0.1:{port}/", timeout=5, context=trusting
                        ) as response:
                            body = response.read().decode("utf-8")
                        break
                    except OSError:
                        if time.monotonic() > deadline:
                            raise
                        time.sleep(0.2)
            finally:
                server.stop()
            if "Use this phone as a microphone" not in body:
                raise RuntimeError("the microphone page was not served")
            report(f"Served the microphone page over HTTPS ({len(body)} characters).")
    except Exception as exc:
        log.exception("phone microphone self-test failed")
        report(f"FAILED: {exc}")
        return 1
    report("phone microphone self-test passed")
    return 0
