"""Settings → Save Diagnostics, for YTKTV and YTKTV Desk."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from ytktv.i18n import t


def save_diagnostics(parent: QWidget, app: str, path: str | None, **details: Any) -> str:
    """Ask where (unless *path* is given), write the diagnostics zip, and say what to do next."""
    from ytktv import diagnostics

    if path is None:
        suggested = str(Path.home() / "Desktop" / diagnostics.default_name(app))
        path, _ = QFileDialog.getSaveFileName(
            parent, t("Save diagnostics"), suggested, "Zip (*.zip)"
        )
        if not path:
            return ""
        saved = diagnostics.save(Path(path), app, **details)
        QMessageBox.information(
            parent,
            t("Diagnostics saved"),
            t(
                "Saved {name}. Attach it to a new issue at {issues} and say what happened.",
                name=saved.name,
                issues=diagnostics.ISSUES,
            ),
        )
        return str(saved)
    return str(diagnostics.save(Path(path), app, **details))
