"""Admin Settings of a room, edited on the staff terminal and applied by the room."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ytktv.rooms.admin import FIELDS, QUALITIES
from ytktv.smart_lights import KINDS as LIGHT_KINDS


class AdminSettingsDialog(QDialog):
    """Built from what the room reported; values() gives only what was changed."""

    def __init__(self, room: str, report: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Admin Settings · {room}")
        self.setMinimumWidth(560)
        self.current: dict[str, Any] = dict(report.get("settings") or {})
        column = QVBoxLayout(self)
        about = QLabel(
            f"YTKTV {report.get('version', '?')} · {report.get('separation', '')}".strip(" ·")
        )
        about.setObjectName("muted")
        about.setWordWrap(True)
        column.addWidget(about)
        form = QFormLayout()
        self.widgets: dict[str, QWidget] = {}
        for name, (label, _check) in FIELDS.items():
            if name not in self.current:
                continue
            widget = self._widget(name, self.current[name], report)
            self.widgets[name] = widget
            form.addRow(label, widget)
        column.addLayout(form)
        note = QLabel("Changes are applied by the room at once and noted in the Log.")
        note.setObjectName("muted")
        column.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        column.addWidget(buttons)

    def _widget(self, name: str, value: Any, report: dict[str, Any]) -> QWidget:
        if isinstance(value, bool):
            box = QCheckBox()
            box.setChecked(value)
            return box
        if name == "max_height":
            combo = QComboBox()
            for height in QUALITIES:
                combo.addItem(f"{height}p", height)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            return combo
        if name == "mv_screen":
            combo = QComboBox()
            combo.addItem("Automatic (extended display)", -1)
            for index, screen in enumerate(report.get("screens") or []):
                combo.addItem(f"{index + 1}: {screen}", index)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            return combo
        if name == "output_device":
            combo = QComboBox()
            combo.addItem("System default", None)
            for device in report.get("outputs") or []:
                combo.addItem(str(device), str(device))
            combo.setCurrentIndex(max(0, combo.findData(value)))
            return combo
        if name == "smart_lights":
            combo = QComboBox()
            for key, text in LIGHT_KINDS.items():
                combo.addItem(text, key)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            return combo
        if name == "local_folders":
            edit = QPlainTextEdit("\n".join(value or []))
            edit.setPlaceholderText("One folder per line, as a path on the room's computer")
            edit.setMaximumHeight(90)
            return edit
        return QLineEdit("" if value is None else str(value))

    def _value(self, name: str) -> Any:
        widget = self.widgets[name]
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QComboBox):
            return widget.currentData()
        if isinstance(widget, QPlainTextEdit):
            return [line.strip() for line in widget.toPlainText().splitlines() if line.strip()]
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        return None

    def values(self) -> dict[str, Any]:
        """Only the settings that were changed."""
        values = {name: self._value(name) for name in self.widgets}
        return {n: v for n, v in values.items() if v != self.current.get(n)}
