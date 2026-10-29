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


def test_calls_orders_and_the_bill():
    from ytktv.desk.billing import bill
    from ytktv.desk.server import receive
    from ytktv.desk.store import Product

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Kids")
    cola = store.save_product(Product(0, "Cola", "Drinks", 3.5))
    hidden = store.save_product(Product(0, "Secret", "Drinks", 9, active=False))
    receive(store, room.room_id, {"type": "call", "kind": "Drinks"})
    assert store.calls() == []  # a closed room cannot call or order

    store.set_setting("rate", "20")
    store.open_room(room.room_id, "Kim", 90, now=1000)
    receive(store, room.room_id, {"type": "call", "kind": "Equipment problem", "note": "mic"})
    receive(
        store,
        room.room_id,
        {
            "type": "order",
            "items": [{"product_id": cola, "qty": 2}, {"product_id": hidden, "qty": 1}],
        },
    )
    orders = store.orders(room.room_id)
    assert [(o.name, o.qty) for o in orders] == [("Cola", 2)]  # hidden items are refused
    assert [c.kind for c in store.calls()] == ["Equipment problem", "Order"]
    assert store.finish_call(store.calls()[0].call_id) == room.room_id

    result = bill(store, room.room_id, now=2000)
    assert result.subtotal == 30 + 7  # 90 booked minutes at 20/h, two colas
    store.set_setting("minimum", "50")
    assert bill(store, room.room_id).total == 50
    store.set_order_status(orders[0].order_id, "cancelled")
    assert bill(store, room.room_id).subtotal == 30
    assert "Kids" in result.html()

    store.close_room(room.room_id)
    assert store.orders(room.room_id) == [] and store.calls() == []


def test_open_ended_rooms_are_charged_as_set():
    from ytktv.desk.billing import billed_minutes
    from ytktv.desk.store import Room

    room = Room("r", "Kids", 0, True, "", None, opened_at=0)
    assert billed_minutes(room, "minute", 15, now=61 * 60 + 1) == 62
    assert billed_minutes(room, "hour", 15, now=61 * 60) == 120
    assert billed_minutes(room, "unit", 15, now=61 * 60) == 75


def test_desk_panels(qtbot, tmp_path):
    from ytktv.desk.billing import bill
    from ytktv.desk.panels import BillDialog, ShopSettings
    from ytktv.desk.server import Hub
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "Kids")
    shop = ShopSettings(store)
    qtbot.addWidget(shop)
    shop.add_row()
    shop.table.item(0, 0).setText("Chips")
    shop.table.item(0, 2).setText("2.5")
    shop.save()
    assert [(p.name, p.price) for p in store.products()] == [("Chips", 2.5)]

    store.open_room(room.room_id, "Kim", 60)
    store.add_order(room.room_id, [(store.products()[0].product_id, 1)])
    store.add_call(room.room_id, "Drinks", "")
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.select(room.room_id)
    assert window.stat_calls.text() == "1" and window.call_chips.count() == 1
    window.finish_call(store.calls()[0].call_id)
    assert window.stat_calls.text() == "0"

    dialog = BillDialog(bill(store, room.room_id))
    qtbot.addWidget(dialog)
    dialog.save_pdf(str(tmp_path / "bill.pdf"))
    assert (tmp_path / "bill.pdf").stat().st_size > 0


def test_rooms_from_the_first_test_version_are_dropped(tmp_path):
    import sqlite3

    path = tmp_path / "desk.sqlite3"
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE rooms (id TEXT PRIMARY KEY, name TEXT, key_hash TEXT, last_seen REAL)"
    )
    old.execute("INSERT INTO rooms VALUES ('r', 'Old', 'hash', 0)")
    old.commit()
    old.close()
    store = DeskStore(path)
    assert store.rooms() == []
    room, key = store.pair(store.new_code(), "New")
    assert store.key(room.room_id) == key


