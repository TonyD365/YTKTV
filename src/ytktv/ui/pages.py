"""The console's pages: search, hot songs, favourites, queue, history, settings."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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

from ytktv import __version__
from ytktv.core.controller import KTVController
from ytktv.core.models import Song
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

    def browse_rows(self, songs: list[Song]) -> list[SongRow]:
        """Rows for songs that can be added to the queue."""
        controller = self.ctx.controller
        rows = []
        for song in songs:
            favorite = controller.library.is_favorite(song.video_id)
            actions: list[Action] = [
                ("＋ List", "", partial(self.choose_playlist, song)),
                ("♥" if favorite else "♡", "", partial(controller.toggle_favorite, song)),
                ("Priority", "", partial(controller.enqueue, song, priority=True)),
                ("Select", "accent", partial(controller.enqueue, song)),
            ]
            rows.append(SongRow(song, actions, self.ctx.thumbnails))
        return rows

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

    def on_state(self, state: dict[str, Any]) -> None:  # noqa: B027 - optional hook
        pass

    def on_playlists(self) -> None:  # noqa: B027 - optional hook
        pass

    def on_favorites(self) -> None:  # noqa: B027 - optional hook
        pass


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

        self.list = SongList("Search YouTube for any song. Every video can be sung.")
        self.body.addWidget(self.list, stretch=1)
        self._songs: list[Song] = []
        self._request = 0

    def _append(self, word: str) -> None:
        text = self.input.text().strip()
        if word.lower() not in text.lower():
            self.input.setText(f"{text} {word}".strip())
        self.search()

    def search(self) -> None:
        query = self.input.text().strip()
        if not query:
            return
        self._request += 1
        request = self._request
        self.list.show_message("Searching...")

        def done(songs: list[Song]) -> None:
            if request == self._request:
                self._songs = songs
                self._render()

        def failed(_exc: Exception) -> None:
            if request == self._request:
                self.list.show_message(
                    "Search failed. Check the internet connection and try again."
                )

        run_async(lambda: self.ctx.youtube.search(query), done, failed)

    def _render(self) -> None:
        if self._songs:
            self.list.set_rows(self.browse_rows(self._songs))
        else:
            self.list.show_message("No results.")

    def on_favorites(self) -> None:
        if self._songs:
            self._render()


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
        self.list = SongList("Pick a category.")
        self.body.addWidget(self.list, stretch=1)
        self._songs: list[Song] = []
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
        self.list.show_message("Loading...")

        def done(songs: list[Song]) -> None:
            if request == self._request:
                self._songs = songs
                self.list.set_rows(self.browse_rows(songs))

        def failed(_exc: Exception) -> None:
            if request == self._request:
                self.list.show_message("Could not load this category.")

        run_async(lambda: self.ctx.youtube.hot(category), done, failed)

    def on_favorites(self) -> None:
        if self._songs:
            self.list.set_rows(self.browse_rows(self._songs))


class FavoritesPage(Page):
    def __init__(self, ctx: Context) -> None:
        super().__init__("Favorites", ctx)
        self.list = SongList("No favorites yet. Tap ♡ on any song to keep it here.")
        self.body.addWidget(self.list, stretch=1)
        self.on_favorites()

    def on_favorites(self) -> None:
        self.list.set_rows(self.browse_rows(self.ctx.controller.library.favorites()))


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
            rows.append(SongRow(song, actions, self.ctx.thumbnails, tags, index=i + 1))
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
        self.list = SongList("Songs you have sung will show up here.")
        self.body.addWidget(self.list, stretch=1)
        self._signature: Any = None
        self._songs: list[Song] = []

    def on_state(self, state: dict[str, Any]) -> None:
        signature = [song["video_id"] for song in state["history"]]
        if signature == self._signature:
            return
        self._signature = signature
        self._songs = [Song.from_dict(song) for song in state["history"]]
        self.list.set_rows(self.browse_rows(self._songs))

    def on_favorites(self) -> None:
        self.list.set_rows(self.browse_rows(self._songs))


class SettingsPage(Page):
    display_changed = Signal()
    check_updates = Signal()
    install_update = Signal()
    install_separation = Signal()
    install_hd_unlock = Signal()

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
        check(display, "Show the video's subtitles as karaoke lyrics", "show_lyrics")
        check(
            display,
            "Use auto-generated captions when a video has no subtitles (often inaccurate)",
            "lyrics_auto_captions",
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
