import json
import time

import pytest
from fastapi.testclient import TestClient

from ytktv.config import Settings
from ytktv.desk.server import create_desk_app
from ytktv.desk.store import CODE_SECONDS, DeskStore
from ytktv.rooms import binding, crypto
from ytktv.rooms.protocol import DeskImpostor, RoomSession


def test_pairing_codes_work_once_and_expire():
    store = DeskStore()
    code = store.new_code(now=1000)
    room, key = store.pair(code, "Kids", now=1001)
    assert room.name == "Kids" and store.key(room.room_id) == key
    with pytest.raises(KeyError):
        store.pair(code, "Again", now=1002)
    late = store.new_code(now=1000)
    with pytest.raises(KeyError):
        store.pair(late, "Late", now=1000 + CODE_SECONDS + 1)


def test_the_desk_keeps_its_identity(tmp_path):
    first = DeskStore(tmp_path / "desk.sqlite3")
    again = DeskStore(tmp_path / "desk.sqlite3")
    assert first.desk_id == again.desk_id and len(first.fingerprint) >= 4
    assert DeskStore().desk_id != first.desk_id


def test_a_room_may_unbind_itself_only_after_a_week_without_the_desk():
    settings = Settings(
        desk_url="https://desk", room_id="r", room_key="k", desk_key="ab", desk_last_seen=0
    )
    day = 24 * 3600
    assert not binding.can_unbind(settings, now=6 * day)
    assert binding.can_unbind(settings, now=8 * day)
    assert not binding.can_unbind(Settings(), now=8 * day)
    binding.clear(settings)
    assert not binding.is_bound(settings)


def handshake(ws, session):
    """The room's side of the handshake; returns the first message after it."""
    ws.send_text(session.hello())
    first = session.open(ws.receive_text())
    if first["type"] == "challenge":
        ws.send_text(session.answer(first))
        first = session.open(ws.receive_text())
    return first


def test_rooms_and_the_desk_prove_who_they_are():
    from starlette.websockets import WebSocketDisconnect

    store = DeskStore()
    app = create_desk_app(store)
    with TestClient(app) as http:
        assert http.post("/api/pair", json={"code": "000000"}).status_code == 403
        reply = http.post("/api/pair", json={"code": store.new_code(), "name": "Adults"}).json()
        assert reply["desk_id"] == crypto.desk_id(reply["desk_key"])
        with http.websocket_connect("/ws/room") as ws:
            session = RoomSession(reply["room_id"], reply["key"], store.public_key)
            assert handshake(ws, session)["type"] == "ack"
            assert app.state.hub.online() == {reply["room_id"]}

        # A room with the wrong key is refused.
        with http.websocket_connect("/ws/room") as ws:
            session = RoomSession(reply["room_id"], "wrong", store.public_key)
            with pytest.raises(WebSocketDisconnect):
                handshake(ws, session)

        # A desk with another key cannot talk to the room, so it cannot unbind it.
        with http.websocket_connect("/ws/room") as ws:
            session = RoomSession(reply["room_id"], reply["key"], DeskStore().public_key)
            ws.send_text(session.hello())
            with pytest.raises(DeskImpostor):
                session.open(ws.receive_text())

        # An unknown room gets a signed unbind it can trust.
        store.remove(reply["room_id"])
        with http.websocket_connect("/ws/room") as ws:
            session = RoomSession(reply["room_id"], reply["key"], store.public_key)
            assert handshake(ws, session)["type"] == "unbind"


def test_room_messages_must_be_signed_and_fresh():
    store = DeskStore()
    session = RoomSession("r", "k", store.public_key)
    body = json.dumps({"type": "unbind", "seq": 1}, sort_keys=True)
    good = json.dumps({"body": body, "sig": store.sign(f"{session.nonce}|{body}".encode())})
    assert session.open(good)["type"] == "unbind"
    with pytest.raises(DeskImpostor):
        session.open(good)  # replayed
    forged = json.dumps({"body": body, "sig": DeskStore().sign(b"x")})
    with pytest.raises(DeskImpostor):
        RoomSession("r", "k", store.public_key).open(forged)


def test_front_desk_card_and_desk_window(qtbot, tmp_path):
    from ytktv.config import SettingsStore
    from ytktv.desk.server import Hub
    from ytktv.desk.window import DeskWindow
    from ytktv.ui.front_desk_card import FrontDeskCard

    store = SettingsStore(tmp_path / "settings.json")
    card = FrontDeskCard(store)
    qtbot.addWidget(card)
    assert not card.form.isHidden() and card.bound_row.isHidden()
    desk = DeskStore()
    pairing = binding.Pairing("https://desk:8770", "r1", "k", "Kids", desk.desk_id, desk.public_key)
    assert pairing.fingerprint == desk.fingerprint
    binding.apply(store.settings, pairing)
    card.refresh()
    assert card.form.isHidden() and not card.unbind_button.isEnabled()
    store.settings.desk_last_seen = time.time() - 8 * 24 * 3600
    card.refresh()
    assert card.unbind_button.isEnabled()
    card.unbind()
    assert not binding.is_bound(store.settings)

    desk.pair(desk.new_code(), "Adults")
    window = DeskWindow(desk, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.add_room()
    assert window.code_label.text().isdigit()
    assert desk.fingerprint in window.panel_info.text()
    window.room_list.setCurrentRow(0)
    window.unbind_room()
    assert desk.rooms() == []


def test_room_state_follows_the_desk():
    from ytktv.rooms.state import RoomState, format_left

    state = RoomState()
    assert state.closed and state.seconds_left() is None
    assert state.apply({"type": "open", "guest": "Kim", "ends_at": 1000.0})
    assert not state.closed and state.guest == "Kim" and state.seconds_left(now=400) == 600
    assert state.apply({"type": "open", "ends_at": None}) and state.seconds_left() is None
    assert state.apply({"type": "close"}) and state.closed
    assert not state.apply({"type": "ack"})
    assert format_left(65) == "1:05" and format_left(3725) == "1:02:05"


def test_the_desk_opens_extends_and_closes_rooms(qtbot):
    from ytktv.desk.server import Hub
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Kids")
    assert store.room(room.room_id).message() == {"type": "close"}
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.select(room.room_id)
    window.open_room(guest="Kim", length="1 hour")
    opened = store.room(room.room_id)
    assert opened.is_open and opened.guest == "Kim" and opened.message()["type"] == "open"
    first_end = opened.ends_at
    window.extend_room(length="30 minutes")
    assert store.room(room.room_id).ends_at == pytest.approx(first_end + 1800)
    assert "Kim" in window.panel_info.text()
    window.close_room(confirm=False)
    assert not store.room(room.room_id).is_open
    store.open_room(room.room_id, "", None)
    assert store.room(room.room_id).message() == {"type": "open", "guest": "", "ends_at": None}
