"""Write timed lyrics for one song with faster-whisper. Runs inside the AI lyrics runtime.

usage: whisper_worker.py AUDIO OUTPUT.json MODELS_DIR [LANGUAGE] [HINT.txt]

HINT.txt holds the song's words from elsewhere: a prompt that helps with spelling.

Standalone: the ytktv package is not installed in that environment.
"""

import json
import sys

MODEL = "small"  # good for singing, still fine on a CPU


def lines_from(segments):
    """Lines in YTKTV's lyric format from Whisper segments (objects or dicts)."""

    def get(item, name):
        return item[name] if isinstance(item, dict) else getattr(item, name)

    lines = []
    for segment in segments:
        text = str(get(segment, "text")).strip()
        if not text:
            continue
        words, offset = [], 0
        for word in get(segment, "words") or []:
            piece = str(get(word, "word")).strip()
            at = text.find(piece, offset) if piece else -1
            if at >= 0:
                words.append([round(float(get(word, "start")), 2), at])
                offset = at + len(piece)
        start, end = float(get(segment, "start")), float(get(segment, "end"))
        lines.append({"start": round(start, 2), "end": round(end, 2), "text": text, "words": words})
    return lines


def transcribe(audio, models, language, hint=None):
    try:  # Apple Silicon: the GPU through MLX
        import mlx_whisper
    except ImportError:
        mlx_whisper = None
    if mlx_whisper is not None:
        result = mlx_whisper.transcribe(
            audio,
            path_or_hf_repo=f"mlx-community/whisper-{MODEL}-mlx",
            word_timestamps=True,
            language=language,
            initial_prompt=hint,
        )
        return lines_from(result.get("segments", []))
    from faster_whisper import WhisperModel

    try:  # an NVIDIA GPU when its libraries are there, else the CPU
        model = WhisperModel(MODEL, device="cuda", compute_type="float16", download_root=models)
    except Exception:
        model = WhisperModel(MODEL, device="cpu", compute_type="int8", download_root=models)
    segments, _info = model.transcribe(
        audio,
        language=language,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
        initial_prompt=hint,
    )
    return lines_from(segments)


def main() -> int:
    audio, output, models = sys.argv[1], sys.argv[2], sys.argv[3]
    language = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else None
    hint = None
    if len(sys.argv) > 5:
        with open(sys.argv[5], encoding="utf-8") as file:
            hint = file.read().strip() or None
    lines = transcribe(audio, models, language, hint)
    with open(output, "w", encoding="utf-8") as file:
        json.dump(lines, file, ensure_ascii=False)
    print("@@YTKTV " + json.dumps({"ok": True, "lines": len(lines)}), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
