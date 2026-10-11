"""The MV screen: the full-screen window that goes on the extended display."""

from __future__ import annotations

import ctypes
import logging
from typing import Any

from PySide6.QtCore import QByteArray, QRectF, Qt, QTimer, Signal
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
    QResizeEvent,
)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QLabel, QWidget

from ytktv.player.mpv_player import MpvPlayer
from ytktv.ui import theme
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

    # -- layout -----------------------------------------------------------

    def resizeEvent(self, _event: QResizeEvent) -> None:
        if self.video is not None:
            self.video.setGeometry(self.rect())
        self.idle.setGeometry(self.rect())
        self._place_banner()

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
        showing_video = current is not None and state.get("status") in ("playing", "paused")
        if showing_video:
            fade_out(self.idle, 800)  # reveal the video underneath
        else:
            if not self.idle.isVisible():
                self.idle.raise_()
                fade_in(self.idle, 600)
            self.banner.raise_()
            if state.get("status") == "loading" and current:
                self.show_banner(f"Loading:  {current['song']['title']}", 30)
            else:
                fade_out(self.banner, 300)

    def announce_now_playing(self, state: dict[str, Any]) -> None:
        current = state.get("current")
        if current:
            singer = f"   ·   {current['singer']}" if current.get("singer") else ""
            self.show_banner(f"Now Playing:  {current['song']['title']}{singer}")
            self._next_announced_for = None

    def update_position(self, position: float, duration: float, state: dict[str, Any]) -> None:
        """Announce the next song shortly before the current one ends."""
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
