"""Server Mode: the main Desk's computer shows a server console instead of the front desk."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

from ytktv.desk import awake, lock, remote, staff
from ytktv.desk.console import ConsoleSettings, ServerConsole, enter_server_mode
from ytktv.desk.metrics import Metrics, uptime_text
from ytktv.desk.server import Hub, create_desk_app
from ytktv.desk.store import DeskStore

from .test_staff_terminals import main_desk  # noqa: F401 - the running main Desk fixture


@pytest.fixture
def console(qapp, tmp_path):
    store = DeskStore(tmp_path / "desk.sqlite3")
    store.set_setting(staff.NAME_SETTING, "Server")
    window = ServerConsole(store, Hub(), Metrics(), "127.0.0.1:8770")
    window.confirm_close = False
    yield window
    # Delete it here, on the GUI thread. Left to Python's garbage collector it can be
    # deleted later from another thread (the test server's), which crashes Qt.
    window.close()
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_metrics_count_requests_and_errors():
    now = [1000.0]
    metrics = Metrics(clock=lambda: now[0])
    app = create_desk_app(DeskStore(), Hub(), metrics=metrics)
    client = TestClient(app)
    assert client.get("/api/desk").status_code == 200
    assert client.post("/api/pair", json={"code": "000000"}).status_code == 403
    assert metrics.per_minute() == 2 and metrics.errors_last_hour() == 1
    now[0] += 120
    assert metrics.per_minute() == 0 and metrics.errors_last_hour() == 1
    now[0] += 3600
    assert metrics.errors_last_hour() == 0
    assert uptime_text(90061) == "1d 1h 01m"


def test_entering_server_mode_needs_the_password(qapp, tmp_path):
    store = DeskStore(tmp_path / "desk.sqlite3")
    lock.set_password(store, "1234")
    assert not enter_server_mode(None, store, password="wrong", confirm=False)
    assert store.setting(staff.SERVER_MODE_SETTING, "0") == "0"
    assert enter_server_mode(None, store, password="1234", confirm=False)
    assert store.setting(staff.SERVER_MODE_SETTING) == "1"
    assert store.setting(staff.SERVER_SETTING) == "1"  # terminals may connect
    reopened = DeskStore(tmp_path / "desk.sqlite3")  # kept across restarts
    assert reopened.setting(staff.SERVER_MODE_SETTING) == "1"


def test_leaving_server_mode_needs_the_password(console):
    store = console.store
    store.set_setting(staff.SERVER_MODE_SETTING, "1")
    lock.set_password(store, "1234")
    assert not console.leave(password="nope", confirm=False)
    assert store.setting(staff.SERVER_MODE_SETTING) == "1"
    assert console.leave(password="1234", confirm=False)
    assert store.setting(staff.SERVER_MODE_SETTING) == "0"


def test_the_console_shows_rooms_terminals_and_the_log(console, tmp_path):
    store = console.store
    store.pair(store.new_code(), "Big Room")
    small, _ = store.pair(store.new_code(), "Small Room")
    console.hub.channels[small.room_id] = object()  # type: ignore[assignment]
    terminal_id, token = store.pair_terminal(store.new_terminal_code(), "Bar")
    assert store.terminal_by_token(token) is not None  # seen just now
    store.log("Bar", "Opened Small Room")
    console.metrics.event("room", "Small Room connected")
    console.refresh()
    assert console.values["rooms"].text() == "1 / 2"
    assert "Big Room" in console.details["rooms"].text()
    assert console.values["terminals"].text() == "1 / 1"
    assert "Bar" in console.details["terminals"].text()
    lines = [console.log.item(i).text() for i in range(console.log.count())]
    assert any("Bar: Opened Small Room" in line for line in lines)
    assert any("Small Room connected" in line for line in lines)
    console.filter.setCurrentText("Rooms")
    lines = [console.log.item(i).text() for i in range(console.log.count())]
    assert lines and all("ROOM" in line for line in lines)
    out = tmp_path / "log.csv"
    console.export_log(str(out))
    assert "Small Room connected" in out.read_text(encoding="utf-8-sig")


def test_back_up_now_copies_every_record(console, tmp_path):
    console.store.set_setting("currency", "€")
    copy = console.backup_now(tmp_path / "backups")
    with sqlite3.connect(copy) as db:
        assert db.execute("SELECT v FROM meta WHERE k='set:currency'").fetchone() == ("€",)


def test_settings_rename_and_start_at_login(console, monkeypatch):
    calls = []
    monkeypatch.setattr(awake, "starts_at_login", lambda: False)
    dialog = ConsoleSettings(console, start_at_login=calls.append)
    dialog.name.setText("Back Office")
    dialog.autostart.setChecked(True)
    dialog.save()
    assert staff.machine_name(console.store) == "Back Office" and calls == [True]


def test_start_at_login_files(tmp_path):
    for platform in ("darwin", "linux"):
        awake.start_at_login(True, tmp_path, platform)
        assert awake.starts_at_login(tmp_path, platform)
        awake.start_at_login(False, tmp_path, platform)
        assert not awake.starts_at_login(tmp_path, platform)


def test_terminals_work_while_the_main_desk_is_in_server_mode(main_desk, tmp_path):  # noqa: F811
    store, address, _server = main_desk
    store.set_setting(staff.SERVER_MODE_SETTING, "1")
    config = remote.pair(address, store.new_terminal_code(), "Bar")
    terminal = remote.RemoteStore(remote.MainDesk(config))
    terminal.set_setting("currency", "£")
    assert store.setting("currency") == "£"
    assert any(e.machine == "Bar" for e in store.oplog(0, 2**40))