def test_desk_password_and_lock_screen(qtbot):
    from ytktv.desk import lock
    from ytktv.desk.server import Hub
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    assert lock.check(store, "anything")  # no password set
    lock.set_password(store, "1234")
    assert lock.check(store, "1234") and not lock.check(store, "4321")
    assert "1234" not in store.setting("password")  # only a salted hash is kept

    store.pair(store.new_code(), "Kids")
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    assert not window.lock_screen.isHidden()  # asks at start
    window.lock_screen.password.setText("nope")
    window.lock_screen.try_unlock()
    assert not window.lock_screen.isHidden() and window.lock_screen.error.text()
    window.lock_screen.password.setText("1234")
    window.lock_screen.try_unlock()
    assert window.lock_screen.isHidden()

    window.room_list.setCurrentRow(0)
    window.unbind_room(password="1234")
    assert store.rooms() == []
    window.security.turn_off(password="1234")
    assert not lock.has_password(store)


def test_broadcast_reaches_the_ticked_open_rooms(qtbot):
    from ytktv.desk.panels import BroadcastDialog

    class Hub:
        sent: list = []

        def send_soon(self, room_id, message):
            self.sent.append((room_id, message))

    store = DeskStore()
    adults, _ = store.pair(store.new_code(), "Adults")
    kids, _ = store.pair(store.new_code(), "Kids")
    shut, _ = store.pair(store.new_code(), "Shut")
    store.open_room(adults.room_id, "", None)
    store.open_room(kids.room_id, "", None)
    hub = Hub()
    dialog = BroadcastDialog(store, hub)
    qtbot.addWidget(dialog)
    assert set(dialog.checks) == {adults.room_id, kids.room_id}  # closed rooms are not listed
    dialog.text.setText("Dinner is ready!")
    dialog.checks[kids.room_id].setChecked(False)
    assert dialog.send() == 1
    assert hub.sent[0][0] == adults.room_id and hub.sent[0][1]["text"] == "Dinner is ready!"


def test_room_lock_state():
    from ytktv.rooms.state import RoomState

    state = RoomState()
    state.apply({"type": "open", "ends_at": None})
    assert state.apply({"type": "lock"}) and state.locked
    assert state.apply({"type": "unlock"}) and not state.locked
    state.apply({"type": "lock"})
    state.apply({"type": "close"})
    assert not state.locked


def test_bookings_clash_and_check_in(qtbot):
    from PySide6.QtCore import QDate, QDateTime, QTime

    from ytktv.desk.pages import BookingDialog, day_bounds
    from ytktv.desk.server import Hub
    from ytktv.desk.store import Booking
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    kids, _ = store.pair(store.new_code(), "Kids")
    adults, _ = store.pair(store.new_code(), "Adults")
    seven = 1_000_000.0
    first = store.book(Booking(0, kids.room_id, seven, 120, "Kim"))
    assert [b.booking_id for b in store.clashes(kids.room_id, seven + 3600, 60)] == [first]
    assert store.clashes(kids.room_id, seven + 2 * 3600, 60) == []  # right after it
    assert store.clashes(adults.room_id, seven, 60) == []  # another room
    store.set_booking_status(first, "cancelled")
    assert store.clashes(kids.room_id, seven, 60) == []

    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    today = QDate.currentDate()
    dialog = BookingDialog(store, today)
    qtbot.addWidget(dialog)
    dialog.room.setCurrentIndex(0)
    dialog.when.setDateTime(QDateTime(today, QTime(23, 0)))
    dialog.guest.setText("Alex")
    assert dialog.save(confirm_clash=False)
    page = window.bookings
    page.calendar.setSelectedDate(today)
    page.refresh()
    assert page.table.rowCount() == 1 and page.table.item(0, 2).text() == "Alex"
    page.table.selectRow(0)
    page.set_status("arrived")
    room = store.room(kids.room_id)
    assert room.is_open and room.guest == "Alex" and room.ends_at is not None
    assert store.bookings(*day_bounds(today))[0].status == "arrived"


