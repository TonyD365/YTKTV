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


# While a word is sung the colour sweeps across it, but never for longer than this:
# the gap to the next word is often a breath or a break, not a held note.
MAX_WORD_SECONDS = 1.5


@dataclass(frozen=True, slots=True)
class LyricLine:
    start: float  # seconds
    end: float
    text: str
    # When each word starts, as (seconds, index into text). Automatic captions have
    # this; subtitles written by hand usually time whole lines only, and leave it empty.
    words: tuple[tuple[float, int], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"start": self.start, "end": self.end, "text": self.text}
        if self.words:
            data["words"] = [list(word) for word in self.words]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LyricLine:
        words = tuple((float(t), int(i)) for t, i in data.get("words") or ())
        return cls(float(data["start"]), float(data["end"]), str(data["text"]), words)


def sung_fraction(line: LyricLine, position: float, stops: list[tuple[float, float]]) -> float:
    """How much of *line* has been sung at *position*, from 0 to 1.

    *stops* says where each word begins, as (seconds, fraction of the line's width).
    Without stops the line fills evenly from its start to its end.
    """
    if not stops:
        span = max(0.05, line.end - line.start)
        return max(0.0, min(1.0, (position - line.start) / span))
    if position < stops[0][0]:
        return 0.0
    for i, (start, fraction) in enumerate(stops):
        next_start, next_fraction = stops[i + 1] if i + 1 < len(stops) else (line.end, 1.0)
        if position < next_start or i + 1 == len(stops):
            sweep = max(0.05, min(next_start - start, MAX_WORD_SECONDS))
            done = max(0.0, min(1.0, (position - start) / sweep))
            return fraction + (next_fraction - fraction) * done
    return 1.0


def clean_text(text: str) -> str:
    """Strip sound descriptions and music symbols, leaving only what is sung."""
    text = _SOUND_NOTE.sub(" ", text)
    text = _NOTES.sub(" ", text)
    text = _SPACE.sub(" ", text.replace("\n", " ")).strip()
    return text.lstrip("-–— ").strip()


def _base_language(code: str) -> str:
    return code.split("-")[0].lower()


def _best_track(tracks: dict[str, Any], wanted: list[str]) -> str | None:
    usable = {
        code: next((e["url"] for e in entries if e.get("ext") == "json3" and e.get("url")), None)
        for code, entries in tracks.items()
        if code != "live_chat"
    }
    usable = {code: url for code, url in usable.items() if url}
    if not usable:
        return None
    for language in wanted:
        # YouTube suffixes track ids ("en-nP7-2PuUl7o"), so match on the language part.
        for code, url in usable.items():
            if code == language or code.startswith(language + "-"):
                return url
        for code, url in usable.items():
            if _base_language(code) == _base_language(language):
                return url
    return next(iter(usable.values()))


def pick_tracks(info: dict[str, Any]) -> tuple[str | None, str | None]:
    """URLs of the best uploaded subtitle track and the best automatic one (``json3``)."""
    wanted: list[str] = []
    if info.get("language"):
        wanted.append(str(info["language"]))
    wanted += _FALLBACK_LANGUAGES
    automatic = info.get("automatic_captions") or {}
    # Only captions of the language actually sung carry word timing; YouTube marks
    # them "-orig". The other automatic tracks are machine translations of it.
    original = {code: entries for code, entries in automatic.items() if code.endswith("-orig")}
    return (
        _best_track(info.get("subtitles") or {}, wanted),
        _best_track(original, wanted) or _best_track(automatic, wanted),
    )


def pick_track(info: dict[str, Any], allow_auto: bool = False) -> str | None:
    """URL of the best subtitle track in ``json3`` format, or None when there is none.

    Subtitles uploaded with the video come first. Automatic captions of music are
    often wrong, so they are only a fallback, and only when *allow_auto* is set.
    """
    uploaded, automatic = pick_tracks(info)
    return uploaded or (automatic if allow_auto else None)


# One unit of text to colour at a time: a CJK character, or a run of other letters.
_CJK = r"\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af"
_UNIT = re.compile(rf"[{_CJK}]|[^\s{_CJK}]+")


