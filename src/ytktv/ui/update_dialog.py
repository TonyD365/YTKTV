"""The update windows: the one that offers a downloaded update, and the one that says it went in.

UpdateDialog shows the new version with its release notes, taken from the GitHub release
itself, and the three steps the download went through (downloaded, signature checked,
ready). The swap happens after the app quits, so nothing of the app can be shown then;
instead the next start shows UpdatedNotice once, which says the update is in.
Both YTKTV and YTKTV Desk use them, each with its own name and icon.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ytktv.i18n import t
from ytktv.ui import theme

log = logging.getLogger(__name__)

# The release workflow appends how to install YTKTV to the notes; in the app that is noise.
_TAIL_HEADINGS = ("## install", "## 安装")


def release_notes(body: str) -> str:
    """The release's notes as the app shows them: without the install instructions."""
    lines = body.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if line.strip().lower().startswith(_TAIL_HEADINGS):
            lines = lines[:i]
            break
    return "\n".join(lines).strip()


def is_security_update(body: str) -> bool:
    return "security" in body.lower() or "安全" in body


def _icon(path: Path, size: int) -> QLabel:
    label = QLabel()
    pixmap = QPixmap(str(path))
    if not pixmap.isNull():
        label.setPixmap(
            pixmap.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
    label.setFixedSize(size, size)
    return label


def _button(text: str, primary: bool) -> QPushButton:
    button = QPushButton(text)
    button.setMinimumHeight(44)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if primary:
        button.setStyleSheet(
            f"QPushButton {{ padding: 10px 24px; border: none; border-radius: 10px;"
            f" font-weight: 700; color: #ffffff;"
            f" background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {theme.PINK}, stop:1 {theme.PURPLE}); }}"
        )
    else:
        button.setStyleSheet(
            f"QPushButton {{ padding: 10px 20px; border-radius: 10px; font-weight: 600;"
            f" color: {theme.TEXT}; background: {theme.PANEL}; border: 1px solid {theme.LINE}; }}"
        )
    return button


class UpdateDialog(QDialog):
    """Offers a downloaded, verified update; accepted means install it now."""

    def __init__(
        self,
        *,
        app: str,
        icon: Path,
        version: str,
        current: str,
        notes: str,
        page_url: str,
        size: str = "",
        warnings: list[str] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("Update ready"))
        self.setMinimumSize(640, 520)
        self.setStyleSheet(
            f"QDialog {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {theme.NEON['BG_TOP']}, stop:0.45 {theme.BG},"
            f" stop:1 {theme.NEON['BG_BOTTOM']}); color: {theme.TEXT}; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 22)
        root.setSpacing(16)

        header = QHBoxLayout()
        header.setSpacing(16)
        header.addWidget(_icon(icon, 72))
        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.headline = QLabel(t("Ready to install"))
        self.headline.setStyleSheet(
            f"color: {theme.CYAN}; font-size: 12px; font-weight: 700; letter-spacing: 1px;"
        )
        self.title = QLabel(f"{app} {version}")
        self.title.setStyleSheet("font-size: 28px; font-weight: 800;")
        line = t("You have {current}", current=current) + (
            f"  ·  {size.strip(' ()')}" if size else ""
        )
        self.subtitle = QLabel(line)
        self.subtitle.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        for widget in (self.headline, self.title, self.subtitle):
            titles.addWidget(widget)
        header.addLayout(titles, 1)
        self.badge = QLabel(t("Security update"))
        self.badge.setStyleSheet(
            f"color: {theme.GREEN}; border: 1px solid {theme.GREEN}; border-radius: 12px;"
            " padding: 4px 12px; font-size: 12px; font-weight: 700;"
        )
        self.badge.setVisible(is_security_update(notes))
        header.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header)

        bar = QHBoxLayout()
        caption = QLabel(t("What's new · from the GitHub release"))
        caption.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px; font-weight: 600;")
        bar.addWidget(caption, 1)
        full = QLabel(
            f'<a href="{page_url}" style="color:{theme.CYAN}">{t("Full release notes")}</a>'
        )
        full.setTextFormat(Qt.TextFormat.RichText)
        full.setOpenExternalLinks(True)
        bar.addWidget(full)
        root.addLayout(bar)

        self.notes = QTextBrowser()
        self.notes.setOpenLinks(False)
        self.notes.anchorClicked.connect(QDesktopServices.openUrl)
        self.notes.setMarkdown(release_notes(notes) or t("No release notes."))
        self.notes.setStyleSheet(
            f"QTextBrowser {{ background: {theme.PANEL}; color: {theme.TEXT};"
            f" border: 1px solid {theme.LINE}; border-radius: 12px; padding: 12px;"
            " font-size: 14px; }"
        )
        root.addWidget(self.notes, 1)

        steps = QHBoxLayout()
        steps.setSpacing(22)
        for text in (t("Downloaded"), t("Signature verified"), t("Ready")):
            step = QLabel(f"✓  {text}")
            step.setStyleSheet(f"color: {theme.GREEN}; font-size: 13px; font-weight: 600;")
            steps.addWidget(step)
        steps.addStretch(1)
        root.addLayout(steps)

        for warning in warnings or []:
            note = QLabel(warning)
            note.setWordWrap(True)
            note.setStyleSheet(f"color: {theme.GOLD}; font-size: 13px;")
            root.addWidget(note)

        buttons = QHBoxLayout()
        hint = QLabel(t("{app} closes, updates and opens again.", app=app))
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        buttons.addWidget(hint, 1)
        self.later = _button(t("Later"), primary=False)
        self.install = _button(t("Restart to update"), primary=True)
        self.later.clicked.connect(self.reject)
        self.install.clicked.connect(self.accept)
        buttons.addWidget(self.later)
        buttons.addWidget(self.install)
        root.addLayout(buttons)
        self.install.setDefault(True)


# --- after the restart ---------------------------------------------------------------------


def remember_update(folder: Path, app: str, current: str, version: str) -> None:
    """Note, just before installing, which update is going in (read on the next start)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{app}-updating.json").write_text(
            json.dumps({"from": current, "to": version}), encoding="utf-8"
        )
    except OSError:
        log.info("could not note the update that is going in")


def finished_update(folder: Path, app: str, running: str) -> tuple[str, str] | None:
    """(from, to) when this start is the first one after an update to *running*; once."""
    path = folder / f"{app}-updating.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    path.unlink(missing_ok=True)
    if not isinstance(data, dict) or data.get("to") != running:
        return None  # the update did not go in (or another one did): say nothing
    return str(data.get("from") or ""), running


class UpdatedNotice(QDialog):
    """A small window on the first start after an update: it went in, all files checked."""

    def __init__(
        self, *, app: str, icon: Path, old: str, new: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(t("{app} is up to date", app=app))
        self.setFixedWidth(420)
        self.setStyleSheet(
            f"QDialog {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,"
            f" stop:0 {theme.NEON['BG_TOP']}, stop:0.6 {theme.BG},"
            f" stop:1 {theme.NEON['BG_BOTTOM']}); color: {theme.TEXT}; }}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(14)
        header = QHBoxLayout()
        header.setSpacing(14)
        header.addWidget(_icon(icon, 56))
        titles = QVBoxLayout()
        self.title = QLabel(t("{app} is up to date", app=app))
        self.title.setStyleSheet("font-size: 20px; font-weight: 800;")
        versions = QLabel(f"{old} → {new}" if old else new)
        versions.setStyleSheet(f"color: {theme.MUTED}; font-size: 13px;")
        titles.addWidget(self.title)
        titles.addWidget(versions)
        header.addLayout(titles, 1)
        root.addLayout(header)
        for text in (t("Files replaced"), t("Every new file checked")):
            step = QLabel(f"✓  {text}")
            step.setStyleSheet(f"color: {theme.GREEN}; font-size: 13px; font-weight: 600;")
            root.addWidget(step)
        close = _button(t("OK"), primary=True)
        close.clicked.connect(self.accept)
        root.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        # It needs no answer: it goes by itself after a while.
        QTimer.singleShot(8000, self.accept)


def show_finished_update(
    folder: Path, app: str, name: str, icon: Path, running: str, parent: QWidget | None
) -> UpdatedNotice | None:
    done = finished_update(folder, app, running)
    if done is None:
        return None
    notice = UpdatedNotice(app=name, icon=icon, old=done[0], new=done[1], parent=parent)
    notice.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    notice.show()
    return notice
