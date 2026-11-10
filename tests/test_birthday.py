import asyncio
import datetime as dt

import pytest

from ytktv.desk import birthday
from ytktv.desk.store import DeskStore
from ytktv.rooms.protocol import DeskImpostor, RoomSession


class FakeHub:
    def __init__(self):
        self.sent = []

    def send_soon(self, room_id, message):
        self.sent.append((room_id, message))

    def online(self):
        return set()

    def report(self, room_id):
        return None


def _store_with_member(birthday_text="11-10"):
    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Party")
    member_id = store.add_member("Amy Chen", "0912345678")
    store.set_birthday(member_id, birthday_text)
    return store, room


def test_is_birthday_window_and_year_edges():
    today = dt.date(2026, 11, 10)
    assert birthday.is_birthday("11-10", today)
    assert not birthday.is_birthday("11-11", today)
    assert birthday.is_birthday("11-12", today, window=2)
    assert birthday.is_birthday("12-31", dt.date(2027, 1, 1), window=1)
    assert birthday.is_birthday("02-29", dt.date(2027, 2, 28))
    assert not birthday.is_birthday("", today)
    assert not birthday.is_birthday("junk", today)


def test_opening_a_members_room_on_their_birthday_throws_a_party():
    store, room = _store_with_member()
    hub = FakeHub()
    today = dt.date(2026, 11, 10)
    store.open_room(room.room_id, "amy chen", None)
    assert birthday.celebrate_if_birthday(store, hub, room.room_id, today) is not None
    assert hub.sent == [(room.room_id, {"type": "birthday", "name": "Amy"})]
    assert birthday.birthday_member(store, "0912345678", today) is not None
    assert birthday.birthday_member(store, "Amy Chen", dt.date(2026, 11, 12)) is None
    store.set_setting(birthday.WINDOW_SETTING, "3")
    assert birthday.birthday_member(store, "Amy Chen", dt.date(2026, 11, 12)) is not None
    store.set_setting(birthday.ENABLED_SETTING, "0")
    assert birthday.birthday_member(store, "Amy Chen", today) is None
    store.set_setting(birthday.ENABLED_SETTING, "1")
    assert birthday.birthday_member(store, "Bob", today) is None


def test_the_birthday_message_is_signed_for_one_room():
    from ytktv.desk.server import Channel

    store = DeskStore()
    room, key = store.pair(store.new_code(), "Party")
    session = RoomSession(room.room_id, key, store.public_key)
    sent = []

    class WS:
        async def send_text(self, text):
            sent.append(text)

    channel = Channel(WS(), store, session.nonce, room.room_id)
    asyncio.run(channel.send(birthday.message("Amy Chen")))
    message = session.open(sent[0])
    assert message["type"] == "birthday" and message["name"] == "Amy"
    other = RoomSession("other-room", key, store.public_key)
    other.nonce = session.nonce
    with pytest.raises(DeskImpostor):
        other.open(sent[0])


def test_desk_window_birthday_button_and_setting(qtbot):
    from ytktv.desk.deals import DealsSettings
    from ytktv.desk.window import DeskWindow

    store, room = _store_with_member(dt.date.today().strftime("%m-%d"))
    hub = FakeHub()
    window = DeskWindow(store, hub, "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.select(room.room_id)
    window.open_room(guest="Amy Chen", length="1 hour")
    assert (room.room_id, {"type": "birthday", "name": "Amy"}) in hub.sent
    hub.sent.clear()
    window._birthday(name="Bo Lee")
    assert hub.sent == [(room.room_id, {"type": "birthday", "name": "Bo"})]
    deals = DealsSettings(store)
    qtbot.addWidget(deals)
    deals.party.setChecked(False)
    assert not birthday.enabled(store)


def test_the_room_celebrates_on_the_big_screen(monkeypatch):
    from types import SimpleNamespace

    from ytktv.ui import main_window

    calls = []
    fake = SimpleNamespace(
        controller=SimpleNamespace(
            room_closed=False,
            birthday=lambda name, song=None: calls.append(("song", name, song)),
        ),
        mv_window=SimpleNamespace(
            show_game=lambda result, seconds=None: calls.append(result["text"]),
            celebration=SimpleNamespace(burst=lambda: calls.append("confetti")),
        ),
        show_toast=lambda text: None,
        ctx=SimpleNamespace(youtube=None),
    )
    monkeypatch.setattr(main_window, "run_async", lambda work, done, failed: failed(None))
    main_window.MainWindow._desk_birthday(fake, "Amy")
    assert ("song", "Amy", None) in calls
    assert "Happy birthday, Amy!" in calls and "confetti" in calls
