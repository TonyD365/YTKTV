"""The control console on the main display, styled after a KTV song machine."""

from __future__ import annotations

from functools import partial
from typing import Any

from PySide6.QtCore import QDateTime, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeyEvent, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ytktv.core.controller import PITCH_RANGE, SPEEDS, KTVController
from ytktv.core.models import PlayStatus, VocalMode
from ytktv.rooms import binding
from ytktv.rooms.client import RoomClient
from ytktv.rooms.state import WARN_AT, format_left
from ytktv.ui.games_page import GamesPage
from ytktv.ui.home_page import HomePage
from ytktv.ui.level_hud import LevelHud, from_segments, to_segments
from ytktv.ui.mixer_panel import MixerPanel
from ytktv.ui.mv_window import MvWindow
from ytktv.ui.pages import (
    ArtistsPage,
    Context,
    FavoritesPage,
    HistoryPage,
    HotPage,
    Page,
    PlaylistsPage,
    QueuePage,
    SearchPage,
    SettingsPage,
)
from ytktv.ui.party_page import PartyPage
from ytktv.ui.room_closed import RoomClosed
from ytktv.ui.service_dialog import ServiceDialog
from ytktv.ui.support import (
    EventBridge,
    ThumbnailLoader,
    fade,
    fade_in,
    fade_out,
    format_time,
    qr_pixmap,
)
from ytktv.youtube.search import YouTube

NAV = (
    ("home", "⌂  Home"),
    ("search", "Search"),
    ("hot", "Hot Songs"),
    ("artists", "Artists"),
    ("favorites", "Favorites"),
    ("playlists", "Playlists"),
    ("queue", "Selected"),
    ("history", "Sung"),
    ("party", "Party"),
    ("games", "Games"),
    ("mixer", "Mixer"),
    ("settings", "Settings"),
)


_MORE_MODES = "More ▾"
# Vocal modes that work at once, with the label shown on the button when one is active.
_INSTANT_MODES = {
    VocalMode.CENTER_CUT: "Vocal Cut",
    VocalMode.LEFT: "Left Only",
    VocalMode.RIGHT: "Right Only",
}


