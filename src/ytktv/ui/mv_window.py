"""The MV screen: the full-screen window that goes on the extended display."""

from __future__ import annotations

import ctypes
import logging
import time
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QKeyEvent,
    QLinearGradient,
    QMouseEvent,
    QOpenGLContext,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
    QPolygonF,
    QResizeEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel, QWidget

from ytktv.player.mpv_player import MpvPlayer
from ytktv.ui import theme
from ytktv.ui.mv_overlays import (
    BOARD_HEAD,
    BOARD_ROW,
    DanmakuOverlay,
    EdgeLight,
    LightShow,
    LyricsOverlay,
    PitchLane,
    ScoreCard,
)
from ytktv.ui.support import fade_in, fade_out, qr_pixmap

log = logging.getLogger(__name__)


class VideoWidget(QOpenGLWidget):
    """Draws mpv's video through the libmpv render API."""

    frame_ready = Signal()

    def __init__(self, player: MpvPlayer, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._player = player
        self._context: Any = None
        self._proc_address: Any = None
        self.frame_ready.connect(self.update)

    def _get_proc_address(self, _ctx: Any, name: bytes) -> int:
        context = QOpenGLContext.currentContext()
        if context is None:
            return 0
        address = context.getProcAddress(QByteArray(name))
        if address is None:
            return 0
        try:
            return int(address)
        except TypeError:
            return int(ctypes.cast(address, ctypes.c_void_p).value or 0)

    def initializeGL(self) -> None:
        mpv = self._player._mpv_module
        try:
            self._proc_address = mpv.MpvGlGetProcAddressFn(self._get_proc_address)
            self._context = mpv.MpvRenderContext(
                self._player.mpv,
                "opengl",
                opengl_init_params={"get_proc_address": self._proc_address},
            )
            # Called from mpv's render thread; the signal hops to the GUI thread.
            self._context.update_cb = self.frame_ready.emit
        except Exception:
            log.exception("could not create the mpv render context")
            self._context = None

    def paintGL(self) -> None:
        if self._context is None:
            return
        ratio = self.devicePixelRatioF()
        self._context.render(
            flip_y=True,
            opengl_fbo={
                "w": int(self.width() * ratio),
                "h": int(self.height() * ratio),
                "fbo": self.defaultFramebufferObject(),
            },
        )

    def release(self) -> None:
        """Free the render context; must happen before mpv itself is destroyed."""
        if self._context is None:
            return
        self.makeCurrent()
        try:
            self._context.update_cb = None
            self._context.free()
        except Exception:
            log.debug("render context free failed", exc_info=True)
        self._context = None
        self.doneCurrent()


class IdleCard(QWidget):
    """What the room sees between songs: branding plus the phone QR code."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._url = ""
        self._qr: QPixmap | None = None

    def set_url(self, url: str) -> None:
        self._url = url
        self._qr = qr_pixmap(url, 520) if url else None
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        background = QLinearGradient(0, 0, w, h)
        background.setColorAt(0.0, QColor("#2a0f5e"))
        background.setColorAt(0.5, QColor(theme.BG))
        background.setColorAt(1.0, QColor("#04202e"))
        painter.fillRect(self.rect(), background)

        unit = h / 100.0
        logo = QFont()
        logo.setPixelSize(int(unit * 17))
        logo.setWeight(QFont.Weight.Black)
        logo.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, unit * 1.2)
        painter.setFont(logo)
        glow = QLinearGradient(w * 0.2, 0, w * 0.8, 0)
        glow.setColorAt(0.0, QColor(theme.PINK))
        glow.setColorAt(1.0, QColor(theme.CYAN))
        text_rect = QRectF(0, unit * 8, w, unit * 24)
        painter.setPen(QPen(QBrush(glow), 1))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, "YTKTV")

        body = QFont()
        body.setPixelSize(int(unit * 4.2))
        body.setWeight(QFont.Weight.DemiBold)
        painter.setFont(body)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(
            QRectF(0, unit * 33, w, unit * 7),
            Qt.AlignmentFlag.AlignCenter,
            "Scan with your phone to pick a song",
        )

        if self._qr is not None:
            side = unit * 36
            x, y = (w - side) / 2, unit * 43
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("white"))
            painter.drawRoundedRect(
                QRectF(x - unit, y - unit, side + 2 * unit, side + 2 * unit), unit * 2, unit * 2
            )
            painter.drawPixmap(QRectF(x, y, side, side).toRect(), self._qr)
            small = QFont()
            small.setPixelSize(int(unit * 3.4))
            small.setWeight(QFont.Weight.Bold)
            painter.setFont(small)
            painter.setPen(QColor(theme.CYAN))
            painter.drawText(
                QRectF(0, unit * 84, w, unit * 6), Qt.AlignmentFlag.AlignCenter, self._url
            )


class TransportBadge(QWidget):
    """The pause / play symbol a KTV screen shows in its corner."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.symbol = "pause"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Only the disc is drawn; the video must show through the corners.
        self.setStyleSheet("background: transparent;")
        self.hide()

    def set_symbol(self, symbol: str) -> None:
        self.symbol = symbol
        self.update()

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = float(min(self.width(), self.height()))
        ring = max(2.0, side * 0.045)
        disc = QRectF(ring, ring, side - 2 * ring, side - 2 * ring)
        painter.setPen(QPen(QColor(theme.PINK), ring))
        painter.setBrush(QColor(8, 4, 20, 200))
        painter.drawEllipse(disc)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("white"))
        if self.symbol == "pause":
            bar_w, bar_h = side * 0.12, side * 0.38
            top = (side - bar_h) / 2
            for x in (side * 0.34, side * 0.54):
                painter.drawRoundedRect(QRectF(x, top, bar_w, bar_h), bar_w * 0.25, bar_w * 0.25)
        else:
            # Shifted right a little: a triangle centred on its box looks off-centre.
            left, right = side * 0.40, side * 0.70
            painter.drawPolygon(
                QPolygonF(
                    [
                        QPointF(left, side * 0.31),
                        QPointF(right, side * 0.50),
                        QPointF(left, side * 0.69),
                    ]
                )
            )


