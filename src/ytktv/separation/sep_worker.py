"""Vocal-separation worker process.

Separation always runs here, outside the main app, at low priority: doing it
in-process starves the real-time audio mixer and makes the sound crackle.

This file is run as a script by the Python environment that YTKTV downloads
for separation (see ``ytktv.separation.runtime``), so it must not import
anything from ``ytktv``. Builds that carry the libraries themselves start it
through ``ytktv --separation-worker``. It speaks a tiny line protocol on stdout; every
protocol line starts with ``@@YTKTV`` so library chatter can be ignored.

    worker -> app   @@YTKTV {"event": "ready", "device": "GPU: ... (CUDA)", "kind": "cuda"}
    app -> worker   {"source": "in.wav", "output": "out.flac", "pitch": "melody.json"}
    worker -> app   @@YTKTV {"ok": true}   or   @@YTKTV {"ok": false, "error": "..."}
"""

import argparse
import json
import logging
import os
import shutil
import sys
from pathlib import Path

PREFIX = "@@YTKTV "
HOP_SECONDS = 0.05  # one melody value every 50 ms


def send(message):
    sys.stdout.write(PREFIX + json.dumps(message) + "\n")
    sys.stdout.flush()


def be_a_good_neighbour():
    """Run below the main app's priority and leave CPU cores free for it.

    Separation is heavy and not urgent; the app's audio mixer and video player
    are light and must never wait. Without this, working on a song makes the
    microphones crackle and the music stutter.
    """
    try:
        if os.name == "nt":
            import ctypes

            below_normal = 0x00004000
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), below_normal)
        else:
            os.nice(5)
    except Exception:
        pass
    threads = max(1, (os.cpu_count() or 4) // 2)
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ.setdefault(name, str(threads))
    return threads


def exit_with_parent():
    """Stop as soon as the app is gone, even in the middle of a song."""
    import threading
    import time

    parent = os.getppid()

    def watch():
        while True:
            time.sleep(2)
            if os.getppid() != parent:
                os._exit(0)

    if os.name != "nt":  # on Windows the closed stdin pipe ends the loop instead
        threading.Thread(target=watch, daemon=True).start()


def describe_device(use_directml):
    try:
        import torch
    except Exception as exc:  # the environment is broken; say so instead of dying silently
        return "unavailable", f"torch failed to load: {exc}"
    try:
        if torch.cuda.is_available():
            return "cuda", f"GPU: {torch.cuda.get_device_name(0)} (CUDA)"
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            return "mps", "GPU: Apple Silicon (Metal)"
        if use_directml:
            import torch_directml

            if torch_directml.is_available():
                return "directml", f"GPU: {torch_directml.device_name(0)} (DirectML)"
    except Exception:
        pass
    return "cpu", "CPU"


class Worker:
    def __init__(self, args):
        self.args = args
        self.separator = None

    def load(self):
        if self.separator is None:
            from audio_separator.separator import Separator

            Path(self.args.model_dir).mkdir(parents=True, exist_ok=True)
            Path(self.args.work_dir).mkdir(parents=True, exist_ok=True)
            separator = Separator(
                log_level=logging.WARNING,
                model_file_dir=self.args.model_dir,
                output_dir=self.args.work_dir,
                output_format="FLAC",  # both stems: the vocals give the melody for scoring
                use_directml=self.args.directml,
            )
            separator.load_model(model_filename=self.args.model)
            self.separator = separator
        return self.separator

    def _resolve(self, name):
        work_dir = Path(self.args.work_dir)
        produced = Path(name)
        if not produced.is_absolute():
            produced = work_dir / produced
        if not produced.exists():
            produced = work_dir / produced.name
        return produced

    def separate(self, source, output, pitch=None):
        outputs = [self._resolve(name) for name in self.load().separate(source)]
        instrumental = next((p for p in outputs if "instrumental" in p.name.lower()), None)
        vocals = next((p for p in outputs if "vocals" in p.name.lower()), None)
        try:
            if instrumental is None:
                raise RuntimeError("separation produced no instrumental")
            if pitch and vocals is not None:
                # The singer's melody, used as the reference for scoring. A failure here
                # must not cost the song its instrumental.
                try:
                    write_pitch(vocals, pitch)
                except Exception as exc:
                    sys.stderr.write(f"melody extraction failed: {exc}\n")
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(instrumental), output)
        finally:
            for leftover in outputs:
                if leftover.exists():
                    leftover.unlink()


def write_pitch(vocals, destination):
    """Track the pitch of the separated vocals and save it as compact JSON."""
    import soundfile

    try:
        from ytktv.separation import pitch_core
    except ImportError:  # running as a plain script in the downloaded environment
        import pitch_core  # type: ignore[no-redef]

    samples, rate = soundfile.read(str(vocals), dtype="float32", always_2d=True)
    notes = pitch_core.track(samples.mean(axis=1), rate, HOP_SECONDS)
    data = {"hop": HOP_SECONDS, "notes": [None if n is None else round(n, 2) for n in notes]}
    Path(destination).parent.mkdir(parents=True, exist_ok=True)
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(data, handle, separators=(",", ":"))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--directml", action="store_true")
    args = parser.parse_args(argv)

    threads = be_a_good_neighbour()
    exit_with_parent()
    kind, label = describe_device(args.directml)
    try:
        import torch

        torch.set_num_threads(threads)
    except Exception:
        pass
    send({"event": "ready", "kind": kind, "device": label})
    worker = Worker(args)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            worker.separate(request["source"], request["output"], request.get("pitch"))
        except Exception as exc:
            send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        else:
            send({"ok": True})


if __name__ == "__main__":
    main()
