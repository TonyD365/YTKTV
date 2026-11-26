"""The update windows: notes from the release, the security badge, the notice after."""

from __future__ import annotations

from ytktv.ui.icon import ICON_FILE
from ytktv.ui.update_dialog import (
    UpdateDialog,
    finished_update,
    is_security_update,
    release_notes,
    remember_update,
    show_finished_update,
)


def test_the_notes_leave_out_the_install_instructions():
    body = "## What's new\r\n\r\n- One\r\n\r\n## Install\r\n\r\nbrew ..."
    assert release_notes(body) == "## What's new\n\n- One"
    assert release_notes("- Only this") == "- Only this"


def test_a_security_release_is_marked(qtbot):
    assert is_security_update("### 🔒 Security: signed updates")
    assert not is_security_update("### 🛠 Fixes")
    dialog = UpdateDialog(
        app="YTKTV Desk", icon=ICON_FILE, version="4.7.2", current="4.7.1",
        notes="### 🛠 Fixes\n- Better", page_url="https://example.invalid", size=" (12 MB)",
    )  # fmt: skip
    qtbot.addWidget(dialog)
    assert dialog.title.text() == "YTKTV Desk 4.7.2"
    assert "12 MB" in dialog.subtitle.text() and "(" not in dialog.subtitle.text()
    assert not dialog.badge.isVisibleTo(dialog)


def test_the_notice_after_an_update_shows_once_and_only_for_that_version(qtbot, tmp_path):
    remember_update(tmp_path, "YTKTV", "4.7.1", "4.7.2")
    assert finished_update(tmp_path, "YTKTV", "4.7.1") is None  # the update did not go in
    remember_update(tmp_path, "YTKTV", "4.7.1", "4.7.2")
    notice = show_finished_update(tmp_path, "YTKTV", "YTKTV", ICON_FILE, "4.7.2", None)
    assert notice is not None and "up to date" in notice.title.text()
    notice.close()
    assert show_finished_update(tmp_path, "YTKTV", "YTKTV", ICON_FILE, "4.7.2", None) is None