def test_closed_sessions_are_kept_in_the_records(qtbot):
    from ytktv.desk.server import Hub, receive
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    kids, _ = store.pair(store.new_code(), "Kids")
    store.set_setting("rate", "10")
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.select(kids.room_id)
    window.open_room(guest="Kim", length="1 hour")
    for song in ("Alexander's Ragtime Band", "Alexander's Ragtime Band", "A Perfect Day"):
        receive(store, kids.room_id, {"type": "heartbeat", "song": song})
    assert store.now_singing(kids.room_id) == "A Perfect Day"
    window.close_room(confirm=False)
    visits = store.history(0, time.time() + 1)
    assert len(visits) == 1 and visits[0].total == 10 and visits[0].guest == "Kim"
    assert visits[0].songs == ["Alexander's Ragtime Band", "A Perfect Day"]
    window.records.refresh()
    assert window.records.table.rowCount() == 1 and "1 sessions" in window.records.summary.text()
    assert "Alexander" in window.records.top_songs.text()


def test_room_types_cleaning_maintenance_and_change_room(qtbot):
    from ytktv.desk.server import Hub
    from ytktv.desk.store import Product
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    small, _ = store.pair(store.new_code(), "101")
    big, _ = store.pair(store.new_code(), "201")
    store.set_type(big.room_id, "VIP", 12)
    assert (store.room(big.room_id).room_type, store.room(big.room_id).capacity) == ("VIP", 12)
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    window.select(small.room_id)
    window.open_room(guest="Kim", length="1 hour")
    cola = store.save_product(Product(0, "Cola", "Drinks", 3, stock=5))
    store.add_order(small.room_id, [(cola, 2)])
    store.note_song(small.room_id, "A Perfect Day")

    window.change_room(target=big.room_id)  # the party moves with its time, orders and songs
    moved = store.room(big.room_id)
    assert moved.is_open and moved.guest == "Kim" and window.selected == big.room_id
    assert [o.name for o in store.orders(big.room_id)] == ["Cola"]
    assert store.now_singing(big.room_id) == "A Perfect Day"
    assert store.room(small.room_id).state == "cleaning" and not store.room(small.room_id).is_open

    window.close_room(confirm=False)
    assert store.room(big.room_id).state == "cleaning"
    window.mark_cleaned()
    assert store.room(big.room_id).state == "ready"
    window.toggle_maintenance()
    assert store.room(big.room_id).state == "maintenance"
    assert not window.room_actions["open"].isEnabled()
    window.toggle_maintenance()
    assert store.room(big.room_id).state == "ready"


def test_stock_runs_out_and_comes_back():
    from ytktv.desk.store import Product

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "101")
    store.open_room(room.room_id, "", None)
    chips = store.save_product(Product(0, "Chips", "Snacks", 2, stock=3))
    assert store.add_order(room.room_id, [(chips, 5)]) == 0  # not enough left
    assert store.add_order(room.room_id, [(chips, 3)]) == 1
    assert store.products(active_only=True) == []  # sold out: off the menu
    store.set_order_status(store.orders(room.room_id)[0].order_id, "cancelled")
    restocked = store.products(active_only=True)[0]
    assert restocked.stock == 3


def test_shift_report_and_hand_over(qtbot):
    from ytktv.desk.billing import bill
    from ytktv.desk.pages import ShiftDialog, shift_report
    from ytktv.desk.store import Product

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "101")
    store.set_setting("rate", "10")
    store.open_room(room.room_id, "Kim", 60)
    cola = store.save_product(Product(0, "Cola", "Drinks", 3))
    store.add_order(room.room_id, [(cola, 2)])
    store.close_room(room.room_id, bill(store, room.room_id))
    report = shift_report(store)
    assert "Sessions closed</td><td align='right'>1" in report and "Cola" in report
    assert "$16.00" in report  # one hour at 10 plus two colas
    dialog = ShiftDialog(store)
    qtbot.addWidget(dialog)
    dialog.hand_over()
    assert "Sessions closed</td><td align='right'>0" in shift_report(store, now=time.time() + 5)


