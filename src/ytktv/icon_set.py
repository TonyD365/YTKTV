"""YTKTV's own line icons, used instead of system emoji on every screen.

Each icon is drawn on a 24 × 24 grid with round strokes in one colour. The phone page gets the
same drawings from /icons/<name>.svg, so the console and the phones look alike. This module has
no Qt in it, so the web server can use it too; ytktv.ui.icons draws them for Qt.
"""

from __future__ import annotations

import re

# name -> SVG elements on a 24 × 24 grid; "C" is replaced by the colour.
ICONS: dict[str, str] = {
    "home": '<path d="M3 11 12 4l9 7"/><path d="M5.5 9.5V20h13V9.5"/><path d="M10 20v-5h4v5"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6"/><path d="m15 15 5.5 5.5"/>',
    "star": '<path d="m12 3.5 2.6 5.6 6 .7-4.5 4.1 1.2 6-5.3-3-5.3 3 1.2-6L3.4 9.8l6-.7z"/>',
    "fire": '<path d="M12 21c-4 0-6.5-2.6-6.5-6.2 0-3.4 2.6-5.3 3.4-8.8 2 1.3 3 3 3.1 4.8'
    ' 1-1 1.6-2.2 1.7-3.6 2.8 2 4.8 4.8 4.8 7.6 0 3.6-2.5 6.2-6.5 6.2z"/>'
    '<path d="M12 21c-1.7 0-2.8-1.1-2.8-2.7 0-1.6 1.4-2.4 2.8-4.3 1.4 1.9 2.8 2.7 2.8 4.3'
    ' 0 1.6-1.1 2.7-2.8 2.7z"/>',
    "list": '<path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r=".6"/>'
    '<circle cx="4" cy="12" r=".6"/><circle cx="4" cy="18" r=".6"/>',
    "heart": '<path d="M12 20s-7.5-4.6-7.5-10A4.3 4.3 0 0 1 12 7.4 4.3 4.3 0 0 1 19.5 10'
    'c0 5.4-7.5 10-7.5 10z"/>',
    "hearts": '<path d="M9 18s-6-3.7-6-8a3.4 3.4 0 0 1 6-2.1A3.4 3.4 0 0 1 15 10"/>'
    '<path d="M16 21s-4.5-2.8-4.5-6a2.6 2.6 0 0 1 4.5-1.6 2.6 2.6 0 0 1 4.5 1.6'
    'c0 3.2-4.5 6-4.5 6z"/>',
    "mic": '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M6 11a6 6 0 0 0 12 0"/>'
    '<path d="M12 17v4M9 21h6"/>',
    "check": '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
    "sliders": '<path d="M6 4v16M12 4v16M18 4v16"/><rect x="4" y="13" width="4" height="3" rx="1"/>'
    '<rect x="10" y="7" width="4" height="3" rx="1"/><rect x="16" y="15" width="4" height="3"'
    ' rx="1"/>',
    "bell": '<path d="M4 17h16"/><path d="M5.5 17a6.5 6.5 0 0 1 13 0"/><path d="M12 8.5V7"/>'
    '<path d="M10.5 7h3"/><path d="M3 20h18"/>',
    "fullscreen": '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/>',
    "playpause": '<path d="M4 5v14l8-7z"/><path d="M15 5v14M20 5v14"/>',
    "prev": '<path d="M6 5v14"/><path d="M19 5v14l-10-7z"/>',
    "next": '<path d="M18 5v14"/><path d="M5 5v14l10-7z"/>',
    "replay": '<path d="M4.5 12a7.5 7.5 0 1 0 2.2-5.3"/><path d="M4.5 4v4h4"/>',
    "megaphone": '<path d="M4 10v4h3l9 4.5v-13L7 10z"/><path d="M7 14l1.5 5h2.5L9.6 14"/>'
    '<path d="M19 9.5a3 3 0 0 1 0 5"/>',
    "drum": '<ellipse cx="12" cy="9" rx="7.5" ry="3"/><path d="M4.5 9v6c0 1.7 3.4 3 7.5 3'
    's7.5-1.3 7.5-3V9"/><path d="m8 3 3 4.5M16 3l-3 4.5"/>',
    "timer": '<circle cx="12" cy="13.5" r="7"/><path d="M12 13.5V10M10 3h4M12 3v3.5"/>'
    '<path d="m18 6.5 1.5-1.5"/>',
    "clap": '<path d="M8 13 5.2 10.2a1.4 1.4 0 0 1 2-2L11 12"/><path d="m9.5 9.5-2.2-2.2'
    'a1.4 1.4 0 0 1 2-2l4.6 4.6"/><path d="M12 6.4a1.4 1.4 0 0 1 2-2l3.3 3.3c2.8 2.8 2.8'
    ' 7 0 9.9a7 7 0 0 1-9.9 0L5 15.2a1.4 1.4 0 0 1 2-2"/><path d="M17.5 3.5 19 2M20 6l1.5-.5"/>',
    "cheer": '<path d="M7 21v-5l-3-4 2-6M17 21v-5l3-4-2-6"/><circle cx="12" cy="7" r="2.5"/>'
    '<path d="M9 21v-6a3 3 0 0 1 6 0v6"/>',
    "swords": '<path d="M4 4l9 9M4 4h4M4 4v4"/><path d="M20 4l-9 9M20 4h-4M20 4v4"/>'
    '<path d="m10 15-4 4M14 15l4 4M7 13l4 4M17 13l-4 4"/>',
    "masks": '<path d="M3 5c3 1.5 6 1.5 9 0v5a4.5 4.5 0 0 1-9 0z"/><path d="M12 9c3 1.5 6 1.5'
    ' 9 0v5a4.5 4.5 0 0 1-9 0"/><path d="M5.5 9h1.5M8.5 9H10M14.5 13H16M17.5 13H19"/>'
    '<path d="M6 12.5a2 2 0 0 0 3 0M15 17.5a2 2 0 0 1 3 0"/>',
    "sparkle": '<path d="M10 3c.6 4.2 2.3 6 6.5 6.5-4.2.6-5.9 2.3-6.5 6.5-.6-4.2-2.3-5.9'
    '-6.5-6.5C7.7 9 9.4 7.2 10 3z"/><path d="M18 14c.3 2 1 2.8 3 3-2 .3-2.7 1-3 3-.3-2-1-2.7'
    '-3-3 2-.2 2.7-1 3-3z"/>',
    "speaker": '<path d="M4 9.5v5h3.5L13 19V5L7.5 9.5z"/><path d="M16.5 9a4 4 0 0 1 0 6'
    'M19 6.5a7.5 7.5 0 0 1 0 11"/>',
    "note": '<path d="M9 18V5.5l10-2V16"/><circle cx="6.5" cy="18" r="2.5"/>'
    '<circle cx="16.5" cy="16" r="2.5"/>',
    "dice": '<rect x="4" y="4" width="16" height="16" rx="3.5"/><circle cx="8.5" cy="8.5" r=".8"/>'
    '<circle cx="12" cy="12" r=".8"/><circle cx="15.5" cy="15.5" r=".8"/>',
    "wheel": '<circle cx="12" cy="10" r="7"/><path d="M12 3v14M5 10h14M7 5l10 10M17 5 7 15"/>'
    '<path d="m9 21 3-4 3 4"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9.5h8M8 12.5h5"/>',
    "bomb": '<circle cx="10.5" cy="14" r="6.5"/><path d="m15 9.5 2-2M17.5 6.5c.8-1.6 2.4-2'
    ' 3.5-1.5"/><path d="M8 12a3 3 0 0 1 2.5-2"/>',
    "boom": '<path d="m12 2.5 1.8 5 4.7-2.3-2.3 4.7 5 1.8-5 1.8 2.3 4.7-4.7-2.3-1.8 5-1.8-5'
    '-4.7 2.3 2.3-4.7-5-1.8 5-1.8-2.3-4.7 4.7 2.3z"/>',
    "eye": '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/>'
    '<circle cx="12" cy="12" r="3"/>',
    "question": '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3'
    'c-.7.3-1 .9-1 1.7v.5"/><circle cx="12" cy="17" r=".6"/>',
    "slot": '<rect x="3.5" y="5" width="14" height="15" rx="2.5"/><path d="M3.5 9h14M3.5 16h14'
    'M8.2 9v7M12.8 9v7"/><path d="M17.5 11h2.5V7"/><circle cx="20" cy="5.5" r="1.3"/>',
    "sad": '<circle cx="12" cy="12" r="9"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/>'
    '<circle cx="9" cy="10" r=".6"/><circle cx="15" cy="10" r=".6"/>',
    "sticks": '<path d="m5 21 9-18M10 21l9-18"/><path d="M4 16h7M9 16h7"/>',
    "scale": '<path d="M12 4v16M8 20h8M5 7h14"/><path d="m5 7-3 7a3 3 0 0 0 6 0zM19 7l-3 7'
    'a3 3 0 0 0 6 0z"/>',
    "coin": '<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="5.5"/>'
    '<path d="M12 9.5v5"/>',
    "crown": '<path d="m3.5 8 4 4 4.5-6.5 4.5 6.5 4-4-1.5 10h-14z"/><path d="M5.5 20h13"/>',
    "cake": '<path d="M4 20V13a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v7"/><path d="M3 20h18"/>'
    '<path d="M4 15.5c1.3 1 2.7 1 4 0s2.7-1 4 0 2.7 1 4 0 2.7-1 4 0"/>'
    '<path d="M8 11V8M12 11V8M16 11V8"/><path d="M8 5.5v-.5M12 5.5v-.5M16 5.5v-.5"/>',
    "balloon": '<path d="M12 15c-3.6 0-6-3.1-6-6.5a6 6 0 0 1 12 0c0 3.4-2.4 6.5-6 6.5z"/>'
    '<path d="m11 15 1 1.5 1-1.5M12 16.5c-1.5 1.5 1.5 3-.5 5"/>',
    "gift": '<rect x="4" y="9" width="16" height="11" rx="1.5"/><path d="M3 9h18M12 9v11"/>'
    '<path d="M12 9C10 5 6.5 5 7.5 7.5 8 9 12 9 12 9zM12 9c2-4 5.5-4 4.5-1.5C16 9 12 9 12 9z"/>',
    "party": '<path d="m4 20 5.5-14 8.5 8.5z"/><path d="M7.2 14 10 16.8M8.5 10.5l5 5"/>'
    '<path d="M14 4.5c.5 1.5 0 2.5-1 3M19.5 10c-1.5-.5-2.5 0-3 1M17 3.5l.5 1.5M20.5 7l-1.5.5"/>',
    "download": '<path d="M12 4v11M7 10.5l5 5 5-5"/><path d="M5 20h14"/>',
    "upload": '<path d="M12 20V9M7 13.5l5-5 5 5"/><path d="M5 4h14"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3'
    'M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>'
    '<circle cx="12" cy="12" r="6.5"/>',
    "calendar": '<rect x="3.5" y="5" width="17" height="15" rx="2"/><path d="M3.5 10h17'
    'M8 3v4M16 3v4"/><path d="M8 14h2M14 14h2M8 17h2"/>',
    "broom": '<path d="M14 3 11 11"/><path d="M7 12h8l2 9H5z"/><path d="M9 16v5M13 16v5"/>',
    "wrench": '<path d="M14.5 4a5 5 0 0 0-4.6 6.9L3.5 17.3a2.1 2.1 0 0 0 3 3l6.4-6.4'
    'A5 5 0 0 0 20 9.5l-3 3-3-.5-.5-3 3-3a5 5 0 0 0-2-2z"/>',
    "warning": '<path d="M12 3.5 21.5 20h-19z"/><path d="M12 10v4.5"/><circle cx="12" cy="17"'
    ' r=".6"/>',
    "lock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1'
    ' 8 0v2.5"/><path d="M12 14.5v2.5"/>',
    "unlock": '<rect x="5" y="10.5" width="14" height="10" rx="2"/><path d="M8 10.5V8a4 4 0 0 1'
    ' 7.7-1.5"/><path d="M12 14.5v2.5"/>',
    "chart": '<path d="M4 20h16"/><path d="M6 20v-6M10.5 20V9M15 20v-8M19.5 20V5"/>',
    "trend": '<path d="M4 20h16M4 4v16"/><path d="m7 15 4-4 3 3 6-7"/><path d="M16 7h4v4"/>',
    "card": '<rect x="3" y="5.5" width="18" height="13" rx="2"/><path d="M3 10h18M7 15h4"/>',
    "scroll": '<path d="M7 4h11a2 2 0 0 1 2 2v1h-4"/><path d="M16 7v11a2 2 0 0 1-2 2H6'
    'a2 2 0 0 1-2-2v-1h10"/><path d="M7 4a2 2 0 0 0-2 2v11M9 9h4M9 12h4"/>',
    "key": '<circle cx="8" cy="15" r="4.5"/><path d="m11.3 11.8 8.2-8.3M16.5 6.5l2.5 2.5'
    'M14 9l2 2"/>',
    "repeat": '<path d="M5 11V9a3 3 0 0 1 3-3h11"/><path d="m16 3 3 3-3 3"/>'
    '<path d="M19 13v2a3 3 0 0 1-3 3H5"/><path d="m8 21-3-3 3-3"/>',
    "cart": '<path d="M3 4h2.5l2.3 11h10.4L20.5 7.5H6.4"/><circle cx="9" cy="19" r="1.4"/>'
    '<circle cx="17" cy="19" r="1.4"/>',
    "clipboard": '<rect x="5" y="4.5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6"'
    ' height="3" rx="1"/><path d="M8.5 11h7M8.5 14.5h7M8.5 18h4"/>',
    "box": '<path d="m12 3 8.5 4.5v9L12 21l-8.5-4.5v-9z"/><path d="m3.5 7.5 8.5 4.5 8.5-4.5'
    'M12 12v9"/>',
    "money": '<rect x="2.5" y="6" width="19" height="12" rx="2"/><circle cx="12" cy="12" r="2.8"/>'
    '<path d="M6 9.5v5M18 9.5v5"/>',
    "receipt": '<path d="M5.5 3h13v18l-2.2-1.5L14 21l-2-1.5-2 1.5-2.3-1.5L5.5 21z"/>'
    '<path d="M8.5 8h7M8.5 11.5h7M8.5 15h4"/>',
    "disco": '<circle cx="12" cy="13" r="7"/><path d="M12 6v14M5 13h14M6.5 9h11M6.5 17h11"/>'
    '<path d="M12 6V2.5"/><path d="M9 6.6c1 3.8 1 9 0 12.8M15 6.6c-1 3.8-1 9 0 12.8"/>',
    "wave": '<path d="M3 15c2-2.5 4-2.5 6 0s4 2.5 6 0 4-2.5 6 0"/><path d="M3 19.5c2-2.5 4-2.5 6 0'
    's4 2.5 6 0 4-2.5 6 0"/><path d="M5 11c0-4 3.5-7 7.5-7 2.6 0 4.5 1.6 4.5 3.5 0 1.4-1 2.5'
    '-2.5 2.5-1 0-2-.6-2-1.8"/>',
    "lights": '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.4.3.5.7.5 1.1v1h6v-1'
    'c0-.4.1-.8.5-1.1A6 6 0 0 0 12 3z"/>',
    "close": '<path d="M6 6l12 12M18 6 6 18"/>',
    "rose": '<path d="M12 21v-9"/><path d="M12 15.5c-2-1.2-4-1.2-5.5 0M12 17.5c2-1.5 4-1.5 5 0"/>'
    '<path d="M12 12c-3 0-5-2-5-5 2 0 3 .5 3.5 1.5C11 6 12 4.5 12 4.5s1 1.5 1.5 4'
    'C14 7.5 15 7 17 7c0 3-2 5-5 5z"/>',
    "laugh": '<circle cx="12" cy="12" r="9"/><path d="M7.5 13h9a4.5 4.5 0 0 1-9 0z"/>'
    '<path d="m7.5 8.5 2 1.2-2 1.2M16.5 8.5l-2 1.2 2 1.2"/>',
    "hundred": '<path d="M3.5 8 5.5 6.5V16"/><circle cx="11" cy="11.5" r="3.5"/>'
    '<circle cx="18" cy="11.5" r="3.5"/><path d="M4 19.5c5-1 11-1 16 0"/>',
    "beers": '<path d="M4 9h7v10a1.5 1.5 0 0 1-1.5 1.5h-4A1.5 1.5 0 0 1 4 19z"/>'
    '<path d="M11 11h1.5a1.5 1.5 0 0 1 1.5 1.5V15a1.5 1.5 0 0 1-1.5 1.5H11"/>'
    '<path d="M4 9c0-1.6 1-2.6 2.5-2.6.6-1 1.5-1.4 2.5-1 1.3 0 2 1 2 2.6"/>'
    '<path d="m15.5 5 5 1.4-1.9 11.2a1.5 1.5 0 0 1-1.8 1.2l-1.3-.3"/><path d="M7 12v5M9 12v5"/>',
}

