"""A member's songs follow them into the room the Desk opened for them, and back."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from ytktv.config import Settings, SettingsStore
from ytktv.desk import store as desk_store
from ytktv.desk.server import create_desk_app, member_message, receive
from ytktv.desk.store import DeskStore
from ytktv.rooms.client import RoomClient, member_lists
from ytktv.rooms.protocol import RoomSession


def song(n: int) -> dict:
    return {"video_id": f"v{n}", "title": f"Song {n}", "channel": "C", "duration": 200}


def opened_for_member(store: DeskStore) -> tuple[str, int, str]:
    room, key = store.pair(store.new_code(), "Kids")
    member_id = store.add_member("Kim", "5550100")
    store.open_room(room.room_id, "Kim", 60)
    store.set_session_member(room.room_id, member_id)
    return room.room_id, member_id, key


def test_songs_are_saved_per_member_and_capped():
    store = DeskStore()
    room_id, member_id, _ = opened_for_member(store)
    for n in range(desk_store.MEMBER_RECENT + 5):
        receive(store, room_id, {"type": "member_song", "kind": "sung", "song": song(n)})
    receive(store, room_id, {"type": "member_song", "kind": "favourite", "song": song(1)})
    receive(store, room_id, {"type": "member_song", "kind": "evil", "song": song(2)})
    receive(store, room_id, {"type": "member_song", "kind": "sung", "song": {"title": "x"}})
    sung = store.member_songs(member_id, "sung")
    assert len(sung) == desk_store.MEMBER_RECENT
    assert [s["video_id"] for s in store.member_songs(member_id, "favourite")] == ["v1"]
    message = member_message(store, room_id)
    assert message is not None and message["name"] == "Kim"
    assert len(message["sung"]) == desk_store.MEMBER_RECENT

    # Switched off at the desk: nothing is sent or saved.
    store.set_setting("member_songs", "0")
    assert member_message(store, room_id) is None
    receive(store, room_id, {"type": "member_song", "kind": "favourite", "song": song(99)})
    assert len(store.member_songs(member_id, "favourite")) == 1
    store.set_setting("member_songs", "1")

    # A closed room, or one opened without a member, gets nobody's songs.
    store.close_room(room_id)
    assert member_message(store, room_id) is None
    store.open_room(room_id, "Lee", 60)
    assert store.session_member(room_id) is None and member_message(store, room_id) is None
    receive(store, room_id, {"type": "member_song", "kind": "sung", "song": song(500)})
    assert all(s["video_id"] != "v500" for s in store.member_songs(member_id, "sung"))


def test_the_list_goes_only_to_the_members_room_signed():
    store = DeskStore()
    room_id, member_id, key = opened_for_member(store)
    other, other_key = store.pair(store.new_code(), "Adults")
    store.open_room(other.room_id, "Lee", 60)
    store.add_member_song(member_id, "favourite", song(7))
    with TestClient(create_desk_app(store)) as http:
        for rid, k, expect in ((room_id, key, True), (other.room_id, other_key, False)):
            with http.websocket_connect("/ws/room") as ws:
                session = RoomSession(rid, k, store.public_key)
                ws.send_text(session.hello())
                ws.send_text(session.answer(session.open(ws.receive_text())))
                kinds = [session.open(ws.receive_text()) for _ in range(3)]
                types = [m["type"] for m in kinds]
                assert types[:2] == ["ack", "open"]
                assert (types[2] == "member_songs") is expect
                if expect:
                    assert kinds[2]["room"] == rid
                    assert kinds[2]["favourites"][0]["video_id"] == "v7"


def test_the_room_keeps_the_list_for_this_session_only(tmp_path):
    settings = SettingsStore(tmp_path / "s.json")
    settings.settings = Settings()
    client = RoomClient(settings, lambda kind, data: None)
    client._handle({"type": "open", "guest": "Kim"})
    assert client.member_song("sung", song(1)) is False  # no member: nothing goes out
    big = {"type": "member_songs", "name": "Kim", "sung": [song(n) for n in range(80)]}
    client._handle(big)
    assert client.member is not None and len(client.member["sung"]) == 50
    assert client.member["favourites"] == []
    client._handle({"type": "close"})
    assert client.member is None
    assert member_lists({"sung": "nope", "favourites": [1, {"video_id": "a"}]})["sung"] == []


def test_controller_reports_sung_and_favourite_songs(tmp_path):
    from tests.helpers import make_controller

    controller, _player, _resolver = make_controller(tmp_path)
    sent: list[tuple[str, dict]] = []

    class Desk:
        member = {"name": "Kim", "sung": [song(3)], "favourites": []}
        online, currency, products = True, "$", []

        def member_song(self, kind: str, data: dict) -> bool:
            sent.append((kind, data))
            return True

    controller.front_desk = Desk()
    controller.room_closed = False
    assert controller.state()["member_songs"]["name"] == "Kim"
    from ytktv.core.models import Song

    controller.toggle_favorite(Song("v9", "Nine"))
    assert sent and sent[0][0] == "favourite" and sent[0][1]["video_id"] == "v9"
    controller.room_closed = True
    assert controller.member_songs() is None
    assert json.dumps(controller.state())  # still plain JSON for the phones


def test_the_desk_opens_a_room_for_a_member(qtbot):
    from ytktv.desk.server import Hub
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Kids")
    store.add_member("Kim", "5550100")
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.select(room.room_id)
    window.open_room(guest="", length="1 hour", member_phone="555-0100")
    assert store.room(room.room_id).guest == "Kim"
    member = store.session_member(room.room_id)
    assert member is not None and member.name == "Kim"
