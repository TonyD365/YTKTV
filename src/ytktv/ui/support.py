"""Small Qt helpers: event bridge, background tasks, thumbnails, QR codes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import qrcode
from PySide6.QtCore import (
    QEasingCurve,
    QObject,
    QPropertyAnimation,
    QRunnable,
    Qt,
    QThreadPool,
    QUrl,
    Signal,
)
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from ytktv.core.events import EventBus

log = logging.getLogger(__name__)


def fade(
    widget: QWidget,
    end: float,
    duration: int = 220,
    start: float | None = None,
    finished: Callable[[], None] | None = None,
) -> None:
    """Animate *widget*'s opacity to *end* (0..1).

    Starts from *start*, or from wherever a fade already in progress has got
    to. The opacity effect is removed again once the widget is fully opaque,
    so idle widgets pay no rendering cost.
    """
    previous = getattr(widget, "_fade_animation", None)
    if previous is not None:
        previous.stop()
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        effect.setOpacity(1.0 if start is None else start)
        widget.setGraphicsEffect(effect)
    elif start is not None:
        effect.setOpacity(start)
    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(effect.opacity())
    animation.setEndValue(end)
    animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

    def done() -> None:
        widget._fade_animation = None  # type: ignore[attr-defined]
        if end >= 1.0:
            widget.setGraphicsEffect(None)  # type: ignore[arg-type]
        if finished:
            finished()

    animation.finished.connect(done)
    widget._fade_animation = animation  # type: ignore[attr-defined]
    animation.start()


def fade_in(widget: QWidget, duration: int = 220) -> None:
    """Show *widget* and fade it in from transparent (or from mid-fade)."""
    hidden = not widget.isVisible()
    widget.show()
    fade(widget, 1.0, duration, start=0.0 if hidden else None)


def fade_out(widget: QWidget, duration: int = 320) -> None:
    """Fade *widget* out, then hide it."""
    if widget.isVisible():
        fade(widget, 0.0, duration, finished=widget.hide)


class EventBridge(QObject):
    """Re-emits controller events as a Qt signal on the GUI thread."""

    received = Signal(str, object)

    def __init__(self, bus: EventBus, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._unsubscribe = bus.subscribe(self._forward)

    def _forward(self, topic: str, payload: Any) -> None:
        try:
            self.received.emit(topic, payload)
        except RuntimeError:
            pass  # the QObject is already gone during shutdown

    def close(self) -> None:
        self._unsubscribe()


class _TaskSignals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]) -> None:
        super().__init__()
        self.fn = fn
        self.signals = _TaskSignals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:
            log.warning("background task failed: %s", exc)
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


_live_tasks: set[_Task] = set()


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    """Run *fn* on the thread pool; callbacks are delivered on the GUI thread."""
    task = _Task(fn)
    task.setAutoDelete(False)
    _live_tasks.add(task)

    def finish(callback: Callable[[Any], None] | None, value: Any) -> None:
        _live_tasks.discard(task)
        if callback:
            callback(value)

    task.signals.done.connect(lambda value: finish(on_done, value))
    task.signals.failed.connect(lambda exc: finish(on_error, exc))
    QThreadPool.globalInstance().start(task)


class ThumbnailLoader(QObject):
    """Fetches and caches thumbnails."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._network = QNetworkAccessManager(self)
        self._cache: dict[str, QPixmap] = {}
        self._waiting: dict[str, list[Callable[[QPixmap], None]]] = {}

    def load(self, url: str, callback: Callable[[QPixmap], None]) -> None:
        if not url:
            return
        cached = self._cache.get(url)
        if cached is not None:
            callback(cached)
            return
        if url in self._waiting:
            self._waiting[url].append(callback)
            return
        self._waiting[url] = [callback]
        reply = self._network.get(QNetworkRequest(QUrl(url)))
        reply.finished.connect(lambda: self._finished(url, reply))

    def _finished(self, url: str, reply: QNetworkReply) -> None:
        callbacks = self._waiting.pop(url, [])
        pixmap = QPixmap()
        if reply.error() == QNetworkReply.NetworkError.NoError:
            pixmap.loadFromData(reply.readAll())
        reply.deleteLater()
        if pixmap.isNull():
            return
        if len(self._cache) > 400:
            self._cache.clear()
        self._cache[url] = pixmap
        for callback in callbacks:
            try:
                callback(pixmap)
            except RuntimeError:
                pass  # the label was deleted while we were downloading


def qr_pixmap(text: str, size: int, dark: str = "#0d0720", light: str = "#ffffff") -> QPixmap:
    """Render a QR code without needing Pillow."""
    code = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    code.add_data(text)
    code.make(fit=True)
    matrix = code.get_matrix()
    count = len(matrix)
    scale = max(1, size // count)
    image = QImage(count * scale, count * scale, QImage.Format.Format_RGB32)
    image.fill(QColor(light))
    painter = QPainter(image)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(dark))
    for y, row in enumerate(matrix):
        for x, filled in enumerate(row):
            if filled:
                painter.drawRect(x * scale, y * scale, scale, scale)
    painter.end()
    return QPixmap.fromImage(image).scaled(
        size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation
    )


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"
