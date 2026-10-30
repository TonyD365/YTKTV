"""Keyboard, media keys and remote controls: play, skip and change the sound without a mouse.

Works in every YTKTV window. Most remotes (USB and Bluetooth remotes, air mice, a TV remote
through HDMI-CEC on a Raspberry Pi) send the same keys as a keyboard's media and arrow keys.
Keys typed into a text box are left alone.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QAbstractSpinBox, QApplication, QComboBox, QLineEdit, QTextEdit

from ytktv.core.controller import KTVController
from ytktv.core.models import VocalMode

K = Qt.Key
STEP = 5  # volume steps, out of 100

# (keys, what it does) — shown in Settings, so keep them in a readable order.
KEYS: tuple[tuple[tuple[Qt.Key, ...], str], ...] = (
    ((K.Key_Space, K.Key_MediaPlay, K.Key_MediaPause, K.Key_MediaTogglePlayPause, K.Key_Play),
     "Play / pause"),
    ((K.Key_N, K.Key_MediaNext, K.Key_Forward), "Next song"),
    ((K.Key_R, K.Key_MediaPrevious, K.Key_Back), "Sing it again"),
    ((K.Key_V, K.Key_Return, K.Key_Enter, K.Key_Select), "Original / instrumental"),
    ((K.Key_Up, K.Key_Plus, K.Key_Equal), "Music louder"),
    ((K.Key_Down, K.Key_Minus), "Music softer"),
    ((K.Key_BracketRight, K.Key_Right), "Key up"),
    ((K.Key_BracketLeft, K.Key_Left), "Key down"),
    ((K.Key_L,), "Lyrics on / off"),
    ((K.Key_S,), "Scoring on / off"),
)  # fmt: skip
KEY_NAMES = {
    K.Key_Space: "Space", K.Key_MediaPlay: "▶", K.Key_MediaTogglePlayPause: "⏯",
    K.Key_MediaNext: "⏭", K.Key_MediaPrevious: "⏮", K.Key_Return: "Enter / OK",
    K.Key_Up: "↑", K.Key_Down: "↓", K.Key_Right: "→", K.Key_Left: "←",
    K.Key_Plus: "+", K.Key_Minus: "−", K.Key_BracketRight: "]", K.Key_BracketLeft: "[",
    K.Key_N: "N", K.Key_R: "R", K.Key_V: "V", K.Key_L: "L", K.Key_S: "S",
}  # fmt: skip
TYPING = (QLineEdit, QTextEdit, QAbstractSpinBox)


def key_help() -> list[tuple[str, str]]:
    """(keys, action) rows for the Settings page."""
    rows = []
    for keys, action in KEYS:
        names = [KEY_NAMES[k] for k in keys if k in KEY_NAMES]
        rows.append(("  ".join(names), action))
    return rows


class RemoteKeys(QObject):
    """An application-wide key filter that turns keys into controller actions."""

    def __init__(self, controller: KTVController, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        c = controller
        actions: dict[str, Callable[[], None]] = {
            "Play / pause": c.toggle_pause,
            "Next song": c.skip,
            "Sing it again": c.replay,
            "Original / instrumental": self.toggle_vocals,
            "Music louder": lambda: c.set_volume("music", c.settings.music_volume + STEP),
            "Music softer": lambda: c.set_volume("music", c.settings.music_volume - STEP),
            "Key up": lambda: c.set_pitch(c.pitch + 1),
            "Key down": lambda: c.set_pitch(c.pitch - 1),
            "Lyrics on / off": lambda: c.set_show_lyrics(not c.settings.show_lyrics),
            "Scoring on / off": lambda: c.set_scoring(not c.settings.scoring),
        }
        self.by_key = {key: actions[name] for keys, name in KEYS for key in keys}

    def toggle_vocals(self) -> None:
        instrumental = self.controller.vocal_mode == VocalMode.INSTRUMENTAL
        mode = VocalMode.ORIGINAL if instrumental else VocalMode.INSTRUMENTAL
        self.controller.set_vocal_mode(mode)

    def handle(self, key: int, modifiers: Qt.KeyboardModifier) -> bool:
        """Run the action for *key*; False when it is not ours (or has Ctrl/Cmd/Alt)."""
        busy = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        if modifiers & (busy | Qt.KeyboardModifier.MetaModifier):
            return False
        action = self.by_key.get(Qt.Key(key))
        if action is None:
            return False
        action()
        return True

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt's name
        if event.type() != QEvent.Type.KeyPress or not isinstance(event, QKeyEvent):
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, TYPING) or (isinstance(focus, QComboBox) and focus.isEditable()):
            return False  # typing a song name, not controlling the music
        if event.isAutoRepeat() and event.key() not in (K.Key_Up, K.Key_Down):
            return True  # a held key does not skip ten songs
        return self.handle(event.key(), event.modifiers())
