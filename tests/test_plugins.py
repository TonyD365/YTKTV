from __future__ import annotations

from pathlib import Path

from ytktv.core.events import EventBus
from ytktv.core.models import Song
from ytktv.plugins import PluginManager
from ytktv.ui import theme

GOOD = '''"""Adds songs and listens."""
NAME = "Good"
VERSION = "2.0"
PERMISSIONS = ["events", "songs", "toast"]
heard = []

def setup(api):
    from ytktv.core.models import Song
    api.on("score", heard.append)
    api.add_song_source(lambda q: [Song("abcdefghijk", f"{q} hit")])
'''


def write(folder: Path, name: str, text: str) -> None:
    (folder / "plugins").mkdir(parents=True, exist_ok=True)
    (folder / "plugins" / f"{name}.py").write_text(text, "utf-8")


def test_found_but_not_run_until_turned_on(tmp_path: Path) -> None:
    write(tmp_path, "boom", 'NAME = "Boom"\nPERMISSIONS = []\nraise SystemExit("ran!")\n')
    manager = PluginManager(tmp_path)
    [info] = manager.discover()
    assert info.name == "Boom" and not info.enabled and not info.error
    manager.start()  # off, so its code never runs
    assert not info.running


def test_turned_on_plugin_runs_and_adds_songs(tmp_path: Path) -> None:
    write(tmp_path, "good", GOOD)
    bus = EventBus()
    manager = PluginManager(tmp_path, bus)
    manager.discover()
    manager.set_enabled("file:good", True)
    manager.discover()
    manager.start()
    info = manager.plugins["file:good"]
    assert info.running and info.version == "2.0" and info.description == "Adds songs and listens."
    assert [s.title for s in manager.search("abc")] == ["abc hit"]
    bus.emit("score", 95)


def test_asking_for_more_turns_it_off_again(tmp_path: Path) -> None:
    write(tmp_path, "good", 'PERMISSIONS = ["events"]\ndef setup(api): pass\n')
    manager = PluginManager(tmp_path)
    manager.discover()
    manager.set_enabled("file:good", True)
    write(tmp_path, "good", 'PERMISSIONS = ["events", "songs"]\ndef setup(api): pass\n')
    [info] = manager.discover()
    assert not info.enabled


def test_permission_is_checked(tmp_path: Path) -> None:
    write(tmp_path, "sneaky", 'PERMISSIONS = []\ndef setup(api): api.add_theme("X", {})\n')
    manager = PluginManager(tmp_path)
    manager.discover()
    manager.set_enabled("file:sneaky", True)
    manager.start()
    info = manager.plugins["file:sneaky"]
    assert not info.running and "PermissionDenied" in info.error
    assert "X" not in theme.THEMES


def test_broken_listener_is_switched_off(tmp_path: Path) -> None:
    write(
        tmp_path,
        "bad",
        'PERMISSIONS = ["events", "songs"]\n'
        "def setup(api):\n"
        "    api.on('*', lambda t, p: 1 / 0)\n"
        "    api.add_song_source(lambda q: [])\n",
    )
    bus = EventBus()
    manager = PluginManager(tmp_path, bus)
    manager.discover()
    manager.set_enabled("file:bad", True)
    manager.start()
    bus.emit("state", None)  # must not raise
    info = manager.plugins["file:bad"]
    assert not info.running and "ZeroDivisionError" in info.error
    assert manager.search("x") == []


def test_unknown_permission_is_an_error(tmp_path: Path) -> None:
    write(tmp_path, "odd", 'PERMISSIONS = ["root"]\ndef setup(api): pass\n')
    [info] = PluginManager(tmp_path).discover()
    assert "unknown permissions" in info.error


def test_theme_and_toast(tmp_path: Path) -> None:
    example = Path(__file__).parents[1] / "examples" / "plugins" / "hello_plugin.py"
    write(tmp_path, "hello", example.read_text("utf-8"))
    bus = EventBus()
    toasts: list[object] = []
    bus.subscribe(lambda topic, payload: toasts.append(payload) if topic == "toast" else None)
    manager = PluginManager(tmp_path, bus)

    class Current:
        song = Song("abcdefghijk", "Yellow")
        singer = "Ann"

    class Controller:
        current = Current()

    manager.controller = Controller()
    manager.discover()
    manager.set_enabled("file:hello", True)
    manager.start()
    try:
        assert theme.THEMES["Sunset"]["PINK"] == "#ff7a45"
        bus.emit("state", None)
        bus.emit("state", None)
        assert toasts == ["Now singing: Yellow"]
    finally:
        theme.THEMES.pop("Sunset", None)