def test_arm_machines_get_arm_builds(monkeypatch):
    from ytktv import bootstrap, updater

    assert updater.platform_suffixes("Windows", "ARM64")[0] == "windows-arm64-setup.exe"
    assert updater.platform_suffixes("Windows", "AMD64") == ["windows-x64-setup.exe"]
    assert updater.platform_suffixes("Linux", "aarch64") == ["linux-aarch64.AppImage"]
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "ARM64")
    assert bootstrap._windows_mpv_asset().match("mpv-dev-aarch64-20261021-git-e471496c56.7z")
    monkeypatch.setattr(bootstrap.platform, "machine", lambda: "AMD64")
    pattern = bootstrap._windows_mpv_asset()
    assert pattern.match("mpv-dev-x86_64-20261021-git-e471496c56.7z")
    assert not pattern.match("mpv-dev-x86_64-v3-20261021-git-e471496c56.7z")


def test_arm_gets_the_cpu_separation_runtime():
    from ytktv.separation.runtime import Gpu, choose_variant

    nvidia = Gpu("nvidia", "RTX", cuda=True)
    assert choose_variant("Windows", nvidia, "AMD64") == "cuda"
    assert choose_variant("Windows", Gpu("intel", "Arc"), "AMD64") == "directml"
    assert choose_variant("Windows", Gpu("qualcomm", "Adreno"), "ARM64") == "cpu"
    assert choose_variant("Linux", nvidia, "aarch64") == "cpu"


def test_scrolling_past_the_price_fields_leaves_them_alone(qtbot):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from ytktv.desk.panels import OnMenu, ShopSettings
    from ytktv.desk.store import Product

    store = DeskStore()
    store.save_product(Product(0, "Cola", "Drinks", 3, active=False))
    shop = ShopSettings(store)
    qtbot.addWidget(shop)
    before = shop.rate.value()
    wheel = QWheelEvent(
        QPointF(5, 5),
        QPointF(5, 5),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(shop.rate, wheel)
    assert shop.rate.value() == before
    switch = shop.table.cellWidget(0, 4)
    assert isinstance(switch, OnMenu) and switch.text() == "Hidden"
    switch.setChecked(True)
    assert switch.text() == "On menu"


def test_the_till_members_and_shift_totals(qtbot, monkeypatch):
    from ytktv.desk.billing import bill
    from ytktv.desk.pages import MembersPage, shift_report
    from ytktv.desk.panels import BillDialog
    from ytktv.desk.store import Product

    store = DeskStore()
    store.set_setting("rate", "100")
    store.set_setting("member_discount", "10")
    room, _ = store.pair(store.new_code(), "101")
    from PySide6.QtWidgets import QMessageBox

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    members = MembersPage(store)
    qtbot.addWidget(members)
    kim = members.new_member(name="Kim", phone="0912 345 678")
    assert kim and members.new_member(name="Copy", phone="0912345678") == 0  # same phone
    assert "already a member" in warned[0]
    members.table.selectRow(0)
    members.top_up(amount=500)
    assert store.member_by_phone("0912345678").balance == 500

    store.open_room(room.room_id, "Kim", 60)
    cola = store.save_product(Product(0, "Cola", "Drinks", 7))
    store.add_order(room.room_id, [(cola, 1)])
    dialog = BillDialog(bill(store, room.room_id), store=store)
    qtbot.addWidget(dialog)
    assert dialog.bill.total == 107
    dialog.phone.setText("0912345678")
    dialog.find_member()
    assert dialog.bill.total == pytest.approx(96.3)  # members save 10%
    dialog.discount.setValue(10)
    dialog.round_to.setCurrentIndex(1)  # drop the cents
    assert dialog.bill.total == 86
    dialog.payment.setCurrentText("Member balance")
    dialog.settle()
    paid = store.member_by_phone("0912345678")
    assert paid.balance == 500 - 86 and paid.points == 86
    store.close_room(room.room_id, dialog.bill)
    assert store.history(0, time.time() + 1)[0].payment == "Member balance"
    assert "· Member balance</td><td align='right'>$86.00" in shift_report(store)

    poor = BillDialog(
        bill(store, room.room_id) if store.room(room.room_id).is_open else dialog.bill, store=store
    )
    qtbot.addWidget(poor)
    poor.bill.member_off = 0
    poor.phone.setText("0912345678")
    poor.find_member()
    poor.payment.setCurrentText("Member balance")
    poor.discount.setValue(0)
    poor.round_to.setCurrentIndex(0)
    store.pay_from_balance(paid.member_id, store.member_by_phone("0912345678").balance)
    poor.find_member()
    poor.settle()
    assert "Not enough balance" in poor.error.text()


def test_updates_never_mix_up_ytktv_and_the_desk():
    from ytktv import updater

    assets = [
        {"name": "YTKTV-Desk-2.1.0-windows-x64-setup.exe"},
        {"name": "YTKTV-2.1.0-windows-x64-setup.exe"},
        {"name": "SHA256SUMS"},
    ]
    suffixes = ["windows-x64-setup.exe"]
    assert updater.pick_asset(assets, suffixes)["name"] == "YTKTV-2.1.0-windows-x64-setup.exe"
    desk = updater.pick_asset(assets, suffixes, "YTKTV-Desk")
    assert desk["name"] == "YTKTV-Desk-2.1.0-windows-x64-setup.exe"
    assert updater.pick_asset(assets, ["SHA256SUMS"], None)["name"] == "SHA256SUMS"


def test_receipts(qtbot, tmp_path):
    from PySide6.QtPrintSupport import QPrinter

    from ytktv.desk import receipt
    from ytktv.desk.billing import bill
    from ytktv.desk.panels import BillDialog, ReceiptSettings
    from ytktv.desk.store import Product

    store = DeskStore()
    room, _ = store.pair(store.new_code(), "101")
    store.open_room(room.room_id, "Kim", 60)
    cola = store.save_product(Product(0, "可樂", "Drinks", 7))
    store.add_order(room.room_id, [(cola, 2)])
    settings = ReceiptSettings(store)
    qtbot.addWidget(settings)
    settings.paper.setCurrentIndex(1)
    settings.shop.setText("Tony's KTV")
    settings.footer.setText("歡迎再來")
    settings.save()
    assert store.setting("receipt_width") == "80"

    b = bill(store, room.room_id)
    html = receipt.receipt_html(b, "Tony's KTV", "歡迎再來", 80)
    assert (
        "Tony&#x27;s KTV" in html and "可樂 × 2" in html and "TOTAL" in html and "歡迎再來" in html
    )

    printer = receipt.receipt_printer(receipt.ASK, 80)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    printer.setOutputFileName(str(tmp_path / "receipt.pdf"))
    dialog = BillDialog(b, store=store)
    qtbot.addWidget(dialog)
    assert dialog.print_receipt(printer)
    assert (tmp_path / "receipt.pdf").stat().st_size > 0
    from PySide6.QtGui import QPageLayout

    width_mm = printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter).width()
    assert abs(width_mm - 80) < 1


