"""Lyrics written by Whisper for songs that have none (the model itself is not run here)."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

from tests.helpers import make_controller, make_song, wait_for
from ytktv import lyrics_ai
from ytktv.separation.runtime import Runtime


class InstalledRuntime(Runtime):
    def installed_variant(self):
        return "whisper"


def fake_whisper(command, **_kwargs):
    out = Path(command[3])
    out.write_text(json.dumps([{"start": 1.0, "end": 3.0, "text": "la la", "words": [[1.0, 0]]}]))
    return subprocess.CompletedProcess(command, 0, stdout="@@YTKTV {}", stderr="")


def test_ai_lyrics_are_written_once_and_kept(tmp_path):
    audio_calls = []

    def audio(video_id, dest):
        audio_calls.append(video_id)
        (dest / "a.wav").write_bytes(b"x")
        return dest / "a.wav"

    done = []
    writer = lyrics_ai.AiLyrics(
        InstalledRuntime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
        audio,
        lambda video_id, lines: done.append((video_id, lines)),
        run=fake_whisper,
        folder=tmp_path / "cache",
    )
    writer.request("abc")
    wait_for(lambda: bool(done))
    assert done[0][0] == "abc" and done[0][1][0].text == "la la"
    assert writer.cached("abc")[0].words == ((1.0, 0),)
    writer.request("abc")  # kept: not written again
    time.sleep(0.1)
    assert audio_calls == ["abc"] and not (tmp_path / "cache" / "work" / "abc").exists()


def test_nothing_happens_without_the_download(tmp_path):
    writer = lyrics_ai.AiLyrics(
        Runtime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
        lambda *_: (_ for _ in ()).throw(AssertionError("no download")),
        folder=tmp_path / "cache",
    )
    assert not writer.installed
    writer.request("abc")  # quietly does nothing


def test_controller_uses_ai_lyrics_when_a_song_has_none(tmp_path):
    controller, player, _ = make_controller(tmp_path)
    try:
        writer = lyrics_ai.AiLyrics(
            InstalledRuntime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
            lambda video_id, dest: (dest / "a.wav").write_bytes(b"x") or dest / "a.wav",
            controller.ai_lyrics_ready,
            run=fake_whisper,
            folder=tmp_path / "cache",
        )
        controller.ai_lyrics = writer
        controller.settings.ai_lyrics = True
        controller.resolver.lyrics = lambda *_a: []  # the video has no subtitles
        controller.enqueue(make_song(1))
        wait_for(lambda: bool(controller.lyrics), timeout=5)
        assert controller.lyrics[0].text == "la la"
    finally:
        controller.close()


def test_worker_script_is_standalone():
    source = lyrics_ai.WORKER.read_text()
    assert "ytktv" not in source.split('"""', 2)[2] and "faster_whisper" in source


def test_worker_turns_segments_into_lines():
    import runpy

    worker = runpy.run_path(str(lyrics_ai.WORKER))  # it must load without ytktv installed
    segments = [
        {"start": 0.5, "end": 2.0, "text": " hello there ",
         "words": [{"start": 0.5, "word": " hello"}, {"start": 1.2, "word": " there"}]},
        {"start": 3.0, "end": 4.0, "text": "  ", "words": []},
    ]  # fmt: skip
    assert worker["lines_from"](segments) == [
        {"start": 0.5, "end": 2.0, "text": "hello there", "words": [[0.5, 0], [1.2, 6]]}
    ]
    assert lyrics_ai.best_variant("Darwin", "arm64") == "whisper-mlx"


class GpuRuntime(Runtime):
    def installed_variant(self):
        return "whisper-cuda"


def gpu_writer(tmp_path, controller, run=fake_whisper, vocals=lambda _v: None):
    return lyrics_ai.AiLyrics(
        GpuRuntime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
        lambda video_id, dest: (dest / "a.wav").write_bytes(b"x") or dest / "a.wav",
        controller.ai_lyrics_ready,
        run=run,
        folder=tmp_path / "cache",
        vocals=vocals,
    )


def test_with_a_gpu_every_song_is_written_here_and_replaces_the_online_lyrics(tmp_path):
    from ytktv.youtube.lyrics import LyricLine

    controller, _player, _ = make_controller(tmp_path)
    seen = []
    gate = __import__("threading").Event()

    def slow_whisper(command, **kwargs):
        seen.append(command)
        gate.wait(5)
        return fake_whisper(command, **kwargs)

    try:
        controller.ai_lyrics = gpu_writer(tmp_path, controller, slow_whisper)
        online = [LyricLine(0.0, 2.0, "hello online")]
        controller.resolver.lyrics = lambda *_a: online  # the video has subtitles
        controller.enqueue(make_song(1))
        wait_for(lambda: controller.lyrics_source == "online", timeout=5)
        assert controller.lyrics[0].text == "hello online"  # shown while Whisper works
        wait_for(lambda: bool(seen), timeout=5)
        hint = Path(seen[0][-1]).read_text(encoding="utf-8")
        assert hint == "hello online"  # the words help Whisper; the timing is its own
        gate.set()
        wait_for(lambda: controller.lyrics_source == "local", timeout=5)
        assert controller.lyrics[0].text == "la la"
    finally:
        gate.set()
        controller.close()


def test_without_a_gpu_online_lyrics_stay(tmp_path):
    from ytktv.youtube.lyrics import LyricLine

    controller, _player, _ = make_controller(tmp_path)
    calls = []
    try:
        controller.ai_lyrics = lyrics_ai.AiLyrics(
            InstalledRuntime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
            lambda *_a: calls.append("audio"),
            controller.ai_lyrics_ready,
            run=lambda *a, **k: calls.append("whisper"),
            folder=tmp_path / "cache",
        )
        controller.resolver.lyrics = lambda *_a: [LyricLine(0.0, 2.0, "hello online")]
        controller.enqueue(make_song(1))
        wait_for(lambda: controller.lyrics_source == "online", timeout=5)
        time.sleep(0.2)
        assert calls == [] and controller.lyrics[0].text == "hello online"
    finally:
        controller.close()


def test_the_separated_vocals_are_what_whisper_hears(tmp_path):
    vocals = tmp_path / "vocals.flac"
    vocals.write_bytes(b"v")
    heard = []

    def whisper(command, **kwargs):
        heard.append(command[2])
        return fake_whisper(command, **kwargs)

    writer = lyrics_ai.AiLyrics(
        GpuRuntime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
        lambda *_a: (_ for _ in ()).throw(AssertionError("no download: the vocals are here")),
        run=whisper,
        folder=tmp_path / "cache",
        vocals=lambda _v: vocals,
    )
    writer.write("abc")
    assert heard == [str(vocals)]


def test_the_song_on_jumps_the_queue(tmp_path):
    writer = lyrics_ai.AiLyrics(
        GpuRuntime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
        lambda *_a: None,
        folder=tmp_path / "cache",
    )
    writer._busy = True  # nothing is taken off the queue while we look at it
    writer.request("later")
    writer.request("next")
    writer.request("now", first=True)
    writer.request("next", first=True)
    assert [v for v, _, _ in writer._waiting] == ["next", "now", "later"]
