"""Plugins: small Python add-ons that outside developers write for YTKTV.

A plugin is a module (or an installed package) with a ``plugin`` object, or a
``setup(api)`` function. It says what it needs in ``PERMISSIONS`` and gets a
:class:`PluginApi` that only lets it do those things:

* ``events``: hear what happens (songs starting, scores, the queue changing).
* ``themes``: add colour themes to Settings.
* ``songs``: add songs to search results (YouTube video ids or local songs).
* ``toast``: show a short message on the TV.

Plugins are found in two places: installed packages that declare the
``ytktv.plugins`` entry point, and ``.py`` files in the ``plugins`` folder of
the data directory. A plugin never runs until the venue turns it on in
Settings, after it has seen what the plugin asks for. A plugin that fails is
logged and switched off for this session, and the rest of the app keeps going.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from ytktv.core.models import Song

log = logging.getLogger(__name__)

API_VERSION = 1
ENTRY_POINT_GROUP = "ytktv.plugins"
PERMISSIONS: dict[str, str] = {
    "events": "Hear what happens in the room (songs, scores, the queue)",
    "themes": "Add colour themes",
    "songs": "Add songs to search results",
    "toast": "Show short messages on the TV",
}
SEARCH_LIMIT = 20  # songs one plugin may add to one search


class PermissionDenied(Exception):
    """A plugin used something it did not ask for in PERMISSIONS."""


@dataclass
class PluginInfo:
    """A plugin that was found, whether or not it is turned on."""

    key: str  # "entry:<name>" or "file:<name>"
    name: str
    version: str = ""
    description: str = ""
    permissions: list[str] = field(default_factory=list)
    enabled: bool = False
    running: bool = False
    error: str = ""


SongSource = Callable[[str], Iterable[Song]]


class PluginApi:
    """What one plugin may do; each call checks the plugin asked for it."""

    def __init__(self, manager: PluginManager, info: PluginInfo) -> None:
        self._manager = manager
        self._info = info
        self.api_version = API_VERSION
        self.log = logging.getLogger(f"ytktv.plugin.{info.name}")

    @property
    def data_dir(self) -> Path:
        """A folder of the plugin's own for files it keeps."""
        path = self._manager.folder / "data" / _safe(self._info.name)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _need(self, permission: str) -> None:
        if permission not in self._info.permissions:
            raise PermissionDenied(f"{self._info.name} did not ask for {permission!r}")

    def on(self, topic: str, callback: Callable[[Any], None]) -> None:
        """Call ``callback(payload)`` whenever the app emits ``topic`` ("*" for every topic,
        then ``callback(topic, payload)``). Callbacks run on the app's threads: be quick."""
        self._need("events")
        self._manager._listen(self._info, topic, callback)

    def now_playing(self) -> dict[str, Any] | None:
        """The song on screen now (title, channel, video_id, singer), or None."""
        self._need("events")
        current = getattr(self._manager.controller, "current", None)
        if current is None:
            return None
        song = current.song
        return {
            "video_id": song.video_id,
            "title": song.title,
            "channel": song.channel,
            "singer": getattr(current, "singer", ""),
        }

    def add_theme(self, name: str, colours: dict[str, str]) -> None:
        """Add a colour theme; ``colours`` overrides the Neon theme's colours by name."""
        self._need("themes")
        from ytktv.ui import theme

        if name in theme.THEMES and name not in self._manager._themes:
            raise ValueError(f"theme {name!r} already exists")
        merged = dict(theme.NEON)
        for key, value in colours.items():
            if key in merged and theme.valid_accent(value):
                merged[key] = value
        theme.THEMES[name] = merged
        self._manager._themes.add(name)

    def add_song_source(self, search: SongSource) -> None:
        """Add songs to search results: ``search(query)`` returns Songs (run off the GUI thread)."""
        self._need("songs")
        self._manager._sources.append((self._info, search))

    def toast(self, text: str) -> None:
        """Show a short message on the TV."""
        self._need("toast")
        if self._manager.bus is not None:
            self._manager.bus.emit("toast", str(text)[:200])


