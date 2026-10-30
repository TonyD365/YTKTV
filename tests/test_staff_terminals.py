"""Several Desks on one: pairing a staff terminal, working through it, and the log."""

from __future__ import annotations

import socket
import time
from typing import cast

import pytest

from ytktv.desk import remote, staff
from ytktv.desk.billing import Bill
from ytktv.desk.server import Hub, create_desk_app
from ytktv.desk.store import DeskStore, Product
from ytktv.server.app import ServerThread
from ytktv.server.tls import ensure_certificate


@pytest.fixture
def main_desk(tmp_path):
    certificate = ensure_certificate(tmp_path / "tls", "127.0.0.1")
    store = DeskStore(tmp_path / "desk.sqlite3")
    store.set_setting(staff.SERVER_SETTING, "1")
    store.set_setting(staff.NAME_SETTING, "Counter")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    app = create_desk_app(store, Hub(), staff.certificate_hash(certificate[0]))
    server = ServerThread(app, port, host="127.0.0.1", certificate=certificate)
    server.start()
    deadline = time.monotonic() + 10
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
            break
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.1)
    yield store, f"127.0.0.1:{port}", server
    server.stop()


def test_a_terminal_works_on_the_main_desk_and_is_logged(main_desk, tmp_path):
    store, address, _server = main_desk
    with pytest.raises(remote.NotPaired):
        remote.pair(address, "000000", "Bar")
    config = remote.pair(address, store.new_terminal_code(), "Bar")
    assert config.fingerprint == store.fingerprint and config.main_name == "Counter"
    remote.save_config(config, tmp_path / "terminal.json")
    assert remote.load_config(tmp_path / "terminal.json") == config

    main = remote.MainDesk(config)
    terminal = remote.RemoteStore(main)
    room, _key = store.pair(store.new_code(), "Kids")
    store.save_product(Product(0, "Cola", "Drinks", 5, stock=9))
    assert [r.name for r in terminal.rooms()] == ["Kids"]
    terminal.open_room(room.room_id, "Kim", 60)
    product = terminal.products()[0]
    assert isinstance(product, Product) and product.name == "Cola"
    terminal.add_order(room.room_id, [(product.product_id, 2)])
    bill = Bill("Kids", "Kim", "$", [("Room", 10.0)], payment="Card")
    terminal.close_room(room.room_id, bill)
    assert not store.room(room.room_id).is_open
    assert terminal.history(0, time.time() + 1)[0].payment == "Card"
    assert remote.RemoteHub(main).online() == set()
    with pytest.raises(AttributeError):
        _ = terminal.pair  # pairing rooms stays on the main Desk

    actions = [(e.machine, e.action) for e in store.oplog(0, time.time() + 1)][::-1]
    assert actions[0] == ("Bar", "Paired as a staff terminal")
    assert ("Bar", "Opened Kids for Kim (60 min)") in actions
    assert ("Bar", "Added 2 × Cola to Kids") in actions
    assert ("Bar", "Closed Kids, $10.00 by Card") in actions

    # Removed on the main Desk: the terminal is refused from then on.
    store.remove_terminal(store.terminals()[0].terminal_id)
    with pytest.raises(remote.NotPaired):
        terminal.rooms()
    main.close()


def test_the_main_desk_can_stop_serving_and_a_stranger_is_caught(main_desk):
    store, address, _server = main_desk
    config = remote.pair(address, store.new_terminal_code(), "Bar")
    store.set_setting(staff.SERVER_SETTING, "0")
    with pytest.raises(remote.NotPaired, match="does not accept"):
        remote.RemoteStore(remote.MainDesk(config)).rooms()
    store.set_setting(staff.SERVER_SETTING, "1")

    # A Desk with another key at the same address is not the one this terminal paired with.
    impostor = remote.TerminalConfig(**{**config.__dict__, "desk_key": "00" * 32})
    with pytest.raises(remote.DeskOffline):
        remote.MainDesk(impostor).call("store", "rooms")


def test_offline_main_desk_fails_fast_and_comes_back(main_desk, monkeypatch):
    store, address, server = main_desk
    config = remote.pair(address, store.new_terminal_code(), "Bar")
    monkeypatch.setattr(remote.discovery, "find", lambda *_a, **_k: None)
    monkeypatch.setattr(remote, "RETRY_AFTER", 0.2)
    main = remote.MainDesk(config)
    main.online = False  # as after a failed call
    began = time.monotonic()
    with pytest.raises(remote.DeskOffline):
        main.call("store", "rooms")
    assert time.monotonic() - began < 0.5
    main._went_offline()
    deadline = time.monotonic() + 5
    while not main.online and time.monotonic() < deadline:
        time.sleep(0.05)
    assert main.call("store", "rooms") == []
    main.close()