class MvWindow(QWidget):
    closed = Signal()

    def __init__(self, player: MpvPlayer | None) -> None:
        super().__init__()
        self.setWindowTitle("YTKTV - MV Screen")
        self.setStyleSheet("background: black;")
        self.resize(960, 540)
        self.video = VideoWidget(player, self) if player is not None else None
        self.idle = IdleCard(self)
        self.banner = QLabel(self)
        self.banner.setTextFormat(Qt.TextFormat.PlainText)
        self.banner.hide()
        self._banner_timer = QTimer(self)
        self._banner_timer.setSingleShot(True)
        self._banner_timer.timeout.connect(lambda: fade_out(self.banner, 500))
        self._next_announced_for: str | None = None
        self.badge = TransportBadge(self)
        self._badge_timer = QTimer(self)
        self._badge_timer.setSingleShot(True)
        self._badge_timer.timeout.connect(lambda: fade_out(self.badge, 500))
        self._last_status = ""

        # Overlays, bottom to top: lights, lyrics, danmaku. One timer animates them all.
        self.lights = {side: EdgeLight(side, self) for side in ("left", "right", "top", "bottom")}
        self._light_show = LightShow()
        self._lights_enabled = True
        self.level_source: Callable[[], tuple[float, float]] | None = None
        self.lyrics = LyricsOverlay(self)
        self.pitch_lane = PitchLane(self)
        self.danmaku = DanmakuOverlay(self)
        self.score_card = ScoreCard(self)
        self._score_timer = QTimer(self)
        self._score_timer.setSingleShot(True)
        self._score_timer.timeout.connect(lambda: fade_out(self.score_card, 700))
        self.live_score = QLabel(self)
        self.live_score.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.live_score.hide()
        self._position = 0.0
        self._position_at = time.monotonic()
        self._speed = 1.0
        self._lyrics_offset = 0.0  # seconds the lyrics run ahead of their subtitles
        self._playing = False
        self._frame = time.monotonic()
        self._animator = QTimer(self)
        self._animator.setInterval(33)
        self._animator.timeout.connect(self._animate)

    # -- layout -----------------------------------------------------------

    def resizeEvent(self, _event: QResizeEvent) -> None:
        if self.video is not None:
            self.video.setGeometry(self.rect())
        self.idle.setGeometry(self.rect())
        self._place_banner()
        self._place_badge()
        w, h = self.width(), self.height()
        strip_w, strip_h = int(w * 0.07), int(h * 0.09)
        self.lights["left"].setGeometry(0, 0, strip_w, h)
        self.lights["right"].setGeometry(w - strip_w, 0, strip_w, h)
        self.lights["top"].setGeometry(0, 0, w, strip_h)
        self.lights["bottom"].setGeometry(0, h - strip_h, w, strip_h)
        self.lyrics.setGeometry(0, int(h * 0.74), w, int(h * 0.24))
        self.pitch_lane.setGeometry(int(w * 0.2), int(h * 0.57), int(w * 0.6), int(h * 0.15))
        self.danmaku.setGeometry(0, int(h * 0.12), w, int(h * 0.42))
        self._place_score_card()
        self._place_live_score()

    def _place_score_card(self) -> None:
        w, h = self.width(), self.height()
        rows = self.score_card.board_rows()
        grow = 1.0 + BOARD_HEAD + BOARD_ROW * rows if rows else 1.0
        card_w, card_h = int(h * 0.62), int(h * 0.5 * grow)
        self.score_card.setGeometry((w - card_w) // 2, (h - card_h) // 2, card_w, card_h)

    def _place_banner(self) -> None:
        unit = max(1.0, self.height() / 100.0)
        self.banner.setStyleSheet(
            "background: rgba(8, 4, 20, 0.78); color: white; font-weight: 800;"
            f"border: {max(1, int(unit * 0.25))}px solid {theme.PINK};"
            f"border-radius: {int(unit * 1.6)}px; padding: {int(unit * 1.1)}px {int(unit * 2.4)}px;"
            f"font-size: {int(unit * 3.2)}px;"
        )
        self.banner.setMaximumWidth(int(self.width() * 0.8))
        self.banner.adjustSize()
        self.banner.move(int(unit * 3), int(unit * 4))

    def _place_badge(self) -> None:
        unit = max(1.0, self.height() / 100.0)
        side = int(unit * 11)
        self.badge.setGeometry(self.width() - side - int(unit * 3), int(unit * 4), side, side)

    def show_transport(self, symbol: str) -> None:
        """Show the pause symbol (stays while paused) or the play symbol (brief)."""
        self._badge_timer.stop()
        self.badge.set_symbol(symbol)
        self._place_badge()
        fade_in(self.badge, 180)
        self.badge.raise_()
        if symbol == "play":
            self._badge_timer.start(1200)

    # -- animated overlays ------------------------------------------------

    def _place_live_score(self) -> None:
        unit = max(1.0, self.height() / 100.0)
        self.live_score.setStyleSheet(
            f"background: rgba(8, 4, 20, 0.78); color: {theme.CYAN}; font-weight: 900;"
            f"border: {max(1, int(unit * 0.2))}px solid {theme.CYAN};"
            f"border-radius: {int(unit * 1.4)}px; padding: {int(unit * 0.7)}px {int(unit * 1.6)}px;"
            f"font-size: {int(unit * 2.6)}px;"
        )
        self.live_score.adjustSize()
        # Top right, below where the pause symbol appears.
        self.live_score.move(self.width() - self.live_score.width() - int(unit * 3), int(unit * 17))

    def set_live_score(self, points: int | None) -> None:
        """Show the running score while a song is being scored; None hides it."""
        if points is None:
            if self.live_score.isVisible():
                fade_out(self.live_score, 300)
            return
        self.live_score.setText(f"SCORE  {points}")
        self._place_live_score()
        if not self.live_score.isVisible():
            fade_in(self.live_score, 300)
        self.live_score.raise_()

    def show_score(self, score: dict[str, Any]) -> None:
        """The end-of-song result: stays up a few seconds over whatever comes next."""
        singer = score.get("singer") or ""
        caption = f"{singer}  ·  {score['title']}" if singer else str(score["title"])
        voices = score.get("voices") or []
        if len(voices) >= 2:  # a duet: one score for each microphone
            caption = "   ·   ".join(f"Mic {voice['mic']}  {voice['points']}" for voice in voices)
        board = score.get("board") or []
        self.score_card.set_score(
            int(score["points"]), str(score["grade"]), caption, int(score.get("rank") or 0), board
        )
        self._place_score_card()
        fade_in(self.score_card, 400)
        self.score_card.raise_()
        self._score_timer.start(9000 if len(board) > 1 else 7000)

    def set_melody(self, melody: dict[str, Any] | None) -> None:
        """Show the tune being scored as a lane of bars, or hide it with None."""
        self.pitch_lane.set_melody(melody)
        if melody is not None:
            self.pitch_lane.raise_()
            self.score_card.raise_()

    def add_sung_pitch(self, position: float, note: float | None) -> None:
        self.pitch_lane.add_voice(position, note)

    def set_lyrics(self, lines: list[dict[str, Any]]) -> None:
        self.lyrics.set_lines(lines)
        self.lyrics.raise_()
        self._sync_animator()

    def add_danmaku(self, text: str) -> None:
        self.danmaku.add(text)
        self._sync_animator()

    def _sync_animator(self) -> None:
        """Run the animation timer only while something on screen is moving."""
        needed = self.isVisible() and (self._playing or self.danmaku.active())
        if needed and not self._animator.isActive():
            self._frame = time.monotonic()
            self._animator.start()
        elif not needed and self._animator.isActive():
            self._animator.stop()
            for light in self.lights.values():
                light.set_light(0.0, 0.0)

    def _animate(self) -> None:
        now = time.monotonic()
        elapsed, self._frame = min(0.25, now - self._frame), now
        self.danmaku.advance(elapsed)
        if self._playing:
            # Position reports arrive twice a second; glide between them.
            position = self._position + (now - self._position_at) * self._speed
            if self.lyrics.has_lines():
                self.lyrics.set_time(position + self._lyrics_offset)
            if self.pitch_lane.has_melody():
                self.pitch_lane.set_time(position)
            if self._lights_enabled and self.level_source is not None:
                left, right = self.level_source()
                for side, (intensity, hue) in self._light_show.step(
                    max(left, right), elapsed
                ).items():
                    self.lights[side].set_light(intensity, hue)
        if not self._playing or not self._lights_enabled:
            for light in self.lights.values():
                light.set_light(0.0, 0.0)
        self._sync_animator()

    def place_on_screen(self, screen_index: int, fullscreen: bool) -> None:
        """Show on the chosen display (-1 = the first non-primary one, if any)."""
        screens = QGuiApplication.screens()
        primary = QGuiApplication.primaryScreen()
        target = None
        if 0 <= screen_index < len(screens):
            target = screens[screen_index]
        elif screen_index < 0:
            target = next((s for s in screens if s is not primary), None)
        if target is None:
            # Single display: stay a normal window so the console is not covered.
            self.showNormal()
            return
        self.showNormal()
        self.setGeometry(target.geometry())
        handle = self.windowHandle()
        if handle is not None:
            handle.setScreen(target)
        if fullscreen:
            self.showFullScreen()
        else:
            self.show()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def mouseDoubleClickEvent(self, _event: QMouseEvent) -> None:
        self.toggle_fullscreen()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event: Any) -> None:
        self.closed.emit()
        super().closeEvent(event)

    # -- content ----------------------------------------------------------

    def set_url(self, url: str) -> None:
        self.idle.set_url(url)

    def show_banner(self, text: str, seconds: float = 6.0) -> None:
        self.banner.setText(text)
        self._place_banner()
        fade_in(self.banner, 350)
        self.banner.raise_()
        self._banner_timer.start(int(seconds * 1000))

    def apply_state(self, state: dict[str, Any]) -> None:
        """React to a controller state snapshot."""
        current = state.get("current")
        status = state.get("status")
        if status == "paused" and self._last_status != "paused":
            self.show_transport("pause")
        elif status == "playing" and self._last_status == "paused":
            self.show_transport("play")
        elif status not in ("playing", "paused"):
            self._badge_timer.stop()
            fade_out(self.badge, 200)
        self._last_status = str(status)
        self._playing = status == "playing"
        self._speed = float(state.get("speed") or 1.0)
        self._lyrics_offset = float(state.get("lyrics_offset") or 0.0)
        self._lights_enabled = bool(state.get("lights", True))
        if current is None:
            # Only when nothing is on: lyrics and the tune arrive while a song is still
            # loading, and clearing them then left the first song of an evening without
            # lyrics until the Lyrics button was pressed twice. A change of song clears
            # them anyway, with the controller's own (empty) lyrics and melody events.
            self.lyrics.set_lines([])
            self.pitch_lane.set_melody(None)
        if status not in ("playing", "paused"):
            self.set_live_score(None)
        self._sync_animator()
        showing_video = current is not None and status in ("playing", "paused")
        if showing_video:
            fade_out(self.idle, 800)  # reveal the video underneath
        else:
            if not self.idle.isVisible():
                self.idle.raise_()
                fade_in(self.idle, 600)
            self.banner.raise_()
            if state.get("status") == "loading" and current:
                reason = state.get("loading") or "Loading"
                self.show_banner(f"{reason}...   {current['song']['title']}", 600)
            else:
                fade_out(self.banner, 300)

    def announce_now_playing(self, state: dict[str, Any]) -> None:
        current = state.get("current")
        if current:
            singer = f"   ·   {current['singer']}" if current.get("singer") else ""
            self.show_banner(f"Now Playing:  {current['song']['title']}{singer}")
            self._next_announced_for = None

    def update_position(self, position: float, duration: float, state: dict[str, Any]) -> None:
        """Track playback time, and announce the next song shortly before this one ends."""
        self._position, self._position_at = position, time.monotonic()
        current = state.get("current")
        queue = state.get("queue") or []
        if not current or duration <= 0 or duration - position > 20 or position < 5:
            return
        if self._next_announced_for == current["id"]:
            return
        self._next_announced_for = current["id"]
        if queue:
            self.show_banner(f"Up Next:  {queue[0]['song']['title']}", 10)
        else:
            self.show_banner("Queue is empty. Pick the next song!", 10)

    def release(self) -> None:
        if self.video is not None:
            self.video.release()
