"""The console's pages: search, hot songs, favourites, queue, history, settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from PySide6.QtCore import QStringListModel, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QCompleter,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ytktv import __version__, catalog
from ytktv.core.controller import KTVController
from ytktv.core.models import Song, StemStatus
from ytktv.rooms.client import RoomClient
from ytktv.ui import feedback, theme
from ytktv.ui.diagnostics_dialog import save_diagnostics
from ytktv.ui.front_desk_card import FrontDeskCard
from ytktv.ui.local_songs_card import LocalSongsCard
from ytktv.ui.remote_keys import key_help
from ytktv.ui.smart_lights_card import SmartLightsCard
from ytktv.ui.song_list import STEM_TAGS, Action, SongList, SongRow, tag
from ytktv.ui.support import ThumbnailLoader, run_async
from ytktv.youtube.search import HOT_CATEGORIES, YouTube


def ask_text(parent: QWidget, title: str, label: str, text: str = "") -> str:
    """A one-line text prompt; returns "" when cancelled or left empty."""
    value, accepted = QInputDialog.getText(parent, title, label, text=text)
    return value.strip() if accepted else ""


@dataclass
class Context:
    controller: KTVController
    youtube: YouTube
    thumbnails: ThumbnailLoader
    # Jump to the Search page and search for this text (set by the main window).
    open_search: Callable[[str], None] = lambda _query: None
    room_client: RoomClient | None = None  # set when the app runs with a staff terminal


# Tags for songs downloaded to keep, by their status.
KEPT_TAGS = {
    "ready": ("Downloaded", "ready"),
    "downloading": ("Downloading", "busy"),
    "waiting": ("Waiting to download", "busy"),
    "failed": ("Download failed", ""),
}


class Page(QWidget):
    def __init__(self, title: str, ctx: Context) -> None:
        super().__init__()
        self.ctx = ctx
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 18, 16, 12)
        self.body.setSpacing(12)
        self.header = QHBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        self.header.addWidget(heading)
        self.header.addStretch()
        self.body.addLayout(self.header)
        self.browse_list: SongList  # set by pages that list songs to pick from
        self._browse_songs: list[Song] = []
        self._browse_marks: Any = None

    def browse_rows(self, songs: list[Song]) -> list[SongRow]:
        """Rows for songs that can be added to the queue."""
        controller = self.ctx.controller
        rows = []
        queued = controller.queued_ids()
        for song in songs:
            favorite = controller.library.is_favorite(song.video_id)
            kept = controller.offline_status(song.video_id)
            actions: list[Action] = [
                ("＋ List", "", partial(self.choose_playlist, song)),
                *self.keep_actions(song, kept),
                ("♥" if favorite else "♡", "", partial(controller.toggle_favorite, song)),
                ("Priority", "", partial(controller.enqueue, song, priority=True)),
                ("Select", "accent", partial(controller.enqueue, song)),
            ]
            tags = []
            if song.video_id in queued:
                tags.append(tag("Selected", "singer"))
            if controller.stem_status(song.video_id) == StemStatus.READY:
                tags.append(tag("Instrumental ready", "ready"))
            if kept in KEPT_TAGS:
                tags.append(tag(*KEPT_TAGS[kept]))
            rows.append(SongRow(song, actions, self.ctx.thumbnails, tags))
        return rows

    def keep_actions(self, song: Song, kept: str) -> list[Action]:
        """The download button, while the song is not kept yet."""
        if kept in ("none", "failed"):
            return [("⬇", "", partial(self.ctx.controller.download_song, song))]
        return []

    def _marks(self, songs: list[Song]) -> tuple[frozenset[Any], ...]:
        """What the tags on these cards depend on; a change means they must be redrawn."""
        controller = self.ctx.controller
        ids = {song.video_id for song in songs}
        ready = {v for v in ids if controller.stem_status(v) == StemStatus.READY}
        kept = {(v, controller.offline_status(v)) for v in ids}
        return frozenset(ids & controller.queued_ids()), frozenset(ready), frozenset(kept)

    def show_songs(self, songs: list[Song], empty: str = "") -> None:
        """Show *songs* in this page's list and keep their tags current from now on."""
        self._browse_songs = list(songs)
        self._browse_marks = self._marks(songs)
        if songs:
            self.browse_list.set_rows(self.browse_rows(songs))
        else:
            self.browse_list.show_message(empty or self.browse_list._empty_text)

    def refresh_songs(self) -> None:
        if self._browse_songs:
            self.show_songs(self._browse_songs)

    def choose_playlist(self, song: Song) -> None:
        """Pop up the playlists at the cursor and add *song* to the chosen one."""
        controller = self.ctx.controller
        menu = QMenu(self)
        for name in controller.library.playlist_names():
            menu.addAction(name, partial(self._add_to_playlist, name, song))
        if controller.library.playlist_names():
            menu.addSeparator()
        menu.addAction("New playlist...", partial(self._add_to_new_playlist, song))
        menu.exec(QCursor.pos())

    def _add_to_playlist(self, name: str, song: Song) -> None:
        if not self.ctx.controller.add_to_playlist(name, song):
            self.ctx.controller.toast(f"Already in {name}")

    def _add_to_new_playlist(self, song: Song) -> None:
        name = ask_text(self, "New playlist", "Name for the new playlist:")
        if name:
            try:
                created = self.ctx.controller.create_playlist(name, [song])
            except ValueError as exc:
                self.ctx.controller.toast(str(exc), error=True)
                return
            self.ctx.controller.toast(f"Created {created}")

    def on_state(self, state: dict[str, Any]) -> None:
        # A song got queued, or its instrumental became ready: update the tags.
        if self._browse_songs and self._marks(self._browse_songs) != self._browse_marks:
            self.refresh_songs()

    def on_playlists(self) -> None:  # noqa: B027 - optional hook
        pass

    def on_searches(self) -> None:  # noqa: B027 - optional hook
        pass

    def on_favorites(self) -> None:
        self.refresh_songs()  # the hearts changed


class SearchPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Search", ctx)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Song title, artist, or paste a YouTube link")
        self.input.setClearButtonEnabled(True)
        self.input.returnPressed.connect(self.search)
        row.addWidget(self.input, stretch=1)
        button = QPushButton("Search")
        button.setProperty("accent", True)
        button.setMinimumHeight(50)
        button.setMinimumWidth(120)
        button.clicked.connect(self.search)
        row.addWidget(button)
        self.body.addLayout(row)

        # Suggestions appear under the box while typing, after a short pause.
        self._suggestions = QStringListModel(self)
        self.completer = QCompleter(self._suggestions, self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        popup = self.completer.popup()
        if popup is not None:
            popup.setObjectName("suggestions")
        self.completer.activated.connect(lambda _text: QTimer.singleShot(0, self.search))
        self.input.setCompleter(self.completer)
        self._typing = QTimer(self)
        self._typing.setSingleShot(True)
        self._typing.setInterval(250)
        self._typing.timeout.connect(self._fetch_suggestions)
        self.input.textEdited.connect(lambda _text: self._typing.start())
        self._suggest_request = 0

        chips = QHBoxLayout()
        chips.setSpacing(8)
        hint = QLabel("Add to search:")
        hint.setObjectName("songSub")
        chips.addWidget(hint)
        for word in ("karaoke", "KTV", "伴奏", "instrumental", "lyrics", "live"):
            chip = QPushButton(word)
            chip.setProperty("chip", True)
            chip.clicked.connect(lambda _checked=False, w=word: self._append(w))
            chips.addWidget(chip)
        chips.addStretch()
        self.body.addLayout(chips)

        self.recent = QHBoxLayout()
        self.recent.setSpacing(8)
        self.body.addLayout(self.recent)

        self.browse_list = SongList("Search YouTube for any song. Every video can be sung.")
        self.body.addWidget(self.browse_list, stretch=1)
        self._request = 0
        self.on_searches()

    def _append(self, word: str) -> None:
        text = self.input.text().strip()
        if word.lower() not in text.lower():
            self.input.setText(f"{text} {word}".strip())
        self.search()

    def _fetch_suggestions(self) -> None:
        text = self.input.text().strip()
        self._suggest_request += 1
        request = self._suggest_request

        # Pinyin initials ("yldb" -> 月亮代表我的心) answer at once, from the song book
        # and from what this room has sung or saved.
        controller = self.ctx.controller
        known = [
            (s.title, s.channel)
            for s in (*controller.library.favorites(), *controller.queue.history())
        ]
        local = catalog.match_initials(text, known)
        if local and self.input.hasFocus():
            self._suggestions.setStringList(local)
            self.completer.complete()

        def done(suggestions: list[str]) -> None:
            # Ignore answers for text that has since changed, or once a search has started.
            if request != self._suggest_request or not self.input.hasFocus():
                return
            combined = local + [s for s in suggestions if s not in local]
            self._suggestions.setStringList(combined)
            if combined:
                self.completer.complete()

        run_async(lambda: self.ctx.youtube.suggest(text), done)

    def on_searches(self) -> None:
        """Rebuild the row of recent searches."""
        while self.recent.count():
            item = self.recent.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        recent = self.ctx.controller.library.searches()[:8]
        if not recent:
            return
        label = QLabel("Recent:")
        label.setObjectName("songSub")
        self.recent.addWidget(label)
        for query in recent:
            chip = QPushButton(query if len(query) <= 22 else query[:21] + "…")
            chip.setProperty("chip", True)
            chip.setToolTip(query)
            chip.clicked.connect(lambda _checked=False, q=query: self.search_for(q))
            self.recent.addWidget(chip)
        clear = QPushButton("Clear")
        clear.setProperty("chip", True)
        clear.setToolTip("Forget the recent searches")
        clear.clicked.connect(self.ctx.controller.clear_searches)
        self.recent.addWidget(clear)
        self.recent.addStretch()

    def search_for(self, query: str) -> None:
        self.input.setText(query)
        self.search()

    def search(self) -> None:
        query = self.input.text().strip()
        if not query:
            return
        self._typing.stop()
        self._suggest_request += 1  # drop suggestions still on their way
        popup = self.completer.popup()
        if popup is not None:
            popup.hide()
        self._request += 1
        request = self._request
        self._browse_songs = []
        self.browse_list.show_message("Searching...")
        self.ctx.controller.remember_search(query)

        controller = self.ctx.controller
        local = controller.local_matches(query)[:20]  # songs from this computer come first

        def done(songs: list[Song]) -> None:
            if request == self._request:
                self.show_songs(local + songs, "No results.")

        def failed(_exc: Exception) -> None:
            if request == self._request and local:
                self.show_songs(local)
            elif request == self._request:
                self.browse_list.show_message(
                    "Search failed. Check the internet connection and try again."
                )

        if controller.local_only:
            self.show_songs(
                local, "No songs on this computer match. This room plays local songs only."
            )
            return
        run_async(lambda: self.ctx.youtube.search(query), done, failed)


class HotPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Hot Songs", ctx)
        grid = QGridLayout()
        grid.setSpacing(8)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for i, name in enumerate(HOT_CATEGORIES):
            chip = QPushButton(name)
            chip.setProperty("chip", True)
            chip.setCheckable(True)
            chip.clicked.connect(lambda _checked=False, n=name: self.load(n))
            self._group.addButton(chip)
            grid.addWidget(chip, i // 5, i % 5)
        self.body.addLayout(grid)
        self.browse_list = SongList("Pick a category.")
        self.body.addWidget(self.browse_list, stretch=1)
        self._request = 0
        self._loaded = False

    def showEvent(self, event: Any) -> None:
        if not self._loaded:
            first = self._group.buttons()[0]
            first.setChecked(True)
            self.load(first.text())
        super().showEvent(event)

    def load(self, category: str) -> None:
        self._loaded = True
        self._request += 1
        request = self._request
        self._browse_songs = []
        self.browse_list.show_message("Loading...")

        def done(songs: list[Song]) -> None:
            if request == self._request:
                self.show_songs(songs, "Nothing found in this category.")

        def failed(_exc: Exception) -> None:
            if request == self._request:
                self.browse_list.show_message("Could not load this category.")

        run_async(lambda: self.ctx.youtube.hot(category), done, failed)


class ArtistsPage(Page):
    """Well-known artists, filtered by language and by male, female or group, like a KTV
    song book; picking one searches for them."""

    def __init__(self, ctx: Context) -> None:
        super().__init__("Artists", ctx)
        self.language, self.kind = "", ""
        self.filters: dict[str, QPushButton] = {}
        for options, attr in (
            (("", *catalog.LANGUAGES), "language"),
            (("", *catalog.KINDS), "kind"),
        ):
            row = QHBoxLayout()
            row.setSpacing(8)
            group = QButtonGroup(self)
            for option in options:
                button = QPushButton(option or "All")
                button.setCheckable(True)
                button.setProperty("chip", True)
                button.setChecked(option == "")
                button.clicked.connect(lambda _c=False, a=attr, o=option: self.filter(a, o))
                group.addButton(button)
                self.filters[f"{attr}:{option}"] = button
                row.addWidget(button)
            row.addStretch()
            self.body.addLayout(row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        self.grid = QGridLayout(holder)
        self.grid.setSpacing(8)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(holder)
        self.body.addWidget(scroll, stretch=1)
        self.buttons: dict[str, QPushButton] = {}
        self.filter("language", "")

    def filter(self, attr: str, option: str) -> None:
        setattr(self, attr, option)
        while self.grid.count():
            item = self.grid.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        self.buttons = {}
        for i, name in enumerate(catalog.artists(self.language, self.kind)):
            button = QPushButton(name)
            button.setMinimumHeight(46)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, n=name: self.ctx.open_search(n))
            self.buttons[name] = button
            self.grid.addWidget(button, i // 4, i % 4)


class FavoritesPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Favorites", ctx)
        self.browse_list = SongList("No favorites yet. Tap ♡ on any song to keep it here.")
        self.body.addWidget(self.browse_list, stretch=1)
        self.on_favorites()

    def on_favorites(self) -> None:
        self.show_songs(self.ctx.controller.library.favorites())


class LocalPage(Page):
    """Songs from video files on this computer (Settings → Local Songs)."""

    def __init__(self, ctx: Context) -> None:
        super().__init__("Local Songs", ctx)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by title or artist")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(lambda _text: self.on_local())
        self.body.addWidget(self.filter)
        self.browse_list = SongList(
            "No local songs yet. Add a folder of video files in Settings → Local Songs."
        )
        self.body.addWidget(self.browse_list, stretch=1)
        self.on_local()

    def on_local(self) -> None:
        self.show_songs(self.ctx.controller.local_matches(self.filter.text()))


class DownloadsPage(Page):
    """Songs kept on this computer: they play, with lyrics and instrumental, offline."""

    def __init__(self, ctx: Context) -> None:
        super().__init__("Downloads", ctx)
        favorites = QPushButton("Download All Favorites")
        favorites.clicked.connect(self.download_favorites)
        self.header.addWidget(favorites)
        self.size_label = QLabel()
        self.size_label.setObjectName("muted")
        self.body.addWidget(self.size_label)
        self.browse_list = SongList(
            "Nothing downloaded yet. Press ⬇ on a song to keep it for singing without internet."
        )
        self.body.addWidget(self.browse_list, stretch=1)
        self.on_offline()

    def keep_actions(self, song: Song, kept: str) -> list[Action]:
        return [("Remove", "", partial(self.ctx.controller.remove_download, song.video_id))]

    def download_favorites(self) -> None:
        controller = self.ctx.controller
        added = sum(controller.download_song(song) for song in controller.library.favorites())
        if not added:
            controller.toast("Every favorite is already downloaded")

    def on_offline(self) -> None:
        offline = self.ctx.controller.offline
        songs = offline.songs() if offline else []
        size = offline.size() / 1e9 if offline else 0.0
        self.size_label.setText(f"{len(songs)} songs · {size:.1f} GB" if songs else "")
        self.show_songs(songs)


class QueuePage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Selected Songs", ctx)
        shuffle = QPushButton("Shuffle")
        shuffle.clicked.connect(ctx.controller.shuffle)
        clear = QPushButton("Clear All")
        clear.setProperty("danger", True)
        clear.clicked.connect(ctx.controller.clear_queue)
        save = QPushButton("Save as Playlist")
        save.clicked.connect(self._save_as_playlist)
        self.header.addWidget(save)
        self.header.addWidget(shuffle)
        self.header.addWidget(clear)
        self.list = SongList("Nothing selected yet. Find a song and press Select.")
        self.list.on_move = ctx.controller.move
        self.body.addWidget(self.list, stretch=1)
        self._signature: Any = None

    def _save_as_playlist(self) -> None:
        name = ask_text(self, "Save as playlist", "Name for the playlist:")
        if not name:
            return
        try:
            created = self.ctx.controller.save_queue_as_playlist(name)
        except ValueError as exc:
            self.ctx.controller.toast(str(exc), error=True)
            return
        self.ctx.controller.toast(f"Saved {created}")

    def on_state(self, state: dict[str, Any]) -> None:
        queue = state["queue"]
        signature = [(item["id"], item["stem"], item["preload"]) for item in queue]
        if signature == self._signature:
            return
        self._signature = signature
        controller = self.ctx.controller
        rows = []
        for i, item in enumerate(queue):
            song = Song.from_dict(item["song"])
            tags = []
            if item["singer"]:
                tags.append(tag(item["singer"], "singer"))
            stem = STEM_TAGS.get(item["stem"])
            if stem:
                tags.append(tag(stem[1], stem[0]))
            if item["preload"] == "ready":
                tags.append(tag("Video ready", "ready"))
            elif item["preload"] == "loading":
                tags.append(tag("Loading video", "busy"))
            actions: list[Action] = [
                ("Top", "", partial(controller.prioritize, item["id"])),
                ("Remove", "danger", partial(controller.remove, item["id"])),
            ]
            rows.append(
                SongRow(
                    song, actions, self.ctx.thumbnails, tags, index=i + 1, key=item["id"], grip=True
                )
            )
        self.list.set_rows(rows)


class PlaylistsPage(Page):
    """Saved playlists: build your own, or import one from YouTube."""

    def __init__(self, ctx: Context) -> None:
        super().__init__("Playlists", ctx)
        controller = ctx.controller
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.picker = QComboBox()
        self.picker.setMinimumWidth(280)
        self.picker.currentIndexChanged.connect(lambda _index: self._show_songs())
        bar.addWidget(self.picker, stretch=1)
        for text, slot, style in (
            ("Play All", lambda: self._enqueue(False), "accent"),
            ("Shuffle Play", lambda: self._enqueue(True), ""),
            ("New", self._new, ""),
            ("Import from YouTube", self._import, ""),
            ("Delete", self._delete, "danger"),
        ):
            button = QPushButton(text)
            if style:
                button.setProperty(style, True)
            button.clicked.connect(lambda _checked=False, s=slot: s())
            bar.addWidget(button)
        self.body.addLayout(bar)
        self.list = SongList(
            'No playlists yet. Press New, use "＋ List" on any song, '
            "or import a playlist from a YouTube link."
        )
        self.body.addWidget(self.list, stretch=1)
        self._controller = controller
        self.on_playlists()

    def on_playlists(self) -> None:
        selected = self.selected()  # keep the same playlist open across refreshes
        names = self._controller.library.playlist_names()
        self.picker.blockSignals(True)
        self.picker.clear()
        for name in names:
            count = len(self._controller.library.playlist(name) or [])
            self.picker.addItem(f"{name}   ({count})", name)
        index = max(0, self.picker.findData(selected)) if names else -1
        self.picker.setCurrentIndex(index)
        self.picker.blockSignals(False)
        self._show_songs()

    def selected(self) -> str:
        data = self.picker.currentData()
        return str(data) if data else ""

    def _show_songs(self) -> None:
        name = self.selected()
        songs = self._controller.library.playlist(name) if name else None
        if not songs:
            self.list.show_message(
                self.list._empty_text
                if not name
                else 'This playlist is empty. Add songs with "＋ List".'
            )
            return
        controller = self._controller
        rows = []
        for i, song in enumerate(songs):
            actions: list[Action] = [
                ("Remove", "danger", partial(controller.remove_from_playlist, name, song.video_id)),
                ("Priority", "", partial(controller.enqueue, song, priority=True)),
                ("Select", "accent", partial(controller.enqueue, song)),
            ]
            rows.append(SongRow(song, actions, self.ctx.thumbnails, index=i + 1))
        self.list.set_rows(rows)

    def _enqueue(self, shuffle: bool) -> None:
        name = self.selected()
        if name:
            self._controller.enqueue_playlist(name, shuffle=shuffle)

    def _new(self) -> None:
        name = ask_text(self, "New playlist", "Name for the new playlist:")
        if not name:
            return
        try:
            created = self._controller.create_playlist(name)
        except ValueError as exc:
            self._controller.toast(str(exc), error=True)
            return
        self.picker.setCurrentIndex(self.picker.findData(created))

    def _delete(self) -> None:
        name = self.selected()
        if not name:
            return
        answer = QMessageBox.question(self, "Delete playlist", f'Delete the playlist "{name}"?')
        if answer == QMessageBox.StandardButton.Yes:
            self._controller.delete_playlist(name)

    def _import(self) -> None:
        url = ask_text(self, "Import from YouTube", "Paste the link of a YouTube playlist:")
        if not url:
            return
        self._controller.toast("Importing the playlist...")

        def done(name: str) -> None:
            self.picker.setCurrentIndex(self.picker.findData(name))

        def failed(exc: Exception) -> None:
            reason = str(exc) if isinstance(exc, ValueError) else "could not read that playlist"
            self._controller.toast(f"Import failed: {reason}", error=True)

        run_async(lambda: self._controller.import_playlist(url), done, failed)


class HistoryPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Sung Songs", ctx)
        self.browse_list = SongList("Songs you have sung will show up here.")
        self.body.addWidget(self.browse_list, stretch=1)
        self._signature: Any = None

    def on_state(self, state: dict[str, Any]) -> None:
        signature = [song["video_id"] for song in state["history"]]
        if signature != self._signature:
            self._signature = signature
            self.show_songs([Song.from_dict(song) for song in state["history"]])
        else:
            super().on_state(state)


class SettingsPage(Page):
    display_changed = Signal()
    check_updates = Signal()
    run_setup = Signal()
    install_update = Signal()
    install_separation = Signal()
    install_hd_unlock = Signal()

    def save_diagnostics(self, path: str | None = None) -> str:
        from dataclasses import asdict

        from ytktv.config import cache_dir

        settings = asdict(self.ctx.controller.settings)
        return save_diagnostics(
            self, "YTKTV", path, settings=settings, files=[cache_dir() / "separator.log"]
        )

    def set_text_size(self, size: str) -> None:
        """Bigger text everywhere on the console, for people who read better large."""
        self.ctx.controller.settings.text_size = size
        self.ctx.controller.store.save()
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(theme.stylesheet(size))

    def __init__(self, ctx: Context, server_url: str) -> None:
        super().__init__("Settings", ctx)
        settings = ctx.controller.settings
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 8, 0)
        column.setSpacing(14)
        scroll.setWidget(holder)
        self.body.addWidget(scroll, stretch=1)

        def card(title: str) -> QVBoxLayout:
            frame = QFrame()
            frame.setObjectName("settingsCard")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(20, 16, 20, 16)
            layout.setSpacing(12)
            head = QLabel(title.upper())
            head.setObjectName("settingsHead")
            layout.addWidget(head)
            column.addWidget(frame)
            return layout

        def labelled(layout: QVBoxLayout, text: str, widget: QWidget) -> None:
            row = QHBoxLayout()
            label = QLabel(text)
            label.setMinimumWidth(190)
            row.addWidget(label)
            row.addWidget(widget, stretch=1)
            layout.addLayout(row)

        def check(
            layout: QVBoxLayout, text: str, attr: str, after: Callable[[], None] | None = None
        ) -> QCheckBox:
            box = QCheckBox(text)
            box.setChecked(bool(getattr(settings, attr)))

            def changed(on: bool) -> None:
                setattr(settings, attr, on)
                ctx.controller.mixer_changed()
                if after:
                    after()

            box.toggled.connect(changed)
            layout.addWidget(box)
            return box

        # MV screen
        display = card("MV Screen")
        self.screen_combo = QComboBox()
        self._fill_screens()
        self.screen_combo.activated.connect(self._screen_chosen)
        labelled(display, "Show the MV on", self.screen_combo)
        check(display, "Full screen on that display", "mv_fullscreen", self.display_changed.emit)
        self.quality = QComboBox()
        for height in (720, 1080, 1440, 2160):
            self.quality.addItem(f"{height}p", height)
        self.quality.setCurrentIndex(max(0, self.quality.findData(settings.max_height)))
        self.quality.activated.connect(self._quality_chosen)
        labelled(display, "Maximum video quality", self.quality)
        check(
            display,
            "Download the next songs in the queue ahead of time (smoother playback)",
            "preload_queue",
        )

        # Vocals
        vocals = card("Vocal Separation")
        self.separation_label = QLabel()
        self.separation_label.setWordWrap(True)
        vocals.addWidget(self.separation_label)
        self.runtime_button = QPushButton()
        self.runtime_button.setProperty("accent", True)
        self.runtime_button.hide()
        self.runtime_button.clicked.connect(self.install_separation.emit)
        button_row = QHBoxLayout()
        button_row.addWidget(self.runtime_button)
        button_row.addStretch()
        vocals.addLayout(button_row)
        self._runtime_text = ""
        check(vocals, "Prepare an instrumental for every selected song", "auto_separate")
        check(
            vocals,
            "Wait for the instrumental before a song starts (no switch in the middle of a song)",
            "wait_for_instrumental",
        )

        # HD unlock for restricted videos
        self.hd_card = card("Restricted Videos")
        self.hd_label = QLabel("Not available in this build.")
        self.hd_label.setWordWrap(True)
        self.hd_card.addWidget(self.hd_label)
        self.hd_button = QPushButton()
        self.hd_button.setProperty("accent", True)
        self.hd_button.hide()
        self.hd_button.clicked.connect(self.install_hd_unlock.emit)
        hd_row = QHBoxLayout()
        hd_row.addWidget(self.hd_button)
        hd_row.addStretch()
        self.hd_card.addLayout(hd_row)

        # Phone
        phone = card("Phone Remote")
        url = QLabel(
            f"Open {server_url} on any phone connected to the same Wi-Fi, or scan the QR code."
        )
        url.setWordWrap(True)
        url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        phone.addWidget(url)

        column.addWidget(FrontDeskCard(ctx.controller.store, ctx.room_client))
        self.local_card = LocalSongsCard(ctx.controller)
        column.addWidget(self.local_card)
        column.addWidget(SmartLightsCard(ctx.controller))

        remote = card("Keyboard and Remote")
        keys = QLabel(
            "<table cellpadding='3'>"
            + "".join(f"<tr><td><b>{k}</b></td><td>{a}</td></tr>" for k, a in key_help())
            + "</table><br>USB and Bluetooth remotes and air mice send these keys too. A TV"
            " remote works through HDMI-CEC on a Raspberry Pi (see the guide)."
        )
        keys.setWordWrap(True)
        remote.addWidget(keys)
        display = card("Text Size")
        self.text_size = QComboBox()
        self.text_size.addItems(list(theme.TEXT_SIZES))
        self.text_size.setCurrentText(ctx.controller.settings.text_size)
        self.text_size.currentTextChanged.connect(self.set_text_size)
        labelled(display, "Text on the console", self.text_size)

        setup = card("Setup")
        again = QPushButton("Run Setup Again")
        again.setToolTip(
            "Choose the sound output, the MV screen and the first microphone step by step"
        )
        again.clicked.connect(self.run_setup.emit)
        setup.addWidget(again, alignment=Qt.AlignmentFlag.AlignLeft)

        help_card = card("Help")
        diagnose = QPushButton("Save Diagnostics…")
        diagnose.setToolTip(
            "One zip with the recent logs, the version and the settings (keys and passwords"
            " left out), to attach to a bug report"
        )
        diagnose.clicked.connect(lambda: self.save_diagnostics())
        feedback_row = QHBoxLayout()
        feedback_row.addWidget(diagnose)
        for caption, link in (("Report a Bug", feedback.BUG), ("Suggest a Feature", feedback.IDEA)):
            button = QPushButton(caption)
            button.clicked.connect(lambda _c=False, u=link: feedback.open_url(u))
            feedback_row.addWidget(button)
        feedback_row.addStretch()
        help_card.addLayout(feedback_row)

        # Updates
        updates = card("Updates")
        self.update_label = QLabel(f"YTKTV {__version__}")
        updates.addWidget(self.update_label)
        check(updates, "Install new releases automatically", "auto_update")
        row = QHBoxLayout()
        check_now = QPushButton("Check Now")
        check_now.clicked.connect(self.check_updates.emit)
        self.release_button = QPushButton("Open Release Page")
        self.release_button.hide()
        self.install_button = QPushButton("Install Now")
        self.install_button.setProperty("accent", True)
        self.install_button.hide()
        self.install_button.clicked.connect(self.install_update.emit)
        row.addWidget(self.install_button)
        row.addWidget(check_now)
        row.addWidget(self.release_button)
        row.addStretch()
        updates.addLayout(row)
        column.addStretch()
        self._release_url = ""
        self.release_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl(self._release_url))
        )

    def _fill_screens(self) -> None:
        self.screen_combo.clear()
        self.screen_combo.addItem("Automatic (extended display)", -1)
        for i, screen in enumerate(QGuiApplication.screens()):
            size = screen.size()
            self.screen_combo.addItem(
                f"Display {i + 1}: {screen.name()} ({size.width()}x{size.height()})", i
            )
        index = self.screen_combo.findData(self.ctx.controller.settings.mv_screen)
        self.screen_combo.setCurrentIndex(max(0, index))

    def _screen_chosen(self, _index: int) -> None:
        self.ctx.controller.settings.mv_screen = int(self.screen_combo.currentData())
        self.ctx.controller.mixer_changed()
        self.display_changed.emit()

    def _quality_chosen(self, _index: int) -> None:
        self.ctx.controller.settings.max_height = int(self.quality.currentData())
        self.ctx.controller.mixer_changed()

    def set_hd_unlock_status(self, text: str, button: str) -> None:
        self.hd_label.setText(text)
        self.hd_button.setText(button)
        self.hd_button.setVisible(bool(button))

    def set_runtime_status(self, text: str, button: str) -> None:
        """Status of the downloadable runtime; empty text means "nothing special to say"."""
        self._runtime_text = text
        self.runtime_button.setText(button)
        self.runtime_button.setVisible(bool(button))
        self.on_state(self.ctx.controller.state())

    def on_state(self, state: dict[str, Any]) -> None:
        if self._runtime_text:
            self.separation_label.setText(self._runtime_text)
        elif state["separation"]:
            device = state["accelerator"] or "detecting hardware..."
            self.separation_label.setText(
                f"Running on: {device}\n"
                "Each selected song is split into vocals and instrumental in the background, "
                "so Original / Instrumental can be switched instantly while it plays."
            )
        else:
            self.separation_label.setText(
                'Not installed. Install it with:  pip install "ytktv[separation]"\n'
                "Until then, Instrumental falls back to the original audio; Vocal Cut still works."
            )

    def set_update_ready(self, ready: bool) -> None:
        self.install_button.setVisible(ready)

    def set_update_status(self, text: str, release_url: str = "") -> None:
        self.update_label.setText(text)
        self._release_url = release_url
        self.release_button.setVisible(bool(release_url))
