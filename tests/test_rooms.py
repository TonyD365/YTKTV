import json

import pytest
from fastapi.testclient import TestClient

from ytktv.config import Settings
from ytktv.desk.server import create_desk_app
from ytktv.desk.store import CODE_SECONDS, DeskStore
from ytktv.rooms import binding


def test_pairing_codes_work_once_and_expire():
    store = DeskStore()
    code = store.new_code(now=1000)
    room, key = store.pair(code, "Kids", now=1001)
    assert room.name == "Kids" and store.verify(room.room_id, key)
    assert not store.verify(room.room_id, "wrong")
    with pytest.raises(KeyError):
        store.pair(code, "Again", now=1002)
    late = store.new_code(now=1000)
    with pytest.raises(KeyError):
        store.pair(late, "Late", now=1000 + CODE_SECONDS + 1)


def test_a_room_may_unbind_itself_only_after_a_week_without_the_desk():
    settings = Settings(desk_url="http://desk", room_id="r", room_key="k", desk_last_seen=0)
    day = 24 * 3600
    assert not binding.can_unbind(settings, now=6 * day)
    assert binding.can_unbind(settings, now=8 * day)
    assert not binding.can_unbind(Settings(), now=8 * day)  # not bound at all
    binding.clear(settings)
    assert not binding.is_bound(settings)


def test_rooms_pair_connect_and_get_unbound_over_the_network():
    store = DeskStore()
    app = create_desk_app(store)
    with TestClient(app) as http:
        assert http.post("/api/pair", json={"code": "000000"}).status_code == 403
        reply = http.post("/api/pair", json={"code": store.new_code(), "name": "Adults"}).json()
        assert reply["name"] == "Adults"
        with http.websocket_connect("/ws/room") as ws:
            ws.send_text(json.dumps({"room_id": reply["room_id"], "key": reply["key"]}))
            assert json.loads(ws.receive_text()) == {"type": "ack"}
            assert app.state.hub.online() == {reply["room_id"]}
            ws.send_text(json.dumps({"type": "heartbeat"}))
        store.remove(reply["room_id"])
        with http.websocket_connect("/ws/room") as ws:
            ws.send_text(json.dumps({"room_id": reply["room_id"], "key": reply["key"]}))
            assert json.loads(ws.receive_text()) == {"type": "unbind"}
