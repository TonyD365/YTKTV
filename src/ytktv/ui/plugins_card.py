"""The Plugins card in Settings: turn add-ons on or off after seeing what they ask for."""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QMessageBox, QVBoxLayout

from ytktv import plugins as plugin_api
from ytktv.i18n import t
from ytktv.plugins import PluginInfo, PluginManager


def describe(info: PluginInfo) -> str:
    name = f"{info.name} {info.version}".strip()
    asks = ", ".join(t(plugin_api.PERMISSIONS[p]).lower() for p in info.permissions)
    state = f" — {info.error}" if info.error else (t(" — running") if info.running else "")
    return t(
        "{name}: {description}. Asks to: {asks}.{state}",
        name=name,
        description=info.description or t("no description"),
        asks=asks or t("nothing"),
        state=state,
    )


class PluginsCard(QFrame):
    def __init__(self, manager: PluginManager) -> None:
        super().__init__()
        self.manager = manager
        self.setObjectName("settingsCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)
        head = QLabel(t("PLUGINS"))
        head.setObjectName("settingsHead")
        layout.addWidget(head)
        note = QLabel(
            t(
                "Add-ons from other developers. Install one with pip, or drop a .py "
                "file into {value}. Only turn on plugins you trust; changes take "
                "effect when YTKTV starts again.",
                value=manager.folder / "plugins",
            )
        )
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.boxes: dict[str, QCheckBox] = {}
        for info in manager.plugins.values():
            box = QCheckBox(describe(info))
            box.setChecked(info.enabled)
            box.setEnabled(not info.error or info.enabled)
            box.toggled.connect(lambda on, key=info.key: self.toggle(key, on))
            layout.addWidget(box)
            self.boxes[info.key] = box
        if not manager.plugins:
            empty = QLabel(t("No plugins installed."))
            empty.setObjectName("muted")
            layout.addWidget(empty)

    def toggle(self, key: str, on: bool) -> None:
        info = self.manager.plugins[key]
        if on and not self.confirm(info):
            box = self.boxes[key]
            box.blockSignals(True)
            box.setChecked(False)
            box.blockSignals(False)
            return
        self.manager.set_enabled(key, on)

    def confirm(self, info: PluginInfo) -> bool:
        asks = "\n".join(f"• {t(plugin_api.PERMISSIONS[p])}" for p in info.permissions)
        asks = asks or t("• Nothing")
        answer = QMessageBox.question(
            self,
            t("Turn on plugin?"),
            t(
                "{name} asks to:\n{asks}\n\nA plugin runs with this computer's access. "
                "Only turn it on if you trust where it came from.",
                name=info.name,
                asks=asks,
            ),
        )
        return answer == QMessageBox.StandardButton.Yes
