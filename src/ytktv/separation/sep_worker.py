"""Vocal-separation worker process.

This file is run as a script by the Python environment that YTKTV downloads
for separation (see ``ytktv.separation.runtime``), so it must not import
anything from ``ytktv``. It speaks a tiny line protocol on stdout; every
protocol line starts with ``@@YTKTV`` so library chatter can be ignored.

    worker -> app   @@YTKTV {"event": "ready", "device": "GPU: ... (CUDA)", "kind": "cuda"}
    app -> worker   {"source": "in.wav", "output": "out.flac"}
    worker -> app   @@YTKTV {"ok": true}   or   @@YTKTV {"ok": false, "error": "..."}
"""

import argparse
import json
import logging
import shutil
import sys
from pathlib import Path

PREFIX = "@@YTKTV "


def send(message):
    sys.stdout.write(PREFIX + json.dumps(message) + "\n")
    sys.stdout.flush()


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
                output_format="FLAC",
                output_single_stem="Instrumental",
                use_directml=self.args.directml,
            )
            separator.load_model(model_filename=self.args.model)
            self.separator = separator
        return self.separator

    def separate(self, source, output):
        outputs = self.load().separate(source)
        if not outputs:
            raise RuntimeError("separation produced no output")
        work_dir = Path(self.args.work_dir)
        produced = Path(outputs[0])
        if not produced.is_absolute():
            produced = work_dir / produced
        if not produced.exists():
            produced = work_dir / produced.name
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(produced), output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--directml", action="store_true")
    args = parser.parse_args()

    kind, label = describe_device(args.directml)
    send({"event": "ready", "kind": kind, "device": label})
    worker = Worker(args)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            worker.separate(request["source"], request["output"])
        except Exception as exc:
            send({"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        else:
            send({"ok": True})


if __name__ == "__main__":
    main()
