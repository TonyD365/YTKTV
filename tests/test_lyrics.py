from __future__ import annotations

from ytktv.youtube.lyrics import LyricLine, clean_text, line_at, parse_json3, pick_track


def track(code: str, *exts: str) -> dict:
    return {code: [{"ext": ext, "url": f"https://subs.invalid/{code}.{ext}"} for ext in exts]}


def test_clean_text_keeps_only_what_is_sung():
    assert clean_text("♪ The club isn't the best place\nto find a lover ♪") == (
        "The club isn't the best place to find a lover"
    )
    assert clean_text("[RINGING SOUND]") == ""
    assert clean_text("(wind buffeting)") == ""
    assert clean_text("♪ ♪") == ""
    assert clean_text("- I just got here [laughs]") == "I just got here"
    assert clean_text("【音乐】 你好  世界") == "你好 世界"


def test_pick_track_prefers_the_video_language_and_matches_suffixed_ids():
    info = {
        "language": "en",
        "subtitles": {**track("ja", "json3"), **track("en-nP7-2PuUl7o", "vtt", "json3")},
    }
    assert pick_track(info) == "https://subs.invalid/en-nP7-2PuUl7o.json3"
    # No declared language: fall back to the preference list, Chinese first.
    info = {"subtitles": {**track("es", "json3"), **track("zh-Hant", "json3")}}
    assert pick_track(info) == "https://subs.invalid/zh-Hant.json3"
    # Nothing preferred is available: take whatever there is.
    assert pick_track({"subtitles": track("fil", "json3")}) == "https://subs.invalid/fil.json3"


def test_pick_track_ignores_auto_captions_unless_allowed():
    info = {"subtitles": {}, "automatic_captions": track("en", "json3")}
    assert pick_track(info) is None
    assert pick_track(info, allow_auto=True) == "https://subs.invalid/en.json3"
    # Uploaded subtitles still win over automatic ones.
    info["subtitles"] = track("ko", "json3")
    assert pick_track(info, allow_auto=True) == "https://subs.invalid/ko.json3"
    assert pick_track({"subtitles": track("en", "vtt")}) is None  # no json3 rendition
    assert pick_track({"subtitles": {"live_chat": [{"ext": "json3", "url": "x"}]}}) is None
    assert pick_track({}) is None


def event(start_ms: int, duration_ms: int | None, text: str) -> dict:
    data = {"tStartMs": start_ms, "segs": [{"utf8": text}]}
    if duration_ms is not None:
        data["dDurationMs"] = duration_ms
    return data


def test_parse_json3_cleans_orders_and_removes_overlaps():
    data = {
        "events": [
            event(433, 27100, "♪ ♪"),  # placeholder over the intro
            event(30000, 3000, "second line"),
            event(27000, 4000, "♪ first line ♪"),  # out of order, overlaps the next
            event(34000, None, "no duration"),
            {"tStartMs": 40000},  # no text at all
            event(50000, 2000, "[Applause]"),
        ]
    }
    lines = parse_json3(data)
    assert [line.text for line in lines] == ["first line", "second line", "no duration"]
    assert lines[0].start == 27.0 and lines[0].end == 30.0  # trimmed to the next line's start
    assert lines[1].end == 33.0
    assert lines[2].end > lines[2].start
    assert all(a.end <= b.start for a, b in zip(lines, lines[1:], strict=False))
    assert parse_json3({}) == []


def test_parse_json3_joins_a_caption_split_in_two():
    lines = parse_json3({"events": [event(1000, 1000, "la la"), event(2000, 1500, "la la")]})
    assert lines == [LyricLine(1.0, 3.5, "la la")]


def test_line_at_finds_the_current_or_next_line():
    lines = [LyricLine(10, 12, "a"), LyricLine(12, 15, "b"), LyricLine(30, 33, "c")]
    assert line_at(lines, 0) == 0  # before the first: the first is coming up
    assert line_at(lines, 11) == 0
    assert line_at(lines, 12) == 1  # a line ends exactly where the next begins
    assert line_at(lines, 20) == 2  # in a break: the next one
    assert line_at(lines, 33) == -1
    assert line_at([], 5) == -1
