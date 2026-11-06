"""Songs needed soon are separated in pieces, and their lyrics written piece by piece."""

from __future__ import annotations

import json
import sys
import textwrap
import time
from pathlib import Path

import numpy as np

from tests.helpers import make_controller, make_song, wait_for
from tests.test_align import FakeSoundfile
from ytktv import lyrics_ai
from ytktv.core.models import StemStatus
from ytktv.separation import sep_worker
from ytktv.separation.cache import StemCache
from ytktv.separation.remote import SubprocessSeparator
from ytktv.separation.worker import StemManager
from ytktv.youtube.lyrics import LyricLine

RATE = 1000  # small numbers keep the arithmetic readable


def test_pieces_cover_the_song_with_margins():
    pieces = sep_worker.plan_chunks(75 * RATE, RATE)
    assert [(s / RATE, e / RATE) for s, e, _, _ in pieces] == [(0, 30), (30, 60), (60, 75)]
    assert [(lo / RATE, hi / RATE) for _, _, lo, hi in pieces] == [(0, 33), (27, 63), (57, 75)]


def test_joined_pieces_keep_the_middles_and_fade_at_the_joins():
    song = np.sin(np.arange(75 * RATE) / 50.0)[:, None].astype("float32")
    whole = np.zeros_like(song)
    for start, end, low, high in sep_worker.plan_chunks(len(song), RATE):
        piece = song[low:high].copy()
        # The model is unsure at the edges: where they are margins, they must not be kept.
        if low < start:
            piece[:5] = 9.0
        if high > end:
            piece[-5:] = 9.0
        sep_worker.join_piece(whole, piece, start, end, low, fade=30)
    assert np.allclose(whole, song, atol=1e-6)  # same audio either side of a join


def test_the_worker_reports_each_piece_and_writes_whole_stems(tmp_path, monkeypatch, capsys):
    soundfile = FakeSoundfile()
    monkeypatch.setitem(sys.modules, "soundfile", soundfile)
    song = (0.5 * np.sin(np.arange(65 * RATE) / 30.0))[:, None].repeat(2, axis=1)
    soundfile.write(tmp_path / "source.wav", song, RATE)

    class Model:
        def separate(self, path):
            samples, _ = soundfile.read(path)
            soundfile.write(tmp_path / "x_(Instrumental).flac", samples * 0.8, RATE)
            soundfile.write(tmp_path / "x_(Vocals).flac", samples * 0.2, RATE)
            for name in ("x_(Instrumental).flac", "x_(Vocals).flac"):
                (tmp_path / name).write_bytes(b"")  # so the worker can delete them
            return ["x_(Instrumental).flac", "x_(Vocals).flac"]

    worker = sep_worker.Worker(type("Args", (), {"work_dir": str(tmp_path)})())
    worker.separator = Model()
    output = tmp_path / "out" / "instrumental.partial.flac"
    sep_worker.separate_in_chunks(worker, tmp_path / "source.wav", output, None, tmp_path / "p")
    events = [json.loads(line[8:]) for line in capsys.readouterr().out.splitlines()]
    assert [e["index"] for e in events] == [0, 1, 2] and events[-1]["last"]
    assert [(e["start"], e["end"], e["offset"]) for e in events][1] == (30.0, 60.0, 27.0)
    instrumental, _ = soundfile.read(output)
    vocals, _ = soundfile.read(output.with_name(sep_worker.VOCALS_FILE))
    assert len(instrumental) == len(song) and np.allclose(instrumental, song * 0.8, atol=1e-5)
    assert np.allclose(vocals, song * 0.2, atol=1e-5)
    heard, _ = soundfile.read(events[1]["vocals"])  # margins included, for Whisper
    assert len(heard) == 36 * RATE


PIECE_WORKER = textwrap.dedent(
    """
    import json, shutil, sys
    def send(message):
        print('@@YTKTV ' + json.dumps(message), flush=True)
    send({"event": "ready", "kind": "cpu", "device": "CPU"})
    for line in sys.stdin:
        request = json.loads(line)
        if request.get("chunks"):
            for i in range(2):
                send({"event": "chunk", "index": i, "last": i == 1, "start": i * 30.0,
                      "end": i * 30.0 + 30, "offset": max(0, i * 30.0 - 3), "vocals": "v"})
        shutil.copyfile(request["source"], request["output"])
        send({"ok": True})
    """
)


