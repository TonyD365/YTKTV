from __future__ import annotations

from ytktv.youtube.lyrics import (
    MAX_WORD_SECONDS,
    LyricLine,
    borrow_word_timing,
    clean_text,
    line_at,
    parse_json3,
    pick_track,
    pick_tracks,
    sung_fraction,
)


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


def auto_event(start_ms: int, duration_ms: int, *words: tuple[str, int]) -> dict:
    segs = [{"utf8": text, **({"tOffsetMs": offset} if offset else {})} for text, offset in words]
    return {"tStartMs": start_ms, "dDurationMs": duration_ms, "segs": segs}


def test_parse_json3_keeps_when_each_word_of_an_automatic_caption_starts():
    lines = parse_json3(
        {
            "events": [
                auto_event(
                    16000, 5000, ("The", 0), (" club", 160), (" isn't", 400), (" best", 960)
                ),
                {"tStartMs": 18000, "aAppend": 1, "segs": [{"utf8": "\n"}]},
                auto_event(18500, 4000, ("[Music]", 0), (" place", 300), (" ♪", 500), (" to", 700)),
                {"tStartMs": 30000, "dDurationMs": 2000, "segs": [{"utf8": "written by hand"}]},
            ]
        }
    )
    assert [line.text for line in lines] == ["The club isn't best", "place to", "written by hand"]
    first, second, third = lines
    assert first.words == ((16.0, 0), (16.16, 4), (16.4, 9), (16.96, 15))
    assert [first.text[i:].split()[0] for _t, i in first.words] == ["The", "club", "isn't", "best"]
    assert second.words == ((18.8, 0), (19.2, 6))  # the sound note and the symbol are no words
    assert third.words == () and "words" not in third.to_dict()
    assert LyricLine.from_dict(first.to_dict()) == first


def test_sung_fraction_follows_the_words_and_waits_through_pauses():
    line = LyricLine(10.0, 20.0, "one two three")
    assert sung_fraction(line, 15.0, []) == 0.5  # no word timing: an even fill
    # "one" at 10 s, "two" at 11 s, then a long pause before "three" at 18 s.
    stops = [(10.0, 0.0), (11.0, 0.3), (18.0, 0.6)]
    assert sung_fraction(line, 9.0, stops) == 0.0
    assert sung_fraction(line, 10.5, stops) == 0.15
    assert sung_fraction(line, 11.0, stops) == 0.3
    # "two" is filled after MAX_WORD_SECONDS, then the colour waits for "three".
    assert sung_fraction(line, 11.0 + MAX_WORD_SECONDS, stops) == 0.6
    assert sung_fraction(line, 17.9, stops) == 0.6
    assert 0.6 < sung_fraction(line, 18.5, stops) < 1.0
    assert sung_fraction(line, 25.0, stops) == 1.0


def test_borrow_word_timing_moves_uploaded_lines_in_the_rhythm_that_was_heard():
    heard = [
        LyricLine(
            10.0, 14.0, "wrong words were heard", ((10.0, 0), (10.5, 6), (12.5, 12), (13.0, 17))
        )
    ]
    lines = [
        LyricLine(10.0, 14.0, "Right words are here"),
        LyricLine(20.0, 24.0, "Nothing was heard during this one"),
        LyricLine(30.0, 31.0, "我爱你", ((30.0, 0), (30.5, 1))),
    ]
    first, second, third = borrow_word_timing(lines, heard)
    assert first.text == "Right words are here"
    assert first.words == ((10.0, 0), (10.5, 6), (12.5, 12), (13.0, 16))
    assert second.words == ()  # filled evenly, as before
    assert third == lines[2]  # already timed: left alone
    assert borrow_word_timing(lines, []) == lines

    # More words in the line than were heard: the moments are spread over them.
    (spread,) = borrow_word_timing([LyricLine(10.0, 14.0, "我爱你中国")], heard)
    assert [offset for _t, offset in spread.words] == [0, 1, 2, 3, 4]
    times = [t for t, _offset in spread.words]
    assert times == sorted(times) and times[0] == 10.0 and times[-1] < 14.0


def test_pick_tracks_prefers_the_original_automatic_captions():
    info = {
        "language": "en",
        "subtitles": track("en", "json3"),
        "automatic_captions": {**track("en", "json3"), **track("en-orig", "json3")},
    }
    assert pick_tracks(info) == (
        "https://subs.invalid/en.json3",
        "https://subs.invalid/en-orig.json3",
    )
    assert pick_tracks({"automatic_captions": track("ko", "json3")}) == (
        None,
        "https://subs.invalid/ko.json3",
    )
    assert pick_tracks({}) == (None, None)
