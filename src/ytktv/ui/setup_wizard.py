"""First-run setup: where the sound goes, where the video goes, and a microphone check."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ytktv.audio import devices
from ytktv.core.controller import KTVController

DEFAULT = "System Default"
OFF = "Off"
STEPS = ("Sound", "MV Screen", "Microphone")


class SetupWizard(QDialog):
    """Three steps, each applied as soon as it is chosen so it can be tried at once."""

    def __init__(
        self,
        controller: KTVController,
        place_mv: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self._place_mv = place_mv
        self.setWindowTitle("Set up YTKTV")
        self.setModal(True)
        self.setMinimumSize(560, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)
        self.step_label = QLabel()
        self.step_label.setObjectName("settingsHead")
        layout.addWidget(self.step_label)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, stretch=1)

        self.output = QComboBox()
        self.screen_combo = QComboBox()
        self.mic = QComboBox()
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.heard = QLabel()
        self.heard.setObjectName("hint")
        self._build_sound()
        self._build_screen()
        self._build_microphone()

        buttons = QHBoxLayout()
        skip = QPushButton("Skip Setup")
        skip.clicked.connect(self.finish)
        self.back = QPushButton("Back")
        self.back.clicked.connect(lambda: self.go(self.pages.currentIndex() - 1))
        self.next = QPushButton()
        self.next.setProperty("accent", True)
        self.next.setDefault(True)
        self.next.clicked.connect(self._advance)
        buttons.addWidget(skip)
        buttons.addStretch()
        buttons.addWidget(self.back)
        buttons.addWidget(self.next)
        layout.addLayout(buttons)

        self._meter = QTimer(self)
        self._meter.setInterval(60)
        self._meter.timeout.connect(self._show_level)
        self._loudest = 0.0
        self.go(0)

    # -- pages --------------------------------------------------------------

    def _page(self, title: str, text: str) -> QVBoxLayout:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(12)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        box.addWidget(heading)
        body = QLabel(text)
        body.setObjectName("hint")
        body.setWordWrap(True)
        box.addWidget(body)
        self.pages.addWidget(page)
        return box

    def _build_sound(self) -> None:
        box = self._page(
            "Where should the sound come out?",
            "The music and the microphones both play through this device. Pick your "
            "speakers or amplifier, then play the test sound to check.",
        )
        outputs = devices.list_outputs()
        self.output.addItems([DEFAULT, *outputs])
        current = self.controller.settings.output_device
        self.output.setCurrentText(current if current in outputs else DEFAULT)
        self.output.activated.connect(self._output_chosen)
        box.addWidget(self.output)
        test = QPushButton("Play Test Sound")
        test.clicked.connect(lambda: self.controller.play_sfx("applause"))
        box.addWidget(test, alignment=Qt.AlignmentFlag.AlignLeft)
        box.addStretch()

    def _build_screen(self) -> None:
        box = self._page(
            "Which screen shows the music video?",
            "The video plays full screen on this display, and this console stays on the "
            "other one. With a single display the video opens in a window instead.",
        )
        self.screen_combo.addItem("Automatic (extended display)", -1)
        for i, screen in enumerate(QGuiApplication.screens()):
            size = screen.size()
            self.screen_combo.addItem(
                f"Display {i + 1}: {screen.name()} ({size.width()}x{size.height()})", i
            )
        self.screen_combo.setCurrentIndex(
            max(0, self.screen_combo.findData(self.controller.settings.mv_screen))
        )
        self.screen_combo.activated.connect(self._screen_chosen)
        box.addWidget(self.screen_combo)
        box.addStretch()

    def _build_microphone(self) -> None:
        box = self._page(
            "Check the first microphone",
            "Pick the microphone for channel 1 and say something into it. The bar moves "
            "when it is heard. More microphones and all the effects are on the Mixer page.",
        )
        inputs = devices.list_inputs()
        self.mic.addItems([DEFAULT, *inputs, OFF])
        strip = self.controller.settings.mics[0]
        if not strip.enabled:
            self.mic.setCurrentText(OFF)
        else:
            self.mic.setCurrentText(strip.device if strip.device in inputs else DEFAULT)
        self.mic.activated.connect(self._mic_chosen)
        box.addWidget(self.mic)
        box.addWidget(self.level)
        box.addWidget(self.heard)
        box.addStretch()

    # -- choices ------------------------------------------------------------

    def _output_chosen(self, _index: int) -> None:
        choice = self.output.currentText()
        self.controller.set_output_device(None if choice == DEFAULT else choice)

    def _screen_chosen(self, _index: int) -> None:
        self.controller.settings.mv_screen = int(self.screen_combo.currentData())
        self.controller.mixer_changed()
        self._place_mv()

    def _mic_chosen(self, _index: int) -> None:
        choice = self.mic.currentText()
        strip = self.controller.settings.mics[0]
        strip.enabled = choice != OFF
        if choice != OFF:
            strip.device = None if choice == DEFAULT else choice
        self._loudest = 0.0
        self.controller.restart_audio()

    def _show_level(self) -> None:
        audio = self.controller.audio
        peak = 0.0
        if audio is not None and audio.running:
            peak = float(audio.levels()["mics"][0])
        self._loudest = max(self._loudest, peak)
        self.level.setValue(min(100, int(peak**0.5 * 100)))
        if self.mic.currentText() == OFF:
            self.heard.setText("Channel 1 is off.")
        elif audio is None or not audio.running:
            self.heard.setText("The audio engine is not running. See the Mixer page.")
        elif self._loudest > 0.02:
            self.heard.setText("Heard you. The microphone works.")
        else:
            self.heard.setText("Nothing heard yet. Say something into the microphone.")

    # -- navigation ---------------------------------------------------------

    def go(self, index: int) -> None:
        index = max(0, min(index, self.pages.count() - 1))
        self.pages.setCurrentIndex(index)
        self.step_label.setText(f"STEP {index + 1} OF {len(STEPS)}  ·  {STEPS[index].upper()}")
        self.back.setEnabled(index > 0)
        last = index == self.pages.count() - 1
        self.next.setText("Finish" if last else "Next")
        if last:
            self._loudest = 0.0
            self._meter.start()
        else:
            self._meter.stop()

    def _advance(self) -> None:
        if self.pages.currentIndex() == self.pages.count() - 1:
            self.finish()
        else:
            self.go(self.pages.currentIndex() + 1)

    def finish(self) -> None:
        """Close for good: the wizard does not come back on its own after this."""
        self._meter.stop()
        self.controller.settings.setup_done = True
        self.controller.mixer_changed()
        self.accept()

    def reject(self) -> None:  # the window's close button and Esc
        self.finish()
