"""The KTV console look: big touch targets in one of a few colour themes.

Neon (the dark room with pink and cyan accents) is the default. The module-level colour names
(PINK, CYAN, ...) are the current theme's: apply() swaps them, and code that paints reads them
as theme.PINK at paint time, so a new theme shows on the next repaint.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

# Every colour a theme sets. PINK is the main accent, CYAN the second one, PURPLE the third.
NEON: dict[str, str] = {
    "BG": "#0d0720",
    "PANEL": "#1a1035",
    "PANEL_2": "#241650",
    "LINE": "#3a2a70",
    "TEXT": "#f3eeff",
    "MUTED": "#a99bd6",
    "PINK": "#ff3d9a",
    "CYAN": "#2ee6ff",
    "PURPLE": "#8b5cff",
    "GOLD": "#ffc94d",
    "GREEN": "#5dffb0",
    "DANGER": "#ff5470",
    "BG_TOP": "#1b0b3d",
    "BG_BOTTOM": "#07101f",
    "BAR_RGB": "10, 5, 24",
    "HOVER_RGB": "139, 92, 255",
    "TIP_BG": "#000",
    "KEY_TOP": "#3b2a6e",
    "KEY_BOTTOM": "#1c1240",
    "DISABLED": "#6b5f93",
    "DANGER_BG": "#4a1830",
    "GREEN_EDGE": "#2b8a62",
    "GOLD_EDGE": "#8a6a1c",
    "CYAN_EDGE": "#1c6f8a",
    "CTRL_TOP": "#34207a",
    "CTRL_BOTTOM": "#1c1146",
    "CTRL_EDGE": "#4c379c",
}

THEMES: dict[str, dict[str, str]] = {
    "Neon": NEON,
    "Midnight": {  # calm: deep blue-grey with a soft teal
        **NEON,
        "BG": "#0e141b",
        "PANEL": "#16202a",
        "PANEL_2": "#1e2b38",
        "LINE": "#2c3d4f",
        "TEXT": "#e8eef4",
        "MUTED": "#8fa3b8",
        "PINK": "#4fd1c5",
        "CYAN": "#7aa2f7",
        "PURPLE": "#3d6ea8",
        "BG_TOP": "#132030",
        "BG_BOTTOM": "#0a0f14",
        "BAR_RGB": "8, 12, 18",
        "HOVER_RGB": "61, 110, 168",
        "KEY_TOP": "#2a3b4e",
        "KEY_BOTTOM": "#16202a",
        "DISABLED": "#5b6b7c",
        "DANGER_BG": "#3a1c24",
        "CTRL_TOP": "#243447",
        "CTRL_BOTTOM": "#141d27",
        "CTRL_EDGE": "#36506b",
    },
    "Lounge": {  # warm: dark brown with gold and amber
        **NEON,
        "BG": "#16100a",
        "PANEL": "#221911",
        "PANEL_2": "#2e2216",
        "LINE": "#4a3824",
        "TEXT": "#f6ecdc",
        "MUTED": "#bfa888",
        "PINK": "#e0a43a",
        "CYAN": "#f2d29b",
        "PURPLE": "#9c5b2e",
        "BG_TOP": "#2a1a0c",
        "BG_BOTTOM": "#0d0905",
        "BAR_RGB": "18, 12, 6",
        "HOVER_RGB": "156, 91, 46",
        "KEY_TOP": "#4a3420",
        "KEY_BOTTOM": "#241a10",
        "DISABLED": "#7c6a55",
        "DANGER_BG": "#45201a",
        "CTRL_TOP": "#3e2b18",
        "CTRL_BOTTOM": "#1e160d",
        "CTRL_EDGE": "#6b4e2c",
    },
    "Daylight": {  # light and high contrast, for bright rooms
        **NEON,
        "BG": "#f4f5f8",
        "PANEL": "#ffffff",
        "PANEL_2": "#e4e7ee",
        "LINE": "#9aa3b5",
        "TEXT": "#0b0f1a",
        "MUTED": "#3d4557",
        "PINK": "#c2185b",
        "CYAN": "#00639b",
        "PURPLE": "#4a3aa8",
        "GOLD": "#8a5a00",
        "GREEN": "#08734a",
        "DANGER": "#b3261e",
        "BG_TOP": "#ffffff",
        "BG_BOTTOM": "#dfe3ec",
        "BAR_RGB": "255, 255, 255",
        "HOVER_RGB": "74, 58, 168",
        "TIP_BG": "#ffffff",
        "KEY_TOP": "#ffffff",
        "KEY_BOTTOM": "#e4e7ee",
        "DISABLED": "#8a91a0",
        "DANGER_BG": "#fbe2e0",
        "GREEN_EDGE": "#08734a",
        "GOLD_EDGE": "#8a5a00",
        "CYAN_EDGE": "#00639b",
        "CTRL_TOP": "#ffffff",
        "CTRL_BOTTOM": "#dde1ea",
        "CTRL_EDGE": "#9aa3b5",
    },
}
DEFAULT_THEME = "Neon"
LIGHT_THEMES = {"Daylight"}

BG = NEON["BG"]
PANEL = NEON["PANEL"]
PANEL_2 = NEON["PANEL_2"]
LINE = NEON["LINE"]
TEXT = NEON["TEXT"]
MUTED = NEON["MUTED"]
PINK = NEON["PINK"]
CYAN = NEON["CYAN"]
PURPLE = NEON["PURPLE"]
GOLD = NEON["GOLD"]
GREEN = NEON["GREEN"]
DANGER = NEON["DANGER"]
current = DEFAULT_THEME
logo: Path | None = None  # the venue's logo picture, shown on the home and idle screens

_TEMPLATE = """
* {{ font-family: "SF Pro Display", "Segoe UI", "Helvetica Neue", "PingFang SC",
     "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; }}
QWidget {{ color: {TEXT}; font-size: 14px; }}
QMainWindow {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 {BG_TOP}, stop:0.5 {BG}, stop:1 {BG_BOTTOM}); }}
QToolTip {{ background: {TIP_BG}; color: {TEXT}; border: 1px solid {CYAN}; padding: 4px 8px; }}

