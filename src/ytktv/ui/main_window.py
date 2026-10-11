"""The control console on the main display, styled after a KTV song machine."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QDateTime, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QKeyEvent, QResizeEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
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
    Context,
    FavoritesPage,
    HistoryPage,
    HotPage,
    Page,
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
    ("favorites", "♥   Favorites"),
    ("queue", "🎤   Selected"),
    ("history", "✓   Sung"),
    ("mixer", "🎚   Mixer"),
    ("settings", "⚙   Settings"),
)


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
        self.setMinimumSize(1320, 760)

        self.bridge = EventBridge(controller.bus, self)
        self.bridge.received.connect(self._on_event)
        self.ctx = Context(controller, youtube, ThumbnailLoader(self))
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
            "favorites": FavoritesPage(self.ctx),
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
            (VocalMode.CENTER_CUT, "Vocal Cut", "Instant vocal reduction (no waiting)", 78),
            (VocalMode.LEFT, "L", "Left channel only (split-track KTV videos)", 44),
            (VocalMode.RIGHT, "R", "Right channel only (split-track KTV videos)", 44),
        ):
            widget = button(text, lambda m=mode: self._choose_mode(m), tip, width)
            widget.setCheckable(True)
            if mode in (VocalMode.LEFT, VocalMode.RIGHT):
                widget.setProperty("round", True)
            self.mode_buttons[mode] = widget
        group("VOCALS", *self.mode_buttons.values())

        # Transport
        self.pause_button = button("⏯", controller.toggle_pause, "Play / Pause", round=True)
        group(
            "PLAYBACK",
            button("⏮", controller.replay, "Replay from the start", round=True),
            self.pause_button,
            button("⏭", controller.skip, "Skip to the next song", round=True),
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
        group("MUSIC VOLUME", self.music_slider, stretch=1)
        group("MIC VOLUME", self.mic_slider, stretch=1)

        # Crowd
        group(
            "CROWD",
            button("Applause", lambda: self._sfx("applause"), "Applause", 80, gold=True),
            button("Cheer", lambda: self._sfx("cheer"), "Crowd cheer", 68, gold=True),
            button("📣", lambda: self._sfx("airhorn"), "Air horn", round=True),
            button("🥁", lambda: self._sfx("drumroll"), "Drum roll", round=True),
        )
        return bar

    def _volume_slider(self, name: str) -> QSlider:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setMinimumWidth(86)
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
        elif topic == "toast":
            self.show_toast(payload["message"], payload.get("error", False))
        elif topic == "favorites":
            for page in self.pages.values():
                if isinstance(page, Page):
                    page.on_favorites()
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
        pitch = state["pitch"]
        self.key_readout.setText(f"{pitch:+d}" if pitch else "0")
        self.key_readout.setEnabled(abs(pitch) < PITCH_RANGE)
        self.tempo_readout.setText(f"{round(state['speed'] * 100)}%")
        for slider, name in ((self.music_slider, "music_volume"), (self.mic_slider, "mic_volume")):
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
