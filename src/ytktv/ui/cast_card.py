"""Cast to Chromecast, in Settings under TV Without a Cable (see ytktv.cast)."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from ytktv import cast
from ytktv.ui.support import run_async


def frame_bytes(image: QImage, width: int, height: int) -> bytes:
    """*image* fitted into a black width x height picture, as packed RGB bytes."""
    canvas = QImage(width, height, QImage.Format.Format_RGB888)
    canvas.fill(QColor("black"))
    if not image.isNull():
        fitted = image.scaled(
            width,
            height,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.FastTransformation,
        )
        painter = QPainter(canvas)
        painter.drawImage((width - fitted.width()) // 2, (height - fitted.height()) // 2, fitted)
        painter.end()
    row = width * 3
    data = bytes(canvas.constBits())
    stride = canvas.bytesPerLine()
    if stride == row:
        return data[: row * height]
    return b"".join(data[y * stride : y * stride + row] for y in range(height))


class FrameGrabber(QObject):
    """Films the MV window (video, lyrics and every overlay) for the cast stream."""

    def __init__(self, window: QWidget, stream: cast.CastStream) -> None:
        super().__init__(window)
        self._window = window
        self._stream = stream
        self._timer = QTimer(self)
        self._timer.setInterval(max(1, 1000 // stream.fps))
        self._timer.timeout.connect(self.grab)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def grab(self) -> None:
        image = self._window.grab().toImage()
        self._stream.push(frame_bytes(image, self._stream.width, self._stream.height))


class CastCard(QWidget):
    """Find Chromecasts, cast to one, stop, and see how it is going."""

    changed = Signal(str, str)  # state, text; emitted from any thread

    def __init__(
        self,
        caster: cast.Caster,
        grabber: FrameGrabber,
        discover: Callable[[], list[cast.Device]] = cast.discover,
    ) -> None:
        super().__init__()
        self.caster = caster
        self.grabber = grabber
        self._discover = discover
        caster.on_change = self.changed.emit
        self.changed.connect(self._show)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        head = QLabel("<b>Chromecast</b>")
        layout.addWidget(head)
        note = QLabel(
            "Casting sends the whole MV screen, lyrics and effects included, to a Chromecast"
            " or a TV with Chromecast built in. The picture arrives about 1–3 seconds late,"
            " and the sound stays on this computer's speakers: raise the picture delay above"
            " to its highest so the lyrics stay closer to the singing."
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        row = QHBoxLayout()
        self.devices = QComboBox()
        self.devices.setPlaceholderText("No Chromecast found yet")
        self.search_button = QPushButton("Search")
        self.search_button.clicked.connect(self.search)
        self.cast_button = QPushButton("Cast to Chromecast")
        self.cast_button.setProperty("accent", True)
        self.cast_button.clicked.connect(self.toggle)
        row.addWidget(self.devices, stretch=1)
        row.addWidget(self.search_button)
        row.addWidget(self.cast_button)
        layout.addLayout(row)
        self.status = QLabel("Not casting")
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

    def search(self) -> None:
        self.search_button.setEnabled(False)
        self.status.setText("Looking for Chromecasts…")

        def found(devices: list[cast.Device]) -> None:
            self.search_button.setEnabled(True)
            current = self.devices.currentData()
            self.devices.clear()
            for device in devices:
                self.devices.addItem(device.name, device)
            if current is not None:
                index = next((i for i, d in enumerate(devices) if d.uuid == current.uuid), 0)
                self.devices.setCurrentIndex(index)
            if self.caster.state != cast.CASTING:
                self.status.setText(
                    f"Found {len(devices)}." if devices else "No Chromecast on this network."
                )

        def failed(exc: Exception) -> None:
            self.search_button.setEnabled(True)
            self.status.setText(f"Could not search: {exc}")

        run_async(self._discover, found, failed)

    def toggle(self) -> None:
        if self.caster.state in (cast.CASTING, cast.CONNECTING):
            self.stop()
            return
        device = self.devices.currentData()
        if not isinstance(device, cast.Device):
            self.status.setText("Search, then pick a Chromecast first.")
            return
        self.grabber.start()
        self.cast_button.setEnabled(False)
        run_async(lambda: self.caster.start(device))

    def stop(self) -> None:
        self.grabber.stop()
        self.caster.stop()

    def _show(self, state: str, text: str) -> None:
        self.status.setText(text)
        busy = state in (cast.CASTING, cast.CONNECTING)
        self.cast_button.setEnabled(state != cast.CONNECTING)
        self.cast_button.setText("Stop Casting" if busy else "Cast to Chromecast")
        self.devices.setEnabled(not busy)
        if not busy:
            self.grabber.stop()