#topBar {{ background: rgba({BAR_RGB}, 0.75); border-bottom: 2px solid {PINK}; }}
#logo {{ font-size: 34px; font-weight: 900; letter-spacing: 4px; color: {PINK}; }}
#logoSub {{ font-size: 10px; letter-spacing: 3px; color: {CYAN}; font-weight: 700; }}
#caption {{ font-size: 10px; letter-spacing: 2px; color: {CYAN}; font-weight: 800; }}
#nowTitle {{ font-size: 18px; font-weight: 800; }}
#nextTitle {{ font-size: 14px; font-weight: 600; color: {MUTED}; }}
#clock {{ font-size: 26px; font-weight: 300; color: {TEXT}; }}
#timeLabel {{ font-size: 12px; color: {MUTED}; }}
#qrHint {{ font-size: 10px; color: {MUTED}; }}

QProgressBar {{ background: {PANEL_2}; border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {PINK}, stop:1 {CYAN}); }}

#navBar {{ background: rgba({BAR_RGB}, 0.6); border-bottom: 1px solid {LINE}; }}
#navBar QPushButton {{ padding: 14px 16px; border: none; border-bottom: 4px solid transparent;
    font-size: 15px; font-weight: 700; color: {MUTED}; background: transparent; }}
#navBar QPushButton:hover {{ color: {TEXT}; background: rgba({HOVER_RGB}, 0.15); }}
#navBar QPushButton:checked {{ color: {TEXT}; border-bottom: 4px solid {PINK}; }}
#tile {{ border-radius: 18px; color: white; font-size: 22px; font-weight: 800; padding: 14px; }}
#tile:hover {{ border: 3px solid white; }}
#tile:pressed {{ padding-top: 17px; }}
#key {{ font-size: 20px; font-weight: 800; border-radius: 10px; color: {TEXT};
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {KEY_TOP}, stop:1 {KEY_BOTTOM});
    border: 1px solid {PINK}; }}
#key:pressed {{ background: {PINK}; }}
#reaction {{ font-size: 22px; padding: 6px 0; border-radius: 12px; }}
#homeNow {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 18px; }}
#homeCover {{ background: #000; border-radius: 12px; }}
#homeTitle {{ font-size: 20px; font-weight: 800; }}
#homeRow {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 12px; padding: 10px 14px;
    font-size: 15px; }}

#pageTitle {{ font-size: 24px; font-weight: 900; letter-spacing: 1px; }}
#hint {{ color: {MUTED}; font-size: 14px; }}

QLineEdit {{ background: {PANEL}; border: 2px solid {LINE}; border-radius: 14px; padding: 12px 18px;
    font-size: 18px; selection-background-color: {PURPLE}; }}
QLineEdit:focus {{ border-color: {CYAN}; }}

QPushButton {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 12px; padding: 10px 16px;
    font-weight: 700; }}