def _caption(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("caption")
    return label


class MainWindow(QMainWindow):
    def __init__(
        self,
        controller: KTVController,
        youtube: YouTube,
        mv_window: MvWindow,
        server_url: str,
        force_windowed: bool = False,
        room_client: RoomClient | None = None,
    ) -> None:
        super().__init__()
        self.force_windowed = force_windowed
        self.controller = controller
        self.mv_window = mv_window
        self.server_url = server_url
        self.setWindowTitle("YTKTV")
        self.resize(1440, 900)
        self.setMinimumSize(1440, 760)

        self.bridge = EventBridge(controller.bus, self)
        self.bridge.received.connect(self._on_event)
        self.ctx = Context(controller, youtube, ThumbnailLoader(self), room_client=room_client)
        self.ctx.open_search = self.open_search
        self._state: dict[str, Any] = controller.state()
        self._last_current_id: str | None = None
        self._last_status = ""

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        column = QVBoxLayout(root)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self._build_top_bar())
        column.addWidget(self._build_nav())  # the menu runs across the top, under the header
        column.addWidget(self._build_pages(), stretch=1)
        column.addWidget(self._build_control_bar())

        self._root = root
        self._levels: dict[str, int] = {}
        self.level_hud = LevelHud(root)
        self.toast = QLabel(root)
        self.toast.setObjectName("toast")
        self.toast.setTextFormat(Qt.TextFormat.PlainText)
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: fade_out(self.toast))

        self._room_setup(room_client)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._tick_clock)
        self._clock_timer.start(1000)
        self._tick_clock()

        self.mv_window.set_url(server_url)
        self.mv_window.level_source = controller.player.levels
        self._apply_state()

    # -- construction -----------------------------------------------------

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("topBar")
        bar.setFixedHeight(92)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(22, 8, 18, 8)
        layout.setSpacing(24)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        logo = QLabel("YTKTV")
        logo.setObjectName("logo")
        sub = QLabel("KARAOKE SYSTEM")
        sub.setObjectName("logoSub")
        brand.addWidget(logo)
        brand.addWidget(sub)
        layout.addLayout(brand)

        now = QVBoxLayout()
        now.setSpacing(3)
        self.now_caption = _caption("NOW PLAYING")
        self.now_title = QLabel("Pick a song to start the party")
        self.now_title.setObjectName("nowTitle")
        self.now_title.setTextFormat(Qt.TextFormat.PlainText)
        progress_row = QHBoxLayout()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.time_label = QLabel("")
        self.time_label.setObjectName("timeLabel")
        progress_row.addWidget(self.progress, stretch=1)
        progress_row.addWidget(self.time_label)
        now.addWidget(self.now_caption)
        now.addWidget(self.now_title)
        now.addLayout(progress_row)
        layout.addLayout(now, stretch=3)

        upcoming = QVBoxLayout()
        upcoming.setSpacing(3)
        upcoming.addWidget(_caption("UP NEXT"))
        self.next_title = QLabel("-")
        self.next_title.setObjectName("nextTitle")
        self.next_title.setTextFormat(Qt.TextFormat.PlainText)
        upcoming.addWidget(self.next_title)
        upcoming.addStretch()
        layout.addLayout(upcoming, stretch=2)

        qr = QLabel()
        qr.setPixmap(qr_pixmap(self.server_url, 72))
        qr.setToolTip(self.server_url)
        layout.addWidget(qr)
        hint = QVBoxLayout()
        hint.setSpacing(2)
        hint.addWidget(_caption("PHONE REMOTE"))
        address = QLabel(self.server_url.removeprefix("http://"))
        address.setObjectName("qrHint")
        address.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        hint.addWidget(address)
        hint.addStretch()
        layout.addLayout(hint)

        self.time_left = QLabel()
        self.time_left.setObjectName("clock")
        self.time_left.setStyleSheet("color: #ffc94a;")
        self.time_left.hide()
        layout.addWidget(self.time_left)
        self.service_button = QPushButton("🛎  Service")
        self.service_button.setObjectName("accent")
        self.service_button.clicked.connect(self.open_service)
        self.service_button.hide()
        layout.addWidget(self.service_button)
        layout.addSpacing(12)
        self.clock = QLabel()
        self.clock.setObjectName("clock")
        layout.addWidget(self.clock)
        return bar

    def _build_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("navBar")
        nav.setFixedHeight(54)
        layout = QHBoxLayout(nav)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(2)
        self._nav_group = QButtonGroup(self)
        self._nav_buttons: dict[str, QPushButton] = {}
        for key, text in NAV:
            button = QPushButton(text)
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.show_page(k))
            self._nav_group.addButton(button)
            self._nav_buttons[key] = button
            layout.addWidget(button)
        layout.addStretch()
        mv = QPushButton("⛶  MV Full Screen")
        mv.setCheckable(False)
        mv.clicked.connect(self._toggle_mv)
        layout.addWidget(mv)
        return nav

    def _build_pages(self) -> QWidget:
        self.stack = QStackedWidget()
        self.settings_page = SettingsPage(self.ctx, self.server_url)
        self.settings_page.display_changed.connect(self.place_mv)
        self.mixer_page = MixerPanel(self.controller)
        self.pages: dict[str, QWidget] = {
            "home": HomePage(self.ctx, self.show_page),
            "search": SearchPage(self.ctx),
            "hot": HotPage(self.ctx),
            "artists": ArtistsPage(self.ctx),
            "favorites": FavoritesPage(self.ctx),
            "playlists": PlaylistsPage(self.ctx),
            "queue": QueuePage(self.ctx),
            "history": HistoryPage(self.ctx),
            "games": GamesPage(self.ctx),
            "party": PartyPage(self.ctx, self._send_danmaku),
            "mixer": self.mixer_page,
            "settings": self.settings_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.show_page("home")
        return self.stack

    def _build_control_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("controlBar")
        bar.setFixedHeight(104)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 8, 8, 10)
        layout.setSpacing(6)
        controller = self.controller

        def group(title: str, *widgets: QWidget, stretch: int = 0) -> None:
            box = QVBoxLayout()
            box.setSpacing(4)
            label = QLabel(title)
            label.setObjectName("groupLabel")
            box.addWidget(label)
            row = QHBoxLayout()
            row.setSpacing(6)
            for widget in widgets:
                row.addWidget(widget)
            box.addLayout(row)
            layout.addLayout(box, stretch)

        def button(
            text: str, slot: Any, tip: str = "", width: int = 44, **props: Any
        ) -> QPushButton:
            widget = QPushButton(text)
            widget.setFixedSize(width, 44)
            widget.setCursor(Qt.CursorShape.PointingHandCursor)
            widget.setToolTip(tip)
            for name, value in props.items():
                widget.setProperty(name, value)
            widget.clicked.connect(lambda _checked=False: slot())
            return widget

        # Vocals
        self.mode_buttons: dict[VocalMode, QPushButton] = {}
        for mode, text, tip, width in (
            (VocalMode.ORIGINAL, "Original", "Play the song with its original vocals", 76),
            (VocalMode.INSTRUMENTAL, "Instrumental", "Play the AI-separated backing track", 100),
        ):
            widget = button(text, lambda m=mode: self._choose_mode(m), tip, width)
            widget.setCheckable(True)
            self.mode_buttons[mode] = widget
        # The instant modes are used less often, so they share one menu button.
        self.more_modes = QPushButton(_MORE_MODES)
        self.more_modes.setFixedSize(84, 44)
        self.more_modes.setCheckable(True)
        self.more_modes.setCursor(Qt.CursorShape.PointingHandCursor)
        self.more_modes.setToolTip("Vocal modes that need no preparation")
        menu = QMenu(self.more_modes)
        self.mode_actions: dict[VocalMode, QAction] = {}
        for mode, text in _INSTANT_MODES.items():
            action = menu.addAction(text, partial(self._choose_mode, mode))
            action.setCheckable(True)
            self.mode_actions[mode] = action
        self.more_modes.clicked.connect(self._show_more_modes)
        self._more_menu = menu
        group("VOCALS", *self.mode_buttons.values(), self.more_modes)

        # Transport
        self.pause_button = button("⏯", controller.toggle_pause, "Play / Pause", round=True)
        self.score_button = QPushButton("Score")
        self.score_button.setFixedSize(58, 44)
        self.score_button.setCheckable(True)
        self.score_button.setChecked(controller.settings.scoring)
        self.score_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.score_button.setToolTip(
            "Score each song: the microphones are compared with the original singer's melody"
        )
        self.score_button.clicked.connect(controller.set_scoring)
        self.lyrics_button = QPushButton("Lyrics")
        self.lyrics_button.setFixedSize(58, 44)
        self.lyrics_button.setCheckable(True)
        self.lyrics_button.setChecked(controller.settings.show_lyrics)
        self.lyrics_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lyrics_button.clicked.connect(controller.set_show_lyrics)
        self.lyrics_later = button(
            "◂", lambda: controller.nudge_lyrics(-1), "Show the lyrics 0.1 s later", 24
        )
        self.lyrics_earlier = button(
            "▸", lambda: controller.nudge_lyrics(1), "Show the lyrics 0.1 s earlier", 24
        )
        group(
            "PLAYBACK",
            button("⏮", controller.replay, "Replay from the start", round=True),
            self.pause_button,
            button("⏭", controller.skip, "Skip to the next song", round=True),
            self.score_button,
            self.lyrics_later,
            self.lyrics_button,
            self.lyrics_earlier,
        )

        # Key and tempo
        self.key_readout = QLabel("0")
        self.key_readout.setObjectName("readout")
        self.key_readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.key_readout.setFixedWidth(34)
        group(
            "KEY",
            button(
                "♭", lambda: controller.set_pitch(controller.pitch - 1), "Lower the key", round=True
            ),
            self.key_readout,
            button(
                "♯", lambda: controller.set_pitch(controller.pitch + 1), "Raise the key", round=True
            ),
        )
        self.tempo_readout = QLabel("100%")
        self.tempo_readout.setObjectName("readout")
        self.tempo_readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.tempo_readout.setFixedWidth(52)
        group(
            "TEMPO",
            button("−", lambda: self._step_speed(-1), "Slower", round=True),
            self.tempo_readout,
            button("+", lambda: self._step_speed(1), "Faster", round=True),
        )

        # Levels: a minus and a plus key each, like a KTV remote. Every press shows the
        # level on the console and on the MV screen.
        self.level_keys: dict[str, tuple[QPushButton, QPushButton]] = {}
        for name, title, what in (
            ("guide_vocal", "GUIDE", "the original singer in Instrumental mode"),
            ("music_volume", "MUSIC", "the music"),
            ("mic_volume", "MIC", "the microphones"),
        ):
            down = button("−", partial(self._step_level, name, -1), f"Quieter: {what}", 32)
            up = button("+", partial(self._step_level, name, 1), f"Louder: {what}", 32)
            self.level_keys[name] = (down, up)
            group(title, down, up)

        # Crowd
        group(
            "CROWD",
            button("Applause", lambda: self._sfx("applause"), "Applause", 70, gold=True),
            button("Cheer", lambda: self._sfx("cheer"), "Crowd cheer", 54, gold=True),
            button("📣", lambda: self._sfx("airhorn"), "Air horn", round=True),
            button("🥁", lambda: self._sfx("drumroll"), "Drum roll", round=True),
            self._lights_button(),
        )
        return bar

    def _lights_button(self) -> QPushButton:
        self.lights_button = QPushButton("Lights")
        self.lights_button.setFixedSize(56, 44)
        self.lights_button.setCheckable(True)
        self.lights_button.setChecked(self.controller.settings.lights)
        self.lights_button.setToolTip(
            "Light effects around the MV screen that pulse with the music"
        )
        self.lights_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lights_button.clicked.connect(self.controller.set_lights)
        return self.lights_button

    def _send_danmaku(self, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        if self.controller.send_danmaku(text):
            return True
        self.show_toast("Too many messages at once. Try again in a moment.", error=True)
        return False

    def _step_level(self, name: str, steps: int) -> None:
        """Move a level one segment up or down; the display follows from the new state."""
        value = from_segments(to_segments(int(self._state[name])) + steps)
        if name == "guide_vocal":
            self.controller.set_guide_vocal(value)
        else:
            self.controller.set_volume(name.removesuffix("_volume"), value)
        self._show_level(name, value)

    def _show_level(self, name: str, value: int) -> None:
        self.level_hud.setGeometry((self.width() - 480) // 2, self.height() - 104 - 116, 480, 96)
        self.level_hud.show_level(name, value)
        self.mv_window.show_level(name, value)

    # -- actions ----------------------------------------------------------

    def show_page(self, key: str) -> None:
        page = self.pages[key]
        if key != "settings" and self.controller.room_closed:
            self.room_closed_view.cover()
        if self.stack.currentWidget() is not page:
            self.stack.setCurrentWidget(page)
            fade(page, 1.0, 200, start=0.0)
        self._nav_buttons[key].setChecked(True)

    def open_search(self, query: str) -> None:
        self.show_page("search")
        page = self.pages["search"]
        assert isinstance(page, SearchPage)
        page.search_for(query)

    def _show_more_modes(self) -> None:
        # Clicking toggles the check mark; put it back to what the state says.
        self.more_modes.setChecked(self._state["vocal_mode"] in {m.value for m in _INSTANT_MODES})
        # The bar sits at the bottom of the window, so the menu opens upwards.
        above = self.more_modes.mapToGlobal(self.more_modes.rect().topLeft())
        above.setY(above.y() - self._more_menu.sizeHint().height() - 6)
        self._more_menu.exec(above)

    def _choose_mode(self, mode: VocalMode) -> None:
        self.controller.set_vocal_mode(mode)
        if mode == VocalMode.INSTRUMENTAL:
            if not self._state["separation"]:
                self.show_toast("Vocal separation is not installed. See Settings.", error=True)
            elif self._state["current"] and self._state["current"]["stem"] != "ready":
                self.show_toast(
                    "Instrumental is being prepared. It switches automatically when ready."
                )

    def _step_speed(self, direction: int) -> None:
        speeds = list(SPEEDS)
        index = speeds.index(min(speeds, key=lambda s: abs(s - self.controller.speed)))
        self.controller.set_speed(speeds[max(0, min(len(speeds) - 1, index + direction))])

    def _sfx(self, name: str) -> None:
        if not self.controller.play_sfx(name):
            self.show_toast("The mixer is not running. Check the Mixer page.", error=True)

    def _toggle_mv(self) -> None:
        if not self.mv_window.isVisible():
            self.place_mv()
        else:
            self.mv_window.toggle_fullscreen()

    def run_setup(self) -> None:
        """Open the step-by-step setup (first start, or from Settings)."""
        from ytktv.ui.setup_wizard import SetupWizard

        self._setup = SetupWizard(self.controller, self.place_mv, self)
        self._setup.finished.connect(lambda _result: self.mixer_page.refresh_devices())
        self._setup.open()

    def place_mv(self) -> None:
        settings = self.controller.settings
        self.mv_window.place_on_screen(
            settings.mv_screen, settings.mv_fullscreen and not self.force_windowed
        )

    def show_toast(self, message: str, error: bool = False) -> None:
        self.toast.setText(message)
        self.toast.setProperty("error", error)
        self.toast.style().unpolish(self.toast)
        self.toast.style().polish(self.toast)
        self.toast.adjustSize()
        self._place_toast()
        fade_in(self.toast, 160)
        self.toast.raise_()
        self._toast_timer.start(2800)

    def _place_toast(self) -> None:
        parent = self._root
        self.toast.move(
            (parent.width() - self.toast.width()) // 2,
            parent.height() - 104 - self.toast.height() - 18,
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_toast()
        if self.room_closed_view.isVisible():
            self.room_closed_view.cover()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F11:
            if self.isFullScreen():
                self.showNormal()
            else:
                self.showFullScreen()
        else:
            super().keyPressEvent(event)

    # -- state ------------------------------------------------------------

    def _tick_clock(self) -> None:
        self.clock.setText(QDateTime.currentDateTime().toString("HH:mm"))
        self._tick_room()

    # -- front desk -------------------------------------------------------

    def _room_setup(self, room_client: RoomClient | None) -> None:
        self.room_client = room_client
        self._warned = False
        self._times_up_song: str | None = None
        self.room_closed_view = RoomClosed(self)
        self.room_closed_view.open_settings.connect(self._settings_while_closed)
        self.controller.front_desk = room_client
        if room_client is not None:
            room_client.now_singing = lambda: (
                self.controller.current.song.title if self.controller.current else ""
            )
            room_client.on_event = lambda kind, data: self.controller.bus.emit(
                "room", data if isinstance(data, dict) else {"type": kind}
            )
            self.apply_room()

    def open_service(self) -> None:
        if self.room_client is None:
            return
        dialog = ServiceDialog(self.room_client, self)
        if dialog.exec() and dialog.sent:
            self.show_toast(dialog.sent)

    def _on_desk(self, message: dict[str, Any]) -> None:
        """Everything the desk sends has been verified by the room client already."""
        kind = message.get("type")
        if kind == "unbind":
            self.room_closed_view.hide()
        elif kind == "call_done":
            self.show_toast("Staff is on the way")
        elif kind in ("products", "online"):
            self.controller.notify()  # the phone page's menu
        elif kind == "control":
            self._desk_control(str(message.get("action", "")), message.get("value"))
        elif kind == "message":
            self._desk_message(message)
        elif kind == "lock" and self.controller.status == PlayStatus.PLAYING:
            self.controller.toggle_pause()
        self.apply_room()

    def _desk_control(self, action: str, value: Any) -> None:
        if action == "skip":
            self.controller.skip()
        elif action == "pause":
            self.controller.toggle_pause()
        elif action == "volume" and isinstance(value, int):
            self.controller.set_volume("music", max(0, min(100, value)))
            self._show_level("music_volume", max(0, min(100, value)))

    def _desk_message(self, message: dict[str, Any]) -> None:
        """A message or broadcast from the desk, big on the TV and the console."""
        text = str(message.get("text", ""))[:300]
        if not text:
            return
        if message.get("pause") and self.controller.status == PlayStatus.PLAYING:
            self.controller.toggle_pause()
        if message.get("sound"):
            self.controller.play_sfx("drumroll")
        seconds = message.get("seconds")
        self.mv_window.show_game(
            {"title": "📢 From the front desk", "text": text, "detail": ""},
            seconds=float(seconds) if isinstance(seconds, (int, float)) else None,
        )
        if isinstance(seconds, (int, float)):
            self.show_toast(f"Front desk: {text}")
            return
        box = QMessageBox(QMessageBox.Icon.Information, "Front desk", text, parent=self)
        box.addButton("Got it", QMessageBox.ButtonRole.AcceptRole)
        box.finished.connect(lambda _r: self.mv_window.hide_game())
        box.open()

    def _settings_while_closed(self) -> None:
        self.room_closed_view.hide()
        self.show_page("settings")

    def apply_room(self) -> None:
        """Follow the desk: closed rooms show the closed screen, open ones may sing."""
        client = self.room_client
        if client is None:
            return
        closed = client.state.closed
        if closed and not self.controller.room_closed:
            self.controller.close_room()
        elif not closed and self.controller.room_closed:
            self.controller.open_room()
            self._warned = False
            self._times_up_song = None
        locked = client.state.locked and not closed
        self.room_closed_view.message.setText(
            "This room is paused by the front desk" if locked else "This room is closed"
        )
        if (closed or locked) and self.stack.currentWidget() is not self.settings_page:
            self.room_closed_view.cover()
        elif not closed and not locked:
            self.room_closed_view.hide()
        self.mv_window.set_room_closed(closed)
        self.service_button.setVisible(not closed and binding.is_bound(self.controller.settings))
        self._tick_room()

    def _tick_room(self) -> None:
        client = getattr(self, "room_client", None)
        left = client.state.seconds_left() if client is not None else None
        self.time_left.setVisible(left is not None)
        self.mv_window.set_time_left(None if left is None else format_left(left))
        if client is None or left is None:
            return
        self.time_left.setText(f"⏱ {format_left(left)} left")
        if 0 < left <= WARN_AT and not self._warned:
            self._warned = True
            self.show_toast("10 minutes left in this room")
        if left <= 0:
            self._times_up(client)

    def _times_up(self, client: RoomClient) -> None:
        """Let the song that is playing finish, then say so and close the room."""
        current = self.controller.current
        playing = current.song.video_id if current is not None else ""
        if self._times_up_song is None:
            self._times_up_song = playing
        if playing and playing == self._times_up_song:
            return  # still singing the last song
        self.mv_window.show_game(
            {"title": "⏱", "text": "Time's up", "detail": "Thanks for singing!"}
        )
        self.show_toast("Time's up. Thanks for singing!")
        client.state.closed = True
        QTimer.singleShot(5000, self.apply_room)

    def _on_event(self, topic: str, payload: Any) -> None:
        if topic == "state":
            self._state = self.controller.state()
            self._apply_state()
        elif topic == "room":
            self._on_desk(payload)
        elif topic == "position":
            self._apply_position(payload["position"], payload["duration"])
            self.mv_window.set_live_score(payload.get("score"))
        elif topic == "toast":
            self.show_toast(payload["message"], payload.get("error", False))
        elif topic == "favorites":
            for page in self.pages.values():
                if isinstance(page, Page):
                    page.on_favorites()
        elif topic == "searches":
            for page in self.pages.values():
                if isinstance(page, Page):
                    page.on_searches()
        elif topic == "playlists":
            for page in self.pages.values():
                if isinstance(page, Page):
                    page.on_playlists()
        elif topic == "lyrics":
            current = self._state["current"]
            if payload["id"] is None or (current and current["id"] == payload["id"]):
                self.mv_window.set_lyrics(payload["lines"])
        elif topic == "danmaku":
            self.mv_window.add_danmaku(payload["text"])
        elif topic == "reaction":
            self.mv_window.add_reaction(payload["emoji"])
        elif topic == "melody":
            self.mv_window.set_melody(self.controller.melody())
        elif topic == "pitch":
            self.mv_window.add_sung_pitch(payload["position"], payload["note"])
        elif topic == "score":
            self.mv_window.show_score(payload)
            self.show_toast(f"Score: {payload['points']}  ·  {payload['grade']}")
        elif topic == "game":
            self.mv_window.show_game(payload)
        elif topic == "mixer":
            self.mixer_page.apply_state()
        elif topic == "phones":
            self.mixer_page.refresh_devices()  # a phone microphone connected or left

    def _apply_position(self, position: float, duration: float) -> None:
        self.progress.setValue(int(position / duration * 1000) if duration > 0 else 0)
        self.time_label.setText(
            f"{format_time(position)} / {format_time(duration)}" if duration > 0 else ""
        )
        self.mv_window.update_position(position, duration, self._state)

    def _apply_state(self) -> None:
        state = self._state
        current = state["current"]
        status = state["status"]
        captions = {
            "idle": "NOW PLAYING",
            "loading": "LOADING",
            "playing": "NOW PLAYING",
            "paused": "PAUSED",
        }
        self.now_caption.setText((state["loading"] or captions[status]).upper())
        if current:
            singer = f"   ·   {current['singer']}" if current["singer"] else ""
            self.now_title.setText(current["song"]["title"] + singer)
        else:
            self.now_title.setText("Pick a song to start the party")
            self.progress.setValue(0)
            self.time_label.setText("")
        queue = state["queue"]
        self.next_title.setText(queue[0]["song"]["title"] if queue else "-")
        self._nav_buttons["queue"].setText(f"Selected ({len(queue)})" if queue else "Selected")

        for mode, button in self.mode_buttons.items():
            button.setChecked(mode.value == state["vocal_mode"])
        instant = next((m for m in _INSTANT_MODES if m.value == state["vocal_mode"]), None)
        for mode, action in self.mode_actions.items():
            action.setChecked(mode is instant)
        self.more_modes.setChecked(instant is not None)
        self.more_modes.setText(_INSTANT_MODES[instant] if instant else _MORE_MODES)
        pitch = state["pitch"]
        self.key_readout.setText(f"{pitch:+d}" if pitch else "0")
        self.key_readout.setEnabled(abs(pitch) < PITCH_RANGE)
        self.tempo_readout.setText(f"{round(state['speed'] * 100)}%")
        self.lights_button.setChecked(state["lights"])
        self.score_button.setChecked(state["scoring"])
        self.lyrics_button.setChecked(state["show_lyrics"])
        if state["show_lyrics"] and state["current"] and not state["lyrics"]:
            tip = "No lyrics for this song: its video has no subtitles or captions"
        else:
            tip = (
                "Lyrics on the MV screen, from the video's subtitles or, without them, "
                "YouTube's automatic captions (often inaccurate for singing)"
            )
        shift = state["lyrics_offset"]
        if shift:
            tip += (
                f"\nShown {abs(shift):.1f} s {'earlier' if shift > 0 else 'later'} for this song."
            )
        self.lyrics_button.setToolTip(tip)
        self.lyrics_button.setText(f"{shift:+.1f}" if shift else "Lyrics")
        if state["scoring"] and not state["separation"]:
            tip = "Scoring needs vocal separation, which is not installed"
        elif state["scoring"] and state["current"] and not state["scoring_active"]:
            tip = "No score for this song yet: its melody is still being prepared"
        else:
            tip = "Score each song: the microphones are compared with the original singer's melody"
        self.score_button.setToolTip(tip)
        # A level changed somewhere else (a phone, the mixer): show it too.
        for name in ("music_volume", "mic_volume", "guide_vocal"):
            if self._levels.get(name, state[name]) != state[name]:
                self._show_level(name, state[name])
            self._levels[name] = state[name]

        for page in self.pages.values():
            if isinstance(page, Page):
                page.on_state(state)
        self.mixer_page.apply_state()

        self.mv_window.apply_state(state)
        current_id = current["id"] if current else None
        if status == "playing" and (
            current_id != self._last_current_id or self._last_status == "loading"
        ):
            self.mv_window.announce_now_playing(state)
        self._last_current_id = current_id
        self._last_status = status

    def closeEvent(self, event: QCloseEvent) -> None:
        self.bridge.close()
        self.mv_window.close()
        super().closeEvent(event)