def test_logged_store_on_the_main_desk_keeps_secrets_out():
    store = DeskStore()
    logged = cast(DeskStore, staff.LoggedStore(store, lambda: "Counter"))
    logged.set_setting("password_hash", "abc")
    logged.set_setting("currency", "¥")
    hub = staff.LoggedHub(Hub(), store, lambda: "Counter")
    room, _ = store.pair(store.new_code(), "Kids")
    hub.send_soon(room.room_id, {"type": "control", "action": "skip", "value": None})
    hub.send_soon(room.room_id, {"type": "products", "items": []})  # routine: not logged
    actions = [e.action for e in store.oplog(0, time.time() + 1)][::-1]
    assert actions == ["Changed the setting password_hash", "Set currency to ¥", "Skip in Kids"]


def test_terminal_window_settings_and_log(main_desk, qtbot, tmp_path, monkeypatch):
    from ytktv.desk import terminals
    from ytktv.desk.window import DeskWindow

    store, address, _server = main_desk
    monkeypatch.setattr(remote, "config_path", lambda: tmp_path / "terminal.json")
    monkeypatch.setattr(terminals.discovery, "browse", lambda _seconds: [])  # no real network

    # On the main Desk: name it, add a terminal, see it listed.
    logged = cast(DeskStore, staff.LoggedStore(store, lambda: staff.machine_name(store)))
    main_window = DeskWindow(logged, Hub(), address)
    qtbot.addWidget(main_window)
    panel = main_window.terminals
    assert panel.serving.isChecked() and panel.add_button.isEnabled()
    code = panel.add_terminal(show=False)

    # Another Desk joins with that code, after comparing the pictures.
    dialog = terminals.ConnectDialog()
    qtbot.addWidget(dialog)
    dialog.address.setText(address)
    dialog.code.setText(code)
    dialog.name.setText("Bar")
    seen: list[str] = []
    dialog.join(confirm=lambda config: seen.append(config.fingerprint) or True)
    # TLS on a busy Windows CI machine can take a while; wait long enough not to flake.
    qtbot.waitUntil(lambda: remote.load_config() is not None, timeout=30000)
    assert seen == [store.fingerprint]
    panel.load()
    assert panel.list.count() == 1 and panel.list.item(0).text().startswith("Bar")

    # The terminal's window works on the main Desk's rooms.
    room, _ = store.pair(store.new_code(), "Kids")
    main = remote.MainDesk(remote.load_config())
    window = DeskWindow(
        cast(DeskStore, remote.RemoteStore(main)), cast(Hub, remote.RemoteHub(main)),
        "the main Desk", terminal=main,
    )  # fmt: skip
    qtbot.addWidget(window)
    window.select(room.room_id)
    window.open_room(guest="Kim", length="1 hour")
    assert store.room(room.room_id).is_open
    assert window.terminals.name.text() == "Bar"
    main_window.show_tab(main_window.stack.indexOf(main_window.log_page))
    page = main_window.log_page
    rows = [page.table.item(r, 1).text() + ": " + page.table.item(r, 2).text()
            for r in range(page.table.rowCount())]  # fmt: skip
    assert "Bar: Opened Kids for Kim (60 min)" in rows

    # The main Desk goes away: the terminal says so instead of failing.
    main.online = False
    window.refresh()
    assert not window.offline_label.isHidden()
    window.terminals.leave(confirm=False)
    assert remote.load_config() is None
    main.close()


def test_phone_staff_page_pairs_and_checks_out(main_desk):
    store, address, _server = main_desk
    connection, _cert = remote._connect(address)
    connection.request("GET", "/staff")
    page = connection.getresponse().read().decode()
    assert "YTKTV STAFF" in page and "/api/staff/call" in page
    reply = remote._post(
        connection,
        "/api/staff/pair",
        {"code": store.new_terminal_code(), "name": "Amy", "nonce": "ab"},
    )
    token = reply["token"]

    def phone(target, method, *args):
        body = {"target": target, "method": method, "args": list(args)}
        return remote._post(connection, "/api/staff/call", body, token)["result"]

    room, _ = store.pair(store.new_code(), "Kids")
    phone("store", "open_room", room.room_id, "Kim", 60)
    phone("terminal", "tell", room.room_id)
    assert store.room(room.room_id).is_open
    paid = phone("terminal", "checkout", room.room_id, "Alipay")
    assert paid["payment"] == "Alipay" and paid["total"] > 0
    assert not store.room(room.room_id).is_open
    assert store.history(0, time.time() + 1)[0].payment == "Alipay"
    actions = [e.action for e in store.oplog(0, time.time() + 1) if e.machine == "Amy"]
    assert any(a.startswith("Closed Kids") for a in actions)
    connection.close()