class PluginManager:
    """Finds plugins, remembers which the venue turned on, and runs those."""

    def __init__(self, folder: Path, bus: Any = None) -> None:
        self.folder = folder
        self.bus = bus
        self.controller: Any = None  # set by the app, for now_playing()
        self.plugins: dict[str, PluginInfo] = {}
        self._loaders: dict[str, Callable[[], Any]] = {}
        self._sources: list[tuple[PluginInfo, SongSource]] = []
        self._listeners: list[tuple[PluginInfo, str, Callable[..., None]]] = []
        self._themes: set[str] = set()
        self._lock = threading.Lock()
        if bus is not None:
            self.attach(bus)

    def attach(self, bus: Any) -> None:
        """Pass the app's events to plugins, and let them show toasts."""
        self.bus = bus
        bus.subscribe(self._on_event)

    # --- what is turned on -------------------------------------------------

    @property
    def _state_file(self) -> Path:
        return self.folder / "plugins.json"

    def _approved(self) -> dict[str, list[str]]:
        """Plugin key -> the permissions the venue agreed to."""
        try:
            data = json.loads(self._state_file.read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        enabled = data.get("enabled", {}) if isinstance(data, dict) else {}
        return {str(k): [str(p) for p in v] for k, v in enabled.items() if isinstance(v, list)}

    def set_enabled(self, key: str, enabled: bool) -> None:
        """Turn a plugin on or off; it takes effect the next time YTKTV starts."""
        approved = self._approved()
        info = self.plugins.get(key)
        if enabled and info is not None:
            approved[key] = list(info.permissions)
        else:
            approved.pop(key, None)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps({"enabled": approved}, indent=2), "utf-8")
        if info is not None:
            info.enabled = enabled

    # --- finding -----------------------------------------------------------

    def discover(self) -> list[PluginInfo]:
        """Find every plugin without running any of them."""
        self.plugins.clear()
        self._loaders.clear()
        try:
            entries = list(metadata.entry_points(group=ENTRY_POINT_GROUP))
        except Exception:
            log.exception("could not list installed plugins")
            entries = []
        for entry in entries:
            # An installed package is imported to read it (the venue chose to pip install it).
            self._found(f"entry:{entry.name}", entry.name, _once(entry.load), _dist_version(entry))
        files = self.folder / "plugins"
        if files.is_dir():
            for path in sorted(files.glob("*.py")):
                if not path.name.startswith("_"):
                    # A dropped-in file is only read, never run, until it is turned on.
                    self._found(f"file:{path.stem}", path.stem, _once(_file_loader(path)), "", path)
        approved = self._approved()
        for info in self.plugins.values():
            agreed = approved.get(info.key)
            # A plugin that now asks for more than the venue agreed to stays off until asked again.
            info.enabled = agreed is not None and set(info.permissions) <= set(agreed)
        return list(self.plugins.values())

    def _found(
        self,
        key: str,
        name: str,
        load: Callable[[], Any],
        version: str,
        source: Path | None = None,
    ) -> None:
        info = PluginInfo(key=key, name=name, version=version)
        try:
            _describe(info, _read_file(source) if source is not None else load())
            self._loaders[key] = load
        except Exception as exc:
            log.warning("plugin %s could not be read: %s", name, exc)
            info.error = f"Could not be read: {exc}"
        self.plugins[key] = info

    # --- running -----------------------------------------------------------

    def start(self) -> None:
        """Run the plugins the venue turned on."""
        for info in self.plugins.values():
            if info.enabled and not info.error and info.key in self._loaders:
                self._start(info)

    def _start(self, info: PluginInfo) -> None:
        try:
            target = self._loaders[info.key]()
        except Exception as exc:
            log.exception("plugin %s could not be loaded", info.name)
            self._fail(info, exc)
            return
        setup = getattr(target, "setup", None)
        if not callable(setup):
            info.error = "Has no setup(api) function"
            return
        try:
            setup(PluginApi(self, info))
            info.running = True
            log.info("plugin %s %s started", info.name, info.version)
        except Exception as exc:
            log.exception("plugin %s failed to start", info.name)
            self._fail(info, exc)

    def _fail(self, info: PluginInfo, exc: BaseException) -> None:
        """Switch a broken plugin off for this session; the app keeps going."""
        info.running = False
        info.error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            self._listeners = [item for item in self._listeners if item[0] is not info]
            self._sources = [item for item in self._sources if item[0] is not info]

    def _listen(self, info: PluginInfo, topic: str, callback: Callable[..., None]) -> None:
        with self._lock:
            self._listeners.append((info, topic, callback))

    def _on_event(self, topic: str, payload: Any) -> None:
        with self._lock:
            listeners = list(self._listeners)
        for info, wanted, callback in listeners:
            if wanted not in (topic, "*"):
                continue
            try:
                if wanted == "*":
                    callback(topic, payload)
                else:
                    callback(payload)
            except Exception as exc:
                log.exception("plugin %s failed on %r", info.name, topic)
                self._fail(info, exc)

    def search(self, query: str) -> list[Song]:
        """Songs the running plugins add for a search (call off the GUI thread)."""
        with self._lock:
            sources = list(self._sources)
        found: list[Song] = []
        for info, source in sources:
            try:
                songs = [s for s in source(query) if isinstance(s, Song)][:SEARCH_LIMIT]
            except Exception as exc:
                log.exception("plugin %s failed to search", info.name)
                self._fail(info, exc)
                continue
            found += songs
        return found


def _describe(info: PluginInfo, target: Any) -> None:
    info.name = str(getattr(target, "NAME", info.name))
    info.version = str(getattr(target, "VERSION", info.version) or "")
    info.description = str(getattr(target, "DESCRIPTION", "") or (target.__doc__ or "")).strip()
    info.description = info.description.splitlines()[0] if info.description else ""
    asked = [str(p) for p in getattr(target, "PERMISSIONS", [])]
    unknown = [p for p in asked if p not in PERMISSIONS]
    if unknown:
        raise ValueError(f"unknown permissions: {', '.join(unknown)}")
    info.permissions = asked
    needed = int(getattr(target, "API_VERSION", API_VERSION))
    if needed > API_VERSION:
        raise ValueError(f"needs plugin API {needed}, this YTKTV has {API_VERSION}")


def _read_file(path: Path) -> Any:
    """A plugin file's NAME, VERSION, PERMISSIONS etc., read without running it."""
    tree = ast.parse(path.read_text("utf-8"), str(path))
    values: dict[str, Any] = {"__doc__": ast.get_docstring(tree)}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id in _META:
                values[target.id] = ast.literal_eval(node.value)
    return SimpleNamespace(**values)


_META = {"NAME", "VERSION", "DESCRIPTION", "PERMISSIONS", "API_VERSION"}


def _once(load: Callable[[], Any]) -> Callable[[], Any]:
    cache: list[Any] = []

    def get() -> Any:
        if not cache:
            cache.append(load())
        return cache[0]

    return get


def _file_loader(path: Path) -> Callable[[], ModuleType]:
    def load() -> ModuleType:
        spec = importlib.util.spec_from_file_location(f"ytktv_plugin_{_safe(path.stem)}", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {path.name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return load


def _dist_version(entry: Any) -> str:
    dist = getattr(entry, "dist", None)
    return str(getattr(dist, "version", "") or "")


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "plugin"
