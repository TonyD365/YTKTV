"""The Desk's language: saved with the Desk's settings, or on a staff terminal's own computer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QComboBox, QFrame, QLabel, QVBoxLayout

from ytktv import i18n
from ytktv.config import data_dir
from ytktv.i18n import N_, t

log = logging.getLogger(__name__)

SETTING = "language"
RESTART_NOTE = N_("The new language applies after restarting YTKTV Desk.")


def local_path() -> Path:
    return data_dir() / "desk-language.json"


def load_local(path: Path | None = None) -> str:
    try:
        data = json.loads((path or local_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("language", "")) if isinstance(data, dict) else ""


def save_local(code: str, path: Path | None = None) -> None:
    target = path or local_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"language": code}), encoding="utf-8")
    except OSError:
        log.warning("could not save the language", exc_info=True)


def apply(store: Any = None, path: Path | None = None) -> str:
    """Set the language before any window is built.

    With the Desk's own store it is that Desk's setting; a staff terminal (no store here) keeps
    its choice on its own computer. Empty or unknown follows the system's language.
    """
    code = load_local(path) if store is None else store.setting(SETTING, "")
    return i18n.set_language(code)


class LanguageSettings(QFrame):
    """The language picker; it takes effect after a restart."""

    def __init__(self, store: Any, local: bool = False, path: Path | None = None) -> None:
        super().__init__()
        self.store, self.local, self.path = store, local, path
        self.setObjectName("panel")
        column = QVBoxLayout(self)
        column.setContentsMargins(24, 20, 24, 20)
        head = QLabel(t("LANGUAGE"))
        head.setObjectName("panelHead")
        self.choice = QComboBox()
        for code, name in i18n.LANGUAGES.items():
            self.choice.addItem(name, code)
        saved = load_local(path) if local else store.setting(SETTING, "")
        self.choice.setCurrentIndex(max(0, self.choice.findData(i18n.resolve(saved))))
        self.choice.activated.connect(self._chosen)
        self.note = QLabel()
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        self.note.hide()
        for widget in (head, self.choice, self.note):
            column.addWidget(widget)

    def _chosen(self, _index: int) -> None:
        code = str(self.choice.currentData())
        if self.local:
            save_local(code, self.path)
        else:
            self.store.set_setting(SETTING, code)
        self.note.setText(i18n.t_in(code, RESTART_NOTE))
        self.note.show()