def test_windows_on_arm_gets_an_x64_separation_runtime(tmp_path):
    from ytktv.separation.runtime import VARIANTS, Runtime, runtime_python, supported

    assert supported("Windows", frozen=True, machine="ARM64")
    assert runtime_python("Windows", "ARM64") == "cpython-3.12-windows-x86_64-none"
    assert runtime_python("Windows", "AMD64") == "3.12"
    assert runtime_python("Linux", "aarch64") == "3.12"  # Linux ARM has native libraries
    commands = Runtime(tmp_path, system="Windows").install_commands(VARIANTS["cpu"], "uv")
    assert "--python" in commands[0][1]


def test_low_stock_shows_in_the_service_bar(qtbot):
    from ytktv.desk.server import Hub
    from ytktv.desk.store import Product
    from ytktv.desk.window import DeskWindow

    store = DeskStore()
    store.save_product(Product(0, "Cola", "Drinks", 5, stock=2))
    store.save_product(Product(0, "Chips", "Snacks", 8, stock=40))
    store.save_product(Product(0, "Tea", "Drinks", 6))  # never runs out
    store.save_product(Product(0, "Old", "Drinks", 6, active=False, stock=0))
    assert [p.name for p in store.low_stock()] == ["Cola"]
    window = DeskWindow(store, Hub(), "192.168.1.10:8770")
    qtbot.addWidget(window)
    chips = [window.call_chips.itemAt(i).widget().text() for i in range(window.call_chips.count())]
    assert chips == ["📦 Cola: 2 left"]
    store.set_setting("low_stock", "0")
    assert store.low_stock() == []
