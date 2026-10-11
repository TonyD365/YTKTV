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
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ytktv.core.controller import PITCH_RANGE, SPEEDS, KTVController
from ytktv.core.models import VocalMode
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
    ("search", "🔍   Search"),
    ("hot", "🔥   Hot Songs"),
    ("artists", "★   Artists"),
    ("favorites", "♥   Favorites"),
    ("playlists", "≡   Playlists"),
    ("queue", "🎤   Selected"),
    ("history", "✓   Sung"),
    ("mixer", "🎚   Mixer"),
    ("settings", "⚙   Settings"),
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
        self.ctx = Context(controller, youtube, ThumbnailLoader(self))
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
        middle = QHBoxLayout()
        middle.setSpacing(0)
        middle.addWidget(self._build_nav())
        middle.addWidget(self._build_pages(), stretch=1)
        column.addLayout(middle, stretch=1)
        column.addWidget(self._build_control_bar())

        self._root = root
        self.toast = QLabel(root)
        self.toast.setObjectName("toast")
        self.toast.setTextFormat(Qt.TextFormat.PlainText)
        self.toast.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.timeout.connect(lambda: fade_out(self.toast))

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

        self.clock = QLabel()
        self.clock.setObjectName("clock")
        layout.addWidget(self.clock)
        return bar

    def _build_nav(self) -> QWidget:
        nav = QFrame()
        nav.setObjectName("navBar")
        nav.setFixedWidth(188)
        layout = QVBoxLayout(nav)
        layout.setContentsMargins(0, 14, 0, 14)
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
        box = QVBoxLayout()
        box.setContentsMargins(12, 0, 12, 8)
        box.setSpacing(6)
        box.addWidget(_caption("DANMAKU"))
        self.danmaku_input = QLineEdit()
        self.danmaku_input.setPlaceholderText("Say something...")
        self.danmaku_input.setMaxLength(60)
        self.danmaku_input.setStyleSheet("font-size: 13px; padding: 8px 10px; border-radius: 10px;")
        self.danmaku_input.setToolTip("Send a message that flies across the MV screen")
        self.danmaku_input.returnPressed.connect(self._send_danmaku)
        box.addWidget(self.danmaku_input)
        layout.addLayout(box)
        mv = QPushButton("⛶   MV Full Screen")
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
            "search": SearchPage(self.ctx),
            "hot": HotPage(self.ctx),
            "artists": ArtistsPage(self.ctx),
            "favorites": FavoritesPage(self.ctx),
            "playlists": PlaylistsPage(self.ctx),
            "queue": QueuePage(self.ctx),
            "history": HistoryPage(self.ctx),
            "mixer": self.mixer_page,
            "settings": self.settings_page,
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        self.show_page("search")
        return self.stack

    def _build_control_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("controlBar")
        bar.setFixedHeight(104)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(14, 8, 14, 10)
        layout.setSpacing(10)
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
        self.more_modes.setFixedSize(92, 44)
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
        group(
            "PLAYBACK",
            button("⏮", controller.replay, "Replay from the start", round=True),
            self.pause_button,
            button("⏭", controller.skip, "Skip to the next song", round=True),
            self.score_button,
            self.lyrics_button,
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

        # Volumes
        self.music_slider = self._volume_slider("music")
        self.mic_slider = self._volume_slider("mic")
        self.guide_slider = QSlider(Qt.Orientation.Horizontal)
        self.guide_slider.setRange(0, 100)
        self.guide_slider.setMinimumWidth(64)
        self.guide_slider.setValue(controller.settings.guide_vocal)
        self.guide_slider.setToolTip(
            "Guide vocal: how much of the original singer stays audible in Instrumental mode"
        )
        self.guide_slider.valueChanged.connect(controller.set_guide_vocal)
        group("GUIDE", self.guide_slider, stretch=1)
        group("MUSIC", self.music_slider, stretch=1)
        group("MIC", self.mic_slider, stretch=1)

        # Crowd
        group(
            "CROWD",
            button("Applause", lambda: self._sfx("applause"), "Applause", 74, gold=True),
            button("Cheer", lambda: self._sfx("cheer"), "Crowd cheer", 58, gold=True),
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

    def _send_danmaku(self) -> None:
        text = self.danmaku_input.text().strip()
        if not text:
            return
        if self.controller.send_danmaku(text):
            self.danmaku_input.clear()
        else:
            self.show_toast("Too many messages at once. Try again in a moment.", error=True)

    def _volume_slider(self, name: str) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setMinimumWidth(64)
        slider.setValue(getattr(self.controller.settings, f"{name}_volume"))
        slider.valueChanged.connect(lambda value: self.controller.set_volume(name, value))
        return slider

    # -- actions ----------------------------------------------------------

    def show_page(self, key: str) -> None:
        page = self.pages[key]
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

    def _on_event(self, topic: str, payload: Any) -> None:
        if topic == "state":
            self._state = self.controller.state()
            self._apply_state()
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
        elif topic == "score":
            self.mv_window.show_score(payload)
            self.show_toast(f"Score: {payload['points']}  ·  {payload['grade']}")
        elif topic == "mixer":
            self.mixer_page.apply_state()

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
        self._nav_buttons["queue"].setText(
            f"🎤   Selected  ({len(queue)})" if queue else "🎤   Selected"
        )

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
        self.lyrics_button.setToolTip(tip)
        if state["scoring"] and not state["separation"]:
            tip = "Scoring needs vocal separation, which is not installed"
        elif state["scoring"] and state["current"] and not state["scoring_active"]:
            tip = "No score for this song yet: its melody is still being prepared"
        else:
            tip = "Score each song: the microphones are compared with the original singer's melody"
        self.score_button.setToolTip(tip)
        for slider, name in (
            (self.music_slider, "music_volume"),
            (self.mic_slider, "mic_volume"),
            (self.guide_slider, "guide_vocal"),
        ):
            if not slider.isSliderDown() and slider.value() != state[name]:
                slider.blockSignals(True)
                slider.setValue(state[name])
                slider.blockSignals(False)

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