QPushButton:hover {{ border-color: {PURPLE}; }}
QPushButton:pressed {{ background: {PURPLE}; }}
QPushButton:disabled {{ color: {DISABLED}; }}
QPushButton[accent="true"] {{ border: none; color: white;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {PINK}, stop:1 {PURPLE}); }}
QPushButton[accent="true"]:pressed {{ background: {PINK}; }}
QPushButton[danger="true"] {{ background: {DANGER_BG}; border-color: {DANGER}; }}
QPushButton[chip="true"] {{ border-radius: 17px; padding: 7px 16px; font-weight: 600; background: {PANEL}; }}
QPushButton[chip="true"]:checked {{ background: {PURPLE}; border-color: {PURPLE}; }}
QPushButton[small="true"] {{ padding: 7px 12px; border-radius: 9px; font-size: 12px; min-width: 64px; }}

#songRow {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 14px; }}
#songRow:hover {{ border-color: {PURPLE}; }}
#songTitle {{ font-size: 15px; font-weight: 700; }}
#songSub {{ font-size: 12px; color: {MUTED}; }}
#tag {{ font-size: 11px; font-weight: 700; border-radius: 7px; padding: 2px 8px;
    border: 1px solid {LINE}; color: {MUTED}; }}
#tag[kind="ready"] {{ color: {GREEN}; border-color: {GREEN_EDGE}; }}
#tag[kind="busy"] {{ color: {GOLD}; border-color: {GOLD_EDGE}; }}
#tag[kind="singer"] {{ color: {CYAN}; border-color: {CYAN_EDGE}; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 40px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 4px; min-width: 40px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

#controlBar {{ background: rgba({BAR_RGB}, 0.9); border-top: 2px solid {PURPLE}; }}
#controlBar QPushButton {{ padding: 0; font-size: 12px; font-weight: 800;
    border-radius: 12px; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {CTRL_TOP}, stop:1 {CTRL_BOTTOM});
    border: 1px solid {CTRL_EDGE}; }}
#controlBar QPushButton:hover {{ border-color: {CYAN}; }}
#controlBar QPushButton:pressed {{ background: {PURPLE}; }}
#controlBar QPushButton:checked {{ border: none; color: white;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {PINK}, stop:1 {PURPLE}); }}
#controlBar QPushButton[round="true"] {{ border-radius: 22px; font-size: 18px; }}
#controlBar QPushButton[gold="true"] {{ color: #2a1a00; border: none;
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #ffe08a, stop:1 #e0a020); }}
#readout {{ font-size: 17px; font-weight: 800; color: {CYAN}; }}
#groupLabel {{ font-size: 9px; letter-spacing: 2px; color: {MUTED}; font-weight: 800; }}

QSlider::groove:horizontal {{ height: 6px; background: {PANEL_2}; border-radius: 3px; }}
QSlider::sub-page:horizontal {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {PURPLE}, stop:1 {PINK}); }}
QSlider::handle:horizontal {{ width: 20px; height: 20px; margin: -8px 0; border-radius: 10px;
    background: white; border: 2px solid {PINK}; }}

QComboBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; padding: 8px 12px; min-height: 22px; }}
QComboBox:hover {{ border-color: {PURPLE}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QAbstractSpinBox {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; padding: 6px 10px; color: {TEXT}; }}
QAbstractSpinBox:focus {{ border-color: {CYAN}; }}
QListWidget {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 10px; padding: 4px; color: {TEXT}; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {PURPLE}; color: white; }}
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {PURPLE}; selection-background-color: {PURPLE};
    outline: none; }}
#grip {{ color: {MUTED}; font-size: 22px; }}
#grip:hover {{ color: {TEXT}; }}
#songRow[dragging="true"] {{ border-color: {PINK}; }}
#dropMarker {{ background: {PINK}; border-radius: 2px; }}
QMenu {{ background: {PANEL}; border: 1px solid {PURPLE}; padding: 6px; }}
QMenu::item {{ padding: 9px 22px; border-radius: 6px; font-size: 14px; font-weight: 600; color: {TEXT}; }}
QMenu::item:selected {{ background: {PURPLE}; }}
QMenu::item:checked {{ color: {PINK}; }}
QMenu::item:checked:selected {{ color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 6px 8px; }}
#suggestions {{ background: {PANEL}; border: 1px solid {PURPLE}; outline: none; padding: 4px;
    selection-background-color: {PURPLE}; selection-color: {TEXT}; }}