def test_the_client_passes_pieces_on_and_the_manager_uses_pieces_for_songs_soon(tmp_path):
    script = tmp_path / "worker.py"
    script.write_text(PIECE_WORKER)
    separator = SubprocessSeparator([sys.executable, "-u", str(script)], "m", tmp_path, tmp_path)

    def download(video_id, dest):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "source.wav").write_bytes(b"x")
        return dest / "source.wav"

    manager = StemManager(StemCache(tmp_path / "stems", 10**9), separator, download)
    pieces = []
    manager.on_chunk = lambda video_id, piece: pieces.append((video_id, piece["index"]))
    manager.order = lambda: ["now", "next", "later"]
    try:
        manager.start()
        for video_id in ("later", "now"):
            manager.request(video_id)
        # Both: on a slow runner "later" can start before "now" was even asked for.
        wait_for(
            lambda: all(manager.status(v) == StemStatus.READY for v in ("now", "later")),
            timeout=30,
        )
        assert ("now", 0) in pieces and ("now", 1) in pieces
        assert not any(v == "later" for v, _ in pieces)  # far off: separated whole
    finally:
        manager.stop()
        separator.close()


def test_a_piece_keeps_the_lines_that_begin_inside_it():
    heard = [
        LyricLine(1.0, 2.5, "cut at the start", ((1.0, 0),)),  # 28 s: the piece before's
        LyricLine(4.0, 6.0, "mine", ((4.0, 0),)),  # 31 s
        LyricLine(34.0, 35.0, "the next piece's"),  # 61 s
    ]
    kept = lyrics_ai.keep_piece(heard, offset=27.0, start=30.0, end=60.0)
    assert [(line.start, line.text, line.words) for line in kept] == [(31.0, "mine", ((31.0, 0),))]


def test_lyrics_grow_piece_by_piece_ahead_of_the_online_ones(tmp_path):
    from tests.test_ai_lyrics import GpuRuntime

    controller, _player, _ = make_controller(tmp_path)
    hints = []

    def transcribe(audio, hint, _language):
        hints.append(hint)
        index = int(audio.stem)
        return [LyricLine(5.0, 7.0, f"piece {index}")]

    try:
        controller.ai_lyrics = lyrics_ai.AiLyrics(
            GpuRuntime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
            lambda *_a: None,
            run=lambda *a, **k: time.sleep(10),  # the whole-song pass: not in this test
            folder=tmp_path / "cache",
        )
        controller.ai_pieces = lyrics_ai.PieceWriter(
            GpuRuntime(tmp_path / "rt", variants=lyrics_ai.VARIANTS),
            controller.ai_lyrics_partial,
            transcribe,
        )
        online = [LyricLine(10.0, 12.0, "early online"), LyricLine(40.0, 42.0, "late online")]
        controller.resolver.lyrics = lambda *_a: online
        song = make_song(1)
        controller.enqueue(song)
        wait_for(lambda: controller.lyrics_source == "online", timeout=5)
        audio = tmp_path / "000.wav"
        audio.write_bytes(b"v")
        piece = {"index": 0, "last": False, "start": 0.0, "end": 30.0, "offset": 0.0}
        controller._on_piece(song.video_id, {**piece, "vocals": str(audio)})
        wait_for(lambda: controller.lyrics_source == "partial", timeout=5)
        assert [line.text for line in controller.lyrics] == ["piece 0", "late online"]
        wait_for(lambda: not audio.exists())
        assert hints == ["early online late online"]
        audio = tmp_path / "001.wav"
        audio.write_bytes(b"v")
        later = {"index": 1, "last": True, "start": 30.0, "end": 60.0, "offset": 27.0}
        controller._on_piece(song.video_id, {**later, "vocals": str(audio)})
        wait_for(lambda: len(controller.lyrics) == 2 and controller.lyrics[1].start == 32.0)
        assert [line.text for line in controller.lyrics] == ["piece 0", "piece 1"]
        assert hints[1] == "piece 0"  # the words just before carry on into the next piece
        controller.ai_lyrics_ready(song.video_id, [LyricLine(5.0, 7.0, "whole song")])
        assert controller.lyrics_source == "local" and controller.lyrics[0].text == "whole song"
    finally:
        controller.close()


def test_without_a_gpu_pieces_are_thrown_away(tmp_path):
    controller, _player, _ = make_controller(tmp_path)
    try:
        audio = tmp_path / "000.wav"
        audio.write_bytes(b"v")
        controller._on_piece("x", {"vocals": str(audio)})
        assert not audio.exists() and Path(tmp_path).exists()
    finally:
        controller.close()
