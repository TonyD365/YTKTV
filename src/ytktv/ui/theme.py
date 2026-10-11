"""The KTV console look: dark room, neon accents, big touch targets."""

from __future__ import annotations

BG = "#0d0720"
PANEL = "#1a1035"
PANEL_2 = "#241650"
LINE = "#3a2a70"
TEXT = "#f3eeff"
MUTED = "#a99bd6"
PINK = "#ff3d9a"
CYAN = "#2ee6ff"
PURPLE = "#8b5cff"
GOLD = "#ffc94d"
GREEN = "#5dffb0"
DANGER = "#ff5470"

STYLESHEET = f"""
* {{ font-family: "SF Pro Display", "Segoe UI", "Helvetica Neue", "PingFang SC",
     "Microsoft YaHei", "Noto Sans CJK SC", sans-serif; }}
QWidget {{ color: {TEXT}; font-size: 14px; }}
QMainWindow, #root {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
    stop:0 #1b0b3d, stop:0.5 {BG}, stop:1 #07101f); }}
QToolTip {{ background: #000; color: {TEXT}; border: 1px solid {CYAN}; padding: 4px 8px; }}

#topBar {{ background: rgba(10, 5, 24, 0.75); border-bottom: 2px solid {PINK}; }}
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

#navBar {{ background: rgba(10, 5, 24, 0.6); border-right: 1px solid {LINE}; }}
#navBar QPushButton {{ text-align: left; padding: 16px 18px; border: none; border-left: 4px solid transparent;
    font-size: 16px; font-weight: 700; color: {MUTED}; background: transparent; }}
#navBar QPushButton:hover {{ color: {TEXT}; background: rgba(139, 92, 255, 0.15); }}
#navBar QPushButton:checked {{ color: {TEXT}; border-left: 4px solid {PINK};
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(255,61,154,0.35), stop:1 rgba(255,61,154,0)); }}

#pageTitle {{ font-size: 24px; font-weight: 900; letter-spacing: 1px; }}
#hint {{ color: {MUTED}; font-size: 14px; }}

QLineEdit {{ background: {PANEL}; border: 2px solid {LINE}; border-radius: 14px; padding: 12px 18px;
    font-size: 18px; selection-background-color: {PURPLE}; }}
QLineEdit:focus {{ border-color: {CYAN}; }}

QPushButton {{ background: {PANEL_2}; border: 1px solid {LINE}; border-radius: 12px; padding: 10px 16px;
    font-weight: 700; }}
QPushButton:hover {{ border-color: {PURPLE}; }}
QPushButton:pressed {{ background: {PURPLE}; }}
QPushButton:disabled {{ color: #6b5f93; }}
QPushButton[accent="true"] {{ border: none; color: white;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {PINK}, stop:1 {PURPLE}); }}
QPushButton[accent="true"]:pressed {{ background: {PINK}; }}
QPushButton[danger="true"] {{ background: #4a1830; border-color: {DANGER}; }}
QPushButton[chip="true"] {{ border-radius: 17px; padding: 7px 16px; font-weight: 600; background: {PANEL}; }}
QPushButton[chip="true"]:checked {{ background: {PURPLE}; border-color: {PURPLE}; }}
QPushButton[small="true"] {{ padding: 7px 12px; border-radius: 9px; font-size: 12px; min-width: 64px; }}

#songRow {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 14px; }}
#songRow:hover {{ border-color: {PURPLE}; }}
#songTitle {{ font-size: 15px; font-weight: 700; }}
#songSub {{ font-size: 12px; color: {MUTED}; }}
#tag {{ font-size: 11px; font-weight: 700; border-radius: 7px; padding: 2px 8px;
    border: 1px solid {LINE}; color: {MUTED}; }}
#tag[kind="ready"] {{ color: {GREEN}; border-color: #2b8a62; }}
#tag[kind="busy"] {{ color: {GOLD}; border-color: #8a6a1c; }}
#tag[kind="singer"] {{ color: {CYAN}; border-color: #1c6f8a; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {LINE}; border-radius: 4px; min-height: 40px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {LINE}; border-radius: 4px; min-width: 40px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

#controlBar {{ background: rgba(10, 5, 24, 0.9); border-top: 2px solid {PURPLE}; }}
#controlBar QPushButton {{ padding: 0; font-size: 12px; font-weight: 800;
    border-radius: 12px; background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #34207a, stop:1 #1c1146);
    border: 1px solid #4c379c; }}
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
QComboBox QAbstractItemView {{ background: {PANEL}; border: 1px solid {PURPLE}; selection-background-color: {PURPLE};
    outline: none; }}
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