#suggestions::item {{ padding: 7px 12px; }}
QCheckBox {{ spacing: 10px; font-size: 15px; }}
QCheckBox::indicator {{ width: 22px; height: 22px; border-radius: 6px; border: 2px solid {LINE}; background: {PANEL}; }}
QCheckBox::indicator:checked {{ background: {PINK}; border-color: {PINK}; }}
#settingsCard {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 16px; }}
#settingsHead {{ font-size: 12px; letter-spacing: 2px; color: {CYAN}; font-weight: 800; }}

#toast {{ background: rgba(0, 0, 0, 0.85); border: 1px solid {CYAN}; border-radius: 18px;
    padding: 9px 20px; font-size: 14px; font-weight: 600; }}
#toast[error="true"] {{ border-color: {DANGER}; }}
QMessageBox, QDialog {{ background: {PANEL}; }}
"""


_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def valid_accent(colour: str) -> bool:
    """A venue's own accent colour must be a #rrggbb colour."""
    return bool(_HEX.match(colour or ""))


def palette(name: str = DEFAULT_THEME, accent: str = "") -> dict[str, str]:
    """The colours of a theme, with the venue's accent (if any) as the main accent."""
    colours = dict(THEMES.get(name, NEON))
    if valid_accent(accent):
        colours["PINK"] = accent.lower()
    return colours


def build(name: str = DEFAULT_THEME, accent: str = "") -> str:
    """The style sheet for a theme."""
    return _TEMPLATE.format(**palette(name, accent))


STYLESHEET = build()
_NAMED = [
    "BG",
    "PANEL",
    "PANEL_2",
    "LINE",
    "TEXT",
    "MUTED",
    "PINK",
    "CYAN",
    "PURPLE",
    "GOLD",
    "GREEN",
    "DANGER",
]


def apply(name: str = DEFAULT_THEME, accent: str = "") -> str:
    """Make a theme the current one (colour names and STYLESHEET); returns the style sheet."""
    global STYLESHEET, current
    colours = palette(name, accent)
    module = globals()
    for key in _NAMED:
        module[key] = colours[key]
    current = name if name in THEMES else DEFAULT_THEME
    STYLESHEET = build(name, accent)
    return STYLESHEET


def accent_of(name: str = DEFAULT_THEME, accent: str = "") -> str:
    """The main accent colour, for the phone page."""
    return palette(name, accent)["PINK"]


TEXT_SIZES = {"Normal": 1.0, "Large": 1.25, "Extra large": 1.5}
_FONT_SIZE = re.compile(r"font-size:\s*(\d+)px")


def stylesheet(text_size: str = "Normal") -> str:
    """STYLESHEET with every font size scaled up, for people who read better large."""
    factor = TEXT_SIZES.get(text_size, 1.0)
    if factor == 1.0:
        return STYLESHEET
    return _FONT_SIZE.sub(lambda m: f"font-size: {round(int(m.group(1)) * factor)}px", STYLESHEET)


# -- the venue's logo ----------------------------------------------------------------------

LOGO_TYPES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_MAX_SIDE = 4096


def import_logo(source: str | Path, folder: Path) -> Path:
    """Check a picture and copy it into the app's data folder as the venue logo.

    Raises ValueError with a message for people when it is not a usable picture.
    """
    from PySide6.QtGui import QImageReader

    path = Path(source)
    suffix = path.suffix.lower()
    if suffix not in LOGO_TYPES:
        raise ValueError("The logo must be a PNG, JPEG, WebP, GIF or BMP picture.")
    if not path.is_file():
        raise ValueError("That file could not be found.")
    if path.stat().st_size > LOGO_MAX_BYTES:
        raise ValueError("The logo must be 2 MB or smaller.")
    reader = QImageReader(str(path))
    size = reader.size()
    kind = bytes(reader.format().data()).decode(errors="replace").lower()
    if not reader.canRead() or kind not in {"png", "jpg", "jpeg", "webp", "gif", "bmp"}:
        raise ValueError("That file is not a picture YTKTV can read.")
    if size.width() > LOGO_MAX_SIDE or size.height() > LOGO_MAX_SIDE:
        raise ValueError("The logo must be at most 4096 pixels on each side.")
    if reader.read().isNull():
        raise ValueError("That file is not a picture YTKTV can read.")
    for old in folder.glob("venue-logo.*"):
        old.unlink(missing_ok=True)
    target = folder / f"venue-logo{suffix}"
    shutil.copyfile(path, target)
    return target


def logo_file(name: str, folder: Path) -> Path | None:
    """The stored venue logo, if it is set and still there."""
    if not name or Path(name).name != name or not name.startswith("venue-logo."):
        return None
    path = folder / name
    return path if path.is_file() else None