def borrow_word_timing(lines: list[LyricLine], donor: list[LyricLine]) -> list[LyricLine]:
    """Give *lines* that are timed as a whole the rhythm of *donor*'s timed words.

    Subtitles written by hand have the right words but only say when a line starts and
    ends. Automatic captions of the same video often have the wrong words but say when
    each one was heard. The moments at which words were heard during a line are spread
    over that line's own words, so the colour moves when the singer does.
    """
    heard = sorted(time for line in donor for time, _offset in line.words)
    if not heard:
        return lines
    result: list[LyricLine] = []
    for line in lines:
        units = [match.start() for match in _UNIT.finditer(line.text)]
        times = [t for t in heard if line.start - 0.3 <= t < line.end]
        # Too few words heard means the recogniser missed most of the line: fill evenly.
        if line.words or len(units) < 2 or len(times) < max(2, len(units) // 3):
            result.append(line)
            continue
        words: list[tuple[float, int]] = []
        for rank, offset in enumerate(units):
            place = rank * len(times) / len(units)
            low = int(place)
            after = times[low + 1] if low + 1 < len(times) else line.end
            moment = times[low] + (place - low) * (after - times[low])
            words.append((max(line.start, min(moment, line.end)), offset))
        result.append(LyricLine(line.start, line.end, line.text, tuple(words)))
    return result


def _timed_words(
    segments: list[dict[str, Any]], start: float, text: str
) -> tuple[tuple[float, int], ...]:
    """Where each separately timed segment begins in the cleaned *text*; () if untimed."""
    if not any("tOffsetMs" in seg for seg in segments):
        return ()
    built = ""
    words: list[tuple[float, int]] = []
    for seg in segments:
        piece = _SPACE.sub(" ", _NOTES.sub(" ", _SOUND_NOTE.sub(" ", str(seg.get("utf8", "")))))
        body = piece.strip()
        if not built:
            body = body.lstrip("-–— ").strip()
        if not body:
            if built and not built.endswith(" "):
                built += " "
            continue
        if built and piece.startswith(" ") and not built.endswith(" "):
            built += " "
        words.append((start + float(seg.get("tOffsetMs") or 0) / 1000.0, len(built)))
        built += body + (" " if piece.endswith(" ") else "")
    # Cleaning piece by piece must give the same text as cleaning the whole line;
    # if it does not (a note spanning two segments), the offsets cannot be trusted.
    return tuple(words) if built.rstrip() == text and len(words) > 1 else ()


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
        words = _timed_words(segments, start, text)
        duration = float(event.get("dDurationMs") or 0) / 1000.0
        if duration <= 0 or duration > _MAX_LINE_SECONDS:
            duration = min(max(duration, 0.0), _MAX_LINE_SECONDS) or 4.0
        lines.append(LyricLine(start, start + duration, text, words))
    lines.sort(key=lambda line: line.start)
    tidy: list[LyricLine] = []
    for i, line in enumerate(lines):
        if tidy and tidy[-1].text == line.text and line.start - tidy[-1].end < 0.3:
            # The same caption split across two events: join them.
            tidy[-1] = LyricLine(
                tidy[-1].start, max(tidy[-1].end, line.end), line.text, tidy[-1].words
            )
            continue
        end = line.end
        if i + 1 < len(lines) and lines[i + 1].start < end:
            end = max(line.start + 0.2, lines[i + 1].start)  # never overlap the next line
        tidy.append(LyricLine(line.start, end, line.text, line.words))
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


# Duets: who sings each line. Lyrics written for duets often start a part with a marker
# like "男：", "(女)" or "F:", which holds until the next one.
PART_A, PART_B, PART_BOTH = 0, 1, 2
_PART_NAMES = {
    "男": PART_A, "m": PART_A, "male": PART_A, "man": PART_A, "him": PART_A,
    "女": PART_B, "f": PART_B, "female": PART_B, "woman": PART_B, "her": PART_B,
    "合": PART_BOTH, "合唱": PART_BOTH, "男女": PART_BOTH, "男女合": PART_BOTH,
    "both": PART_BOTH, "all": PART_BOTH, "together": PART_BOTH,
}  # fmt: skip
_PART_MARK = re.compile(
    r"^\s*(?:[\[\(（【<]\s*(?P<a>[^\]\)）】>]{1,6}?)\s*[\]\)）】>]\s*[:：]?"
    r"|(?P<b>[^\s:：]{1,6}?)\s*[:：])\s*"
)
# Without markers, a gap this long between lines starts the other singer's turn.
DUET_BREAK_SECONDS = 3.0


def duet_parts(lines: list[LyricLine]) -> tuple[list[LyricLine], list[int]]:
    """Each line's part, and the lines without their part markers.

    Lyrics without any markers alternate between the two singers verse by verse.
    """
    marked: list[int | None] = []
    cleaned: list[LyricLine] = []
    for line in lines:
        match = _PART_MARK.match(line.text)
        name = (match.group("a") or match.group("b")).strip().lower() if match else ""
        if name not in _PART_NAMES or match is None or match.end() >= len(line.text):
            marked.append(None)
            cleaned.append(line)
            continue
        marked.append(_PART_NAMES[name])
        cut = match.end()
        words = tuple((t, max(0, i - cut)) for t, i in line.words)
        cleaned.append(LyricLine(line.start, line.end, line.text[cut:], words))
    if any(part is not None for part in marked):
        parts, current = [], PART_BOTH  # before the first marker both sing
        for part in marked:
            current = current if part is None else part
            parts.append(current)
        return cleaned, parts
    parts, current = [], PART_A
    for i, line in enumerate(lines):
        if i and line.start - lines[i - 1].end >= DUET_BREAK_SECONDS:
            current = PART_B if current == PART_A else PART_A
        parts.append(current)
    return cleaned, parts
