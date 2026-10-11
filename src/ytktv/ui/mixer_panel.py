"""The mixing console page, laid out like a hardware analog mixer."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ytktv.audio import devices
from ytktv.config import MicSettings
from ytktv.core.controller import KTVController
from ytktv.ui.console_widgets import Fader, Knob, Led, LedMeter, XlrJack

OFF = "Off"
DEFAULT = "System Default"

_CONSOLE_STYLE = """
#console { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2b2b2f, stop:0.08 #1d1d20, stop:1 #161618);
    border: 2px solid #050505; border-radius: 18px; }
#console QLabel { color: #d8d8d8; font-size: 9px; font-weight: 800; letter-spacing: 1px; }
#console QLabel#chNumber { font-size: 18px; color: #f2f2f2; }
#console QLabel#brand { font-size: 17px; color: #f2f2f2; letter-spacing: 0px; }
#console QLabel#brandSub { font-size: 9px; color: #9b9ba0; font-weight: 600; letter-spacing: 0px; }
#console QLabel#lcd { background: #1b4fd6; color: #eaf2ff; border: 3px solid #05070c; border-radius: 4px;
    font-family: "Menlo", "Consolas", monospace; font-size: 10px; font-weight: 700; padding: 6px; letter-spacing: 0px; }
#console QComboBox { background: #0c0c0e; color: #e6e6e6; border: 1px solid #3a3a3e; border-radius: 4px;
    padding: 3px 6px; font-size: 10px; min-height: 16px; }
#console QComboBox QAbstractItemView { background: #0c0c0e; color: #e6e6e6; selection-background-color: #1b4fd6; }
#console QPushButton { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f4f4f4, stop:1 #b9b9bd);
    color: #111; border: 1px solid #000; border-radius: 3px; padding: 3px 6px; font-size: 9px; font-weight: 900;
    min-width: 0; min-height: 14px; }
#console QPushButton:checked { background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ff6b6b, stop:1 #c81e1e);
    color: white; }
"""


class _StripFrame(QWidget):
    """Paints the strip divider and the light-grey EQ zone behind the EQ knobs."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.eq_widgets: list[QWidget] = []

    def paintEvent(self, _event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(QColor("#050505"), 2))
        painter.drawLine(self.width() - 1, 0, self.width() - 1, self.height())
        if self.eq_widgets:
            top = self.eq_widgets[0].geometry().top() - 2
            bottom = self.eq_widgets[-1].geometry().bottom() + 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#c9c9cd"))
            painter.drawRect(QRectF(0, top, self.width() - 2, bottom - top))