# The emoji each icon stands for; any of them in a button's text becomes that icon.
EMOJI: dict[str, str] = {
    "⌂": "home", "🏠": "home", "🔍": "search", "★": "star", "⭐": "star", "🔥": "fire",
    "≡": "list", "♥": "heart", "♡": "heart", "❤": "heart", "💕": "hearts", "🎤": "mic",
    "✅": "check", "🎚": "sliders", "🛎": "bell", "⛶": "fullscreen", "⏯": "playpause",
    "⏮": "prev", "⏭": "next", "↺": "replay", "🔄": "repeat", "🔁": "repeat",
    "📣": "megaphone", "📢": "megaphone", "🥁": "drum", "⏱": "timer", "⏳": "timer",
    "⏰": "timer", "🕒": "timer", "👏": "clap", "🙌": "cheer", "⚔": "swords", "🎭": "masks",
    "✨": "sparkle", "🔊": "speaker", "🎵": "note", "♪": "note", "🎲": "dice", "🎡": "wheel",
    "💬": "chat", "💣": "bomb", "💥": "boom", "👁": "eye", "👀": "eye", "❓": "question",
    "🎰": "slot", "😕": "sad", "🥢": "sticks", "⚖": "scale", "🪙": "coin", "👑": "crown",
    "🎂": "cake", "🎈": "balloon", "🎁": "gift", "🎉": "party", "⬇": "download",
    "⬆": "upload", "⚙": "gear", "📅": "calendar", "🧹": "broom", "🔧": "wrench",
    "⚠": "warning", "🔒": "lock", "🔓": "unlock", "📊": "chart", "📈": "trend", "💳": "card",
    "📜": "scroll", "🔑": "key", "🛒": "cart", "📋": "clipboard", "📦": "box", "💰": "money",
    "🧾": "receipt", "🪩": "disco", "🌊": "wave", "💡": "lights", "🌹": "rose",
    "😂": "laugh", "💯": "hundred", "🍻": "beers",
}  # fmt: skip

EMOJI_RE = re.compile(
    "(" + "|".join(sorted(map(re.escape, EMOJI), key=len, reverse=True)) + ")️?\\s*"
)


def svg(name: str, colour: str = "#ffffff", stroke: float = 1.8) -> str:
    """One icon as a complete SVG document."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"'
        f' stroke="{colour}" stroke-width="{stroke}" stroke-linecap="round"'
        f' stroke-linejoin="round">{ICONS[name]}</svg>'
    )


def split(text: str) -> tuple[str | None, str]:
    """The first emoji in *text* as an icon name, and the text without any emoji."""
    match = EMOJI_RE.search(text)
    name = EMOJI[match.group(1)] if match else None
    return name, EMOJI_RE.sub("", text).strip()
