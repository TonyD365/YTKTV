"""Our own icons: every emoji the screens use has a drawing, and buttons swap them in."""

from __future__ import annotations

import xml.dom.minidom

from ytktv.icon_set import EMOJI, ICONS, split, svg


def test_every_icon_is_valid_svg_and_every_emoji_has_one():
    for name in ICONS:
        xml.dom.minidom.parseString(svg(name))
    assert set(EMOJI.values()) <= set(ICONS)


def test_split_takes_the_emoji_out():
    assert split("⚔️  PK Battle: Off") == ("swords", "PK Battle: Off")
    assert split("Plain") == (None, "Plain")


def test_buttons_and_labels_lose_their_emoji(qtbot):
    from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

    from ytktv.ui import icons

    box = QWidget()
    qtbot.addWidget(box)
    column = QVBoxLayout(box)
    button = QPushButton("🛎  Service")
    label = QLabel("🔒 Locked")
    column.addWidget(button)
    column.addWidget(label)
    icons.apply(box)
    assert button.text() == "Service" and not button.icon().isNull()
    assert "<img" in label.text() and "🔒" not in label.text()