class ChannelStrip(_StripFrame):
    def __init__(self, index: int, mic: MicSettings, controller: KTVController) -> None:
        super().__init__()
        self.index = index
        self.mic = mic
        self.controller = controller
        self.setFixedWidth(84)
        self.knobs: dict[str, Knob] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 6, 8)
        layout.setSpacing(1)

        number = QLabel(str(index + 1))
        number.setObjectName("chNumber")
        layout.addWidget(number, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(XlrJack(), alignment=Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(QLabel("MIC"), alignment=Qt.AlignmentFlag.AlignHCenter)

        self.device = QComboBox()
        self.device.setToolTip("Input device for this channel")
        self.device.activated.connect(self._device_chosen)
        layout.addWidget(self.device)
        layout.addSpacing(4)

        def knob(
            label: str,
            attr: str,
            low: float,
            high: float,
            default: float,
            color: str,
            left: str = "",
            right: str = "",
        ) -> Knob:
            widget = Knob(label, low, high, default, color, left, right)
            widget.set_value(float(getattr(mic, attr)))
            widget.valueChanged.connect(lambda value, a=attr: self._set(a, value))
            layout.addWidget(widget)
            self.knobs[attr] = widget
            return widget

        knob("GAIN", "gain", 0.0, 2.0, 1.0, "#25c26a")
        eq_cap = "#3d3d42"
        eq_knobs = [
            knob("HIGH", "high_db", -12.0, 12.0, 0.0, eq_cap, "-12", "+12"),
            knob("MID", "mid_db", -12.0, 12.0, 0.0, eq_cap, "-12", "+12"),
            knob("LOW", "low_db", -12.0, 12.0, 0.0, eq_cap, "-12", "+12"),
        ]
        self.eq_widgets = list(eq_knobs)
        for widget in eq_knobs:
            widget.ink = QColor("#141416")
        knob("ECHO", "echo", 0.0, 1.0, 0.15, "#2f7df0")
        knob("FX", "reverb", 0.0, 1.0, 0.25, "#f2d024")
        knob("PAN", "pan", -1.0, 1.0, 0.0, "#e03030", "L", "R")

        leds = QHBoxLayout()
        leds.setSpacing(3)
        self.peak = Led("#ff2a2a")
        self.signal = Led("#35e05a")
        leds.addWidget(self.peak)
        leds.addWidget(QLabel("PEAK"))
        leds.addStretch()
        leds.addWidget(self.signal)
        layout.addLayout(leds)

        self.fader = Fader("#ececec")
        self.fader.set_value(mic.fader)
        self.fader.valueChanged.connect(lambda value: self._set("fader", value))
        layout.addWidget(self.fader, stretch=1)

        self.mute = QPushButton("MUTE")
        self.mute.setCheckable(True)
        self.mute.setChecked(mic.mute)
        self.mute.toggled.connect(lambda on: self._set("mute", on))
        layout.addWidget(self.mute)

    def _set(self, attr: str, value: Any) -> None:
        self.controller.set_mic(self.index, **{attr: value})

    def refresh(self) -> None:
        """Move the controls to match the settings (a preset or a phone changed them)."""
        for attr, knob in self.knobs.items():
            knob.set_value(float(getattr(self.mic, attr)))
        self.fader.set_value(self.mic.fader)
        if self.mute.isChecked() != self.mic.mute:
            self.mute.blockSignals(True)
            self.mute.setChecked(self.mic.mute)
            self.mute.blockSignals(False)

    def set_devices(self, names: list[str]) -> None:
        self.device.blockSignals(True)
        self.device.clear()
        self.device.addItems([OFF, DEFAULT, *names])
        if not self.mic.enabled:
            self.device.setCurrentText(OFF)
        elif self.mic.device and self.mic.device in names:
            self.device.setCurrentText(self.mic.device)
        else:
            self.device.setCurrentText(DEFAULT)
        self.device.blockSignals(False)

    def _device_chosen(self, _index: int) -> None:
        choice = self.device.currentText()
        self.mic.enabled = choice != OFF
        if choice not in (OFF, DEFAULT):
            self.mic.device = choice
        elif choice == DEFAULT:
            self.mic.device = None
        self.controller.restart_audio()

    def set_level(self, peak: float) -> None:
        self.peak.set_on(peak >= 0.9)
        self.signal.set_on(peak >= 0.02)


class _BusStrip(_StripFrame):
    """A fader-only strip (music, mic master, main)."""

    def __init__(self, title: str, cap_color: str, count: int = 1) -> None:
        super().__init__()
        self.setFixedWidth(64 * count)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 6, 8)
        row = QHBoxLayout()
        row.setSpacing(0)
        self.faders = [Fader(cap_color) for _ in range(count)]
        for fader in self.faders:
            row.addWidget(fader)
        layout.addLayout(row, stretch=1)
        layout.addWidget(QLabel(title), alignment=Qt.AlignmentFlag.AlignHCenter)

    def set_value(self, value: float) -> None:
        for fader in self.faders:
            fader.set_value(value)


class MixerPanel(QWidget):
    def __init__(self, controller: KTVController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        settings = controller.settings

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        holder = QWidget()
        scroll.setWidget(holder)
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(8, 8, 8, 8)
        holder_layout.addStretch()

        console = QFrame()
        console.setObjectName("console")
        console.setStyleSheet(_CONSOLE_STYLE)
        holder_layout.addWidget(console)
        holder_layout.addStretch()

        root = QVBoxLayout(console)
        root.setContentsMargins(16, 10, 16, 14)
        root.setSpacing(6)
        head = QHBoxLayout()
        brand = QLabel("Professional")
        brand.setObjectName("brand")
        sub = QLabel("4-channel karaoke mixing console with effects processor")
        sub.setObjectName("brandSub")
        head.addWidget(brand)
        head.addWidget(sub)
        head.addStretch()
        model = QLabel("YTKTV  MX-4")
        model.setObjectName("brandSub")
        head.addWidget(model)
        root.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(0)
        root.addLayout(body, stretch=1)

        self.strips = [ChannelStrip(i, mic, controller) for i, mic in enumerate(settings.mics)]
        for strip in self.strips:
            body.addWidget(strip)

        # Master section: display, output routing, meter and bus faders.
        master = QVBoxLayout()
        master.setContentsMargins(12, 8, 0, 0)
        master.setSpacing(8)
        body.addLayout(master)

        self.lcd = QLabel()
        self.lcd.setObjectName("lcd")
        self.lcd.setMinimumWidth(250)
        self.lcd.setTextFormat(Qt.TextFormat.PlainText)
        master.addWidget(self.lcd)

        master.addWidget(QLabel("MAIN OUT"))
        self.output = QComboBox()
        self.output.setToolTip("Output device for music and microphones")
        self.output.activated.connect(self._output_chosen)
        master.addWidget(self.output)

        buttons = QHBoxLayout()
        self.monitor = QPushButton("MIC ON")
        self.monitor.setCheckable(True)
        self.monitor.setChecked(settings.mic_monitor)
        self.monitor.setToolTip("Mix the microphones into the output")
        self.monitor.toggled.connect(self._monitor_toggled)
        rescan = QPushButton("RESCAN")
        rescan.setToolTip("Look for newly connected audio devices")
        rescan.clicked.connect(self.refresh_devices)
        buttons.addWidget(self.monitor)
        buttons.addWidget(rescan)
        master.addLayout(buttons)

        master.addWidget(QLabel("EFFECT PRESET"))
        self.preset = QComboBox()
        self.preset.setToolTip("EQ, reverb and echo for every microphone channel")
        self.preset.activated.connect(self._preset_chosen)
        master.addWidget(self.preset)
        preset_buttons = QHBoxLayout()
        save = QPushButton("SAVE AS")
        save.setToolTip("Save channel 1's EQ, reverb and echo as a new preset")
        save.clicked.connect(self._save_preset)
        self.delete_preset = QPushButton("DELETE")
        self.delete_preset.setToolTip("Delete the selected saved preset")
        self.delete_preset.clicked.connect(self._delete_preset)
        preset_buttons.addWidget(save)
        preset_buttons.addWidget(self.delete_preset)
        master.addLayout(preset_buttons)

        buses = QHBoxLayout()
        buses.setSpacing(0)
        meter_column = QVBoxLayout()
        meter_column.setSpacing(2)
        self.meter = LedMeter()
        self.meter.setToolTip("Total output level: music and microphones together")
        meter_column.addWidget(self.meter, stretch=1)
        meter_column.addWidget(QLabel("OUTPUT"), alignment=Qt.AlignmentFlag.AlignHCenter)
        buses.addLayout(meter_column)
        self.music = _BusStrip("MUSIC", "#8c8c92")
        self.mic_bus = _BusStrip("MICS", "#ececec")
        self.main = _BusStrip("L   MAIN   R", "#e02a2a", count=2)
        for bus, name in ((self.music, "music"), (self.mic_bus, "mic"), (self.main, "master")):
            for fader in bus.faders:
                fader.default = 0.8
                fader.valueChanged.connect(
                    lambda value, n=name, s=bus: self._bus_moved(n, s, value)
                )
            buses.addWidget(bus)
        master.addLayout(buses, stretch=1)

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self.refresh_devices()
        self.apply_state()

    # -- data flow --------------------------------------------------------

    def refresh_devices(self) -> None:
        inputs = devices.list_inputs()
        for strip in self.strips:
            strip.set_devices(inputs)
        self.output.blockSignals(True)
        self.output.clear()
        outputs = devices.list_outputs()
        self.output.addItems([DEFAULT, *outputs])
        current = self.controller.settings.output_device
        self.output.setCurrentText(current if current in outputs else DEFAULT)
        self.output.blockSignals(False)
        self._update_lcd()

    def _output_chosen(self, _index: int) -> None:
        choice = self.output.currentText()
        self.controller.set_output_device(None if choice == DEFAULT else choice)
        self._update_lcd()

    def _monitor_toggled(self, on: bool) -> None:
        self.controller.settings.mic_monitor = on
        self.controller.restart_audio()
        self._update_lcd()

    def _bus_moved(self, name: str, strip: _BusStrip, value: float) -> None:
        strip.set_value(value)
        self.controller.set_volume(name, round(value * 100))

    def _preset_chosen(self, _index: int) -> None:
        name = self.preset.currentData()
        if name:
            self.controller.apply_preset(str(name))

    def _save_preset(self) -> None:
        name, accepted = QInputDialog.getText(self, "Save preset", "Name for this preset:")
        if not accepted or not name.strip():
            return
        try:
            self.controller.save_preset(name)
        except ValueError as exc:
            self.controller.toast(str(exc), error=True)

    def _delete_preset(self) -> None:
        name = self.preset.currentData()
        if name and not self.controller.delete_preset(str(name)):
            self.controller.toast("Built-in presets cannot be deleted", error=True)

    def _refresh_presets(self) -> None:
        state = self.controller.mixer_state()
        self.preset.blockSignals(True)
        self.preset.clear()
        self.preset.addItem("Custom", "")
        for preset in state["presets"]:
            self.preset.addItem(preset["name"], preset["name"])
        self.preset.setCurrentIndex(max(0, self.preset.findData(state["preset"])))
        self.preset.blockSignals(False)
        saved = {p["name"] for p in state["presets"] if not p["builtin"]}
        self.delete_preset.setEnabled(state["preset"] in saved)

    def apply_state(self) -> None:
        for strip in self.strips:
            strip.refresh()
        self._refresh_presets()
        settings = self.controller.settings
        self.music.set_value(settings.music_volume / 100.0)
        self.mic_bus.set_value(settings.mic_volume / 100.0)
        self.main.set_value(settings.master_volume / 100.0)
        self._update_lcd()

    def _update_lcd(self) -> None:
        controller = self.controller
        audio = controller.audio
        lines = [f"OUT  {(controller.settings.output_device or 'System Default')[:26]}"]
        if audio is None:
            lines.append("MIX  OFFLINE")
        elif audio.error:
            lines.append(f"ERR  {audio.error[:26]}")
        else:
            state = "ON" if audio.running else "STOPPED"
            dropped = f"  XRUN {audio.underruns}" if audio.underruns else ""
            lines.append(f"MIX  {state}  {audio.sample_rate / 1000:g} kHz{dropped}")
        lines.append(f"SEP  {(controller.accelerator or 'Detecting...')[:26]}")
        self.lcd.setText("\n".join(lines))

    def _show_output(self, mic_left: float, mic_right: float) -> None:
        """Total output: the music from the player plus the microphone bus."""
        music_left, music_right = self.controller.player.levels()
        # The two are separate streams mixed by the sound card; their powers add.
        self.meter.set_levels(
            (music_left**2 + mic_left**2) ** 0.5, (music_right**2 + mic_right**2) ** 0.5
        )

    def _tick(self) -> None:
        audio = self.controller.audio
        if audio is None:
            self._show_output(0.0, 0.0)
            return
        levels = audio.levels()
        for strip, peak in zip(self.strips, levels["mics"], strict=False):
            strip.set_level(peak)
        mics = levels["master"]
        self._show_output(mics[0], mics[1])

    def showEvent(self, event: Any) -> None:
        self._timer.start()
        self._update_lcd()
        super().showEvent(event)

    def hideEvent(self, event: Any) -> None:
        self._timer.stop()
        super().hideEvent(event)
