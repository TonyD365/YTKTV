"""Timed lyrics from a video's own subtitles (no network here; see YouTube.lyrics)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

# Preferred subtitle languages when the video does not say what language it is in.
_FALLBACK_LANGUAGES = ("zh-Hans", "zh-CN", "zh", "zh-Hant", "zh-TW", "en", "ja", "ko", "es")
_SOUND_NOTE = re.compile(r"[\[\(（【][^\]\)）】]{0,40}[\]\)）】]")  # [Music], (applause), ...
_NOTES = re.compile(r"[♪♫♬🎵🎶]+")
_SPACE = re.compile(r"\s+")
# A caption shown for longer than this is a placeholder ("♪ ♪" over an intro), not a line.
_MAX_LINE_SECONDS = 20.0


@dataclass(frozen=True, slots=True)
class LyricLine:
    start: float  # seconds
    end: float
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text}


def clean_text(text: str) -> str:
    """Strip sound descriptions and music symbols, leaving only what is sung."""
    text = _SOUND_NOTE.sub(" ", text)
    text = _NOTES.sub(" ", text)
    text = _SPACE.sub(" ", text.replace("\n", " ")).strip()
    return text.lstrip("-–— ").strip()


def _base_language(code: str) -> str:
    return code.split("-")[0].lower()


def pick_track(info: dict[str, Any], allow_auto: bool = False) -> str | None:
    """URL of the best subtitle track in ``json3`` format, or None when there is none.

    Subtitles uploaded with the video come first. Automatic captions of music are
    often wrong, so they are only a fallback, and only when *allow_auto* is set.
    """
    sources = [info.get("subtitles") or {}]
    if allow_auto:
        sources.append(info.get("automatic_captions") or {})
    wanted: list[str] = []
    if info.get("language"):
        wanted.append(str(info["language"]))
    wanted += _FALLBACK_LANGUAGES
    for tracks in sources:
        usable = {
            code: next(
                (e["url"] for e in entries if e.get("ext") == "json3" and e.get("url")), None
            )
            for code, entries in tracks.items()
            if code != "live_chat"
        }
        usable = {code: url for code, url in usable.items() if url}
        if not usable:
            continue
        for language in wanted:
            # YouTube suffixes track ids ("en-nP7-2PuUl7o"), so match on the language part.
            for code, url in usable.items():
                if code == language or code.startswith(language + "-"):
                    return url
            for code, url in usable.items():
                if _base_language(code) == _base_language(language):
                    return url
        return next(iter(usable.values()))
    return None


def parse_json3(data: dict[str, Any]) -> list[LyricLine]:
    """Convert YouTube's json3 caption format to clean, non-overlapping lines."""
    lines: list[LyricLine] = []
    for event in data.get("events") or []:
        segments = event.get("segs")
        if not segments or "tStartMs" not in event:
            continue
        text = clean_text("".join(str(seg.get("utf8", "")) for seg in segments))
        if not text:
            continue
        start = float(event["tStartMs"]) / 1000.0
        duration = float(event.get("dDurationMs") or 0) / 1000.0
        if duration <= 0 or duration > _MAX_LINE_SECONDS:
            duration = min(max(duration, 0.0), _MAX_LINE_SECONDS) or 4.0
        lines.append(LyricLine(start, start + duration, text))
    lines.sort(key=lambda line: line.start)
    tidy: list[LyricLine] = []
    for i, line in enumerate(lines):
        if tidy and tidy[-1].text == line.text and line.start - tidy[-1].end < 0.3:
            # The same caption split across two events: join them.
            tidy[-1] = LyricLine(tidy[-1].start, max(tidy[-1].end, line.end), line.text)
            continue
        end = line.end
        if i + 1 < len(lines) and lines[i + 1].start < end:
            end = max(line.start + 0.2, lines[i + 1].start)  # never overlap the next line
        tidy.append(LyricLine(line.start, end, line.text))
    return tidy


def line_at(lines: list[LyricLine], position: float) -> int:
    """Index of the line being sung at *position*, or of the next one coming up; -1 if none."""
    low, high = 0, len(lines)
    while low < high:  # first line that has not finished yet
        mid = (low + high) // 2
        if lines[mid].end <= position:
            low = mid + 1
        else:
            high = mid
    return low if low < len(lines) else -1
