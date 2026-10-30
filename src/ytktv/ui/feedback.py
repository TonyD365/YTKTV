"""Bug reports and suggestions go to GitHub; nothing is ever sent without the user."""

from __future__ import annotations

import platform
import sys
import traceback
import urllib.parse
from types import TracebackType
from typing import Any

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QWidget

from ytktv import __version__

ISSUES = "https://github.com/TonyD365/YTKTV/issues/new"
BUG = f"{ISSUES}?template=bug_report.yml"
IDEA = f"{ISSUES}?template=feature_request.yml"
MAX_URL = 6000  # browsers and GitHub cut longer links


def open_url(url: str) -> None:
    QDesktopServices.openUrl(QUrl(url))


def crash_report_url(
    kind: type[BaseException], error: BaseException, trace: TracebackType | None
) -> str:
    """A new-issue link with the error filled in, for the user to read and send themselves."""
    lines = "".join(traceback.format_exception(kind, error, trace))[-3500:]
    body = (
        f"**What I was doing:**\n\n\n**Version:** YTKTV {__version__} on {platform.platform()}\n\n"
        f"```\n{lines}\n```\n"
    )
    query = urllib.parse.urlencode(
        {"title": f"Crash: {kind.__name__}: {str(error)[:80]}", "labels": "bug", "body": body}
    )
    return f"{ISSUES}?{query}"[:MAX_URL]


def install_crash_handler(parent: QWidget | None = None) -> None:
    """Ask, after an unexpected error, whether to report it on GitHub."""
    previous = sys.excepthook
    asked: set[str] = set()

    def handler(kind: type[BaseException], error: BaseException, trace: Any) -> None:
        previous(kind, error, trace)  # still logged as before
        key = f"{kind.__name__}:{error}"
        if key in asked or issubclass(kind, KeyboardInterrupt):
            return
        asked.add(key)  # ask once per kind of error, not in a loop
        answer = QMessageBox.question(
            parent,
            "Something went wrong",
            "YTKTV hit an unexpected error. Report it on GitHub? A page opens with the details"
            " filled in; you can read them and add what you were doing before sending.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            open_url(crash_report_url(kind, error, trace))

    sys.excepthook = handler
