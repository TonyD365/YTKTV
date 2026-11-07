"""A Desk and a room talking over a real network connection: pairing, opening the room,
a service call, an order, closing it and unbinding."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from typing import Any

import pytest
import uvicorn

from ytktv.config import SettingsStore
from ytktv.desk.server import Hub, create_desk_app, tell, unbind
from ytktv.desk.store import DeskStore
from ytktv.rooms import binding, discovery
from ytktv.rooms.client import RoomClient


def wait_for(check: Callable[[], Any], what: str, seconds: float = 20) -> Any:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    pytest.fail(f"timed out waiting for {what}")


@pytest.fixture
def desk():
    store, hub = DeskStore(), Hub()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            create_desk_app(store, hub), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for(lambda: server.started, "the Desk to start")
    yield store, hub, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


def test_a_room_and_the_desk_over_the_network(desk, tmp_path, monkeypatch):
    store, hub, url = desk
    # Keep the address it paired with (no multicast discovery here).
    monkeypatch.setattr(discovery, "find", lambda desk_id, seconds=2.0: None)

    pairing = binding.request(url, store.new_code(), "Room 1")
    settings = SettingsStore(tmp_path / "settings.json")
    binding.apply(settings.settings, pairing)
    settings.save()
    events: list[tuple[str, Any]] = []
    client = RoomClient(settings, lambda kind, data: events.append((kind, data)))
    client.start()
    try:
        room_id = pairing.room_id
        wait_for(lambda: client.online and room_id in hub.online(), "the room to connect")
        assert client.state.closed  # bound rooms wait for the Desk to open them

        store.open_room(room_id, "Kim", 60)
        tell(store, hub, room_id)
        wait_for(lambda: not client.state.closed, "the room to open")

        assert client.call("waiter", "two glasses")
        call = wait_for(lambda: [c for c in store.calls() if c.room_id == room_id], "the call")[0]
        assert call.kind == "waiter"

        store.close_room(room_id)
        tell(store, hub, room_id)
        wait_for(lambda: client.state.closed, "the room to close")

        unbind(store, hub, room_id)
        wait_for(lambda: not binding.is_bound(settings.settings), "the room to be unbound")
        assert not client.state.closed  # a stand-alone room again
    finally:
        client.stop()
