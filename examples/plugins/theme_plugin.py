"""A colour theme for YTKTV. Copy this file, rename it and change the colours."""

NAME = "Ocean Theme"
VERSION = "1.0.0"
PERMISSIONS = ["themes"]
API_VERSION = 1

# Any colour you leave out keeps its value from the Neon theme.
COLOURS = {
    "BG": "#071a24",  # the screen behind everything
    "PANEL": "#0d2733",  # cards and panels
    "PANEL_2": "#143544",  # raised parts of a panel
    "LINE": "#245266",  # borders
    "TEXT": "#eafcff",  # main text
    "MUTED": "#8fb5c2",  # quieter text
    "PINK": "#2dd4bf",  # the main accent
    "CYAN": "#60a5fa",  # the second accent
    "PURPLE": "#818cf8",  # the third accent
}


def setup(api):
    api.add_theme("Ocean", COLOURS)
