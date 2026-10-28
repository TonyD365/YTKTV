#!/usr/bin/env python3
"""Compare two pytest-benchmark JSON files and report regressions.

    python benchmarks/compare.py --base base.json --head head.json --threshold 25

Prints a Markdown report (also written to --output when given) and exits 1 when any
benchmark got slower than the threshold. A benchmark only counts as regressed when both
its median and its minimum slowed down, which filters out most of the scheduling noise
on shared CI runners. Benchmarks faster than --floor (default 2 µs) are listed but never
fail the run: at that scale a few nanoseconds of jitter is already tens of percent.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MARKER = "<!-- ytktv-benchmark-report -->"
SAMPLE_RATE = 48000  # the audio benchmarks process blocks at this rate
SMALL_CHANGE = 5.0  # percent; below this a change is shown as unchanged
TOP = 5  # how many of the largest changes are listed at the top

# Sections of the report, by benchmark file: (title, what the numbers mean).
SECTIONS = {
    "test_bench_dsp.py": (
        "🎚️ Audio processing",
        "Time to process one block of microphone audio. *Real time* is the share of the "
        "block's own duration it takes: it has to stay well under 100%, or the sound breaks up.",
    ),
    "test_bench_queue.py": (
        "📋 Queue and controller",
        "Queue operations and building the state that every screen and phone update is made of.",
    ),
    "test_bench_api.py": (
        "📱 Phone page API",
        "Requests a phone makes, answered by the local web server.",
    ),
    "test_bench_search.py": (
        "🔎 Search and parsing",
        "Turning YouTube results into songs and playable streams (no network involved).",
    ),
}
OTHER = ("🧪 Other", "")


@dataclass
class Bench:
    stats: dict[str, float]
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class Run:
    benches: dict[str, Bench] = field(default_factory=dict)
    commit: str = ""
    branch: str = ""
    machine: str = ""


def load_run(path: Path | None) -> Run:
    run = Run()
    if path is None or not path.exists():
        return run
    data = json.loads(path.read_text(encoding="utf-8"))
    for bench in data.get("benchmarks", []):
        name = bench["fullname"].split("benchmarks/")[-1]
        run.benches[name] = Bench(dict(bench["stats"]), dict(bench.get("params") or {}))
    commit = data.get("commit_info") or {}
    run.commit = str(commit.get("id") or "")[:7]
    run.branch = str(commit.get("branch") or "")
    machine = data.get("machine_info") or {}
    cpu = (machine.get("cpu") or {}).get("brand_raw") or machine.get("processor") or ""
    python = machine.get("python_version") or ""
    run.machine = ", ".join(part for part in (f"Python {python}" if python else "", cpu) if part)
    return run


def load(path: Path | None) -> dict[str, dict[str, float]]:
    """Name -> statistics; kept for scripts that only need the numbers."""
    return {name: bench.stats for name, bench in load_run(path).benches.items()}


def human(seconds: float) -> str:
    for unit, scale in (("s", 1.0), ("ms", 1e-3), ("µs", 1e-6)):
        if seconds >= scale:
            return f"{seconds / scale:.2f} {unit}"
    return f"{seconds / 1e-9:.0f} ns"


def change(base: float, head: float) -> float:
    return (head - base) / base * 100.0 if base > 0 else 0.0


def block_frames(name: str) -> int | None:
    """Audio block size of a DSP benchmark, from its parameter ("test_eq[512]")."""
    if not name.startswith("test_bench_dsp.py"):
        return None
    match = re.search(r"\[(\d+)\]$", name)
    return int(match.group(1)) if match else None


def spread(stats: dict[str, float]) -> str:
    """How much the runs varied: the interquartile range as a share of the median."""
    median, iqr = stats.get("median", 0.0), stats.get("iqr")
    if not median or iqr is None:
        return ""
    return f"±{iqr / median * 50:.0f}%"


@dataclass
class Row:
    name: str
    base: dict[str, float] | None
    head: dict[str, float] | None
    verdict: str = ""  # "regression", "noise", "slower", "faster", "same", "new", "removed"
    percent: float = 0.0


def judge(name: str, old: Bench | None, new: Bench | None, threshold: float, floor: float) -> Row:
    if new is None:
        return Row(name, old.stats if old else None, None, "removed")
    if old is None:
        return Row(name, None, new.stats, "new")
    median_change = change(old.stats["median"], new.stats["median"])
    min_change = change(old.stats["min"], new.stats["min"])
    row = Row(name, old.stats, new.stats, "same", median_change)
    if median_change > threshold and min_change > threshold:
        row.verdict = "noise" if new.stats["median"] < floor else "regression"
    elif median_change < -SMALL_CHANGE and min_change < -SMALL_CHANGE:
        row.verdict = "faster"
    elif median_change > SMALL_CHANGE:
        row.verdict = "slower"
    return row


BADGES = {
    "regression": "🔴",
    "noise": "🟠",
    "slower": "🟡",
    "faster": "🟢",
    "same": "⚪",
    "new": "🆕",
    "removed": "➖",
}


def change_cell(row: Row) -> str:
    badge = BADGES[row.verdict]
    if row.verdict == "new":
        return f"{badge} new"
    if row.verdict == "removed":
        return f"{badge} removed"
    text = f"{badge} {row.percent:+.1f}%"
    if row.verdict == "regression":
        text += " **regression**"
    elif row.verdict == "noise":
        text += " (below noise floor)"
    return text


def realtime_cell(name: str, stats: dict[str, float] | None) -> str:
    frames = block_frames(name)
    if frames is None or not stats:
        return ""
    block = frames / SAMPLE_RATE
    share = stats["median"] / block * 100
    return f"{share:.1f}% of {block * 1000:.1f} ms"


def table(rows: list[Row], audio: bool) -> list[str]:
    header = (
        "| Benchmark | Base | Head | Change |" + (" Real time |" if audio else "") + " Spread |"
    )
    lines = [header, "|---|---:|---:|---|" + ("---:|" if audio else "") + "---:|"]
    for row in rows:
        short = row.name.split("::", 1)[-1]
        before = human(row.base["median"]) if row.base else "–"
        after = human(row.head["median"]) if row.head else "–"
        cells = [f"`{short}`", before, after, change_cell(row)]
        if audio:
            cells.append(realtime_cell(row.name, row.head))
        cells.append(spread(row.head) if row.head else "")
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def details(rows: list[Row]) -> list[str]:
    lines = [
        "<details><summary>All statistics (head)</summary>",
        "",
        "| Benchmark | Min | Median | Mean | Max | Std dev | IQR | Rounds |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        stats = row.head
        if not stats:
            continue
        cells = [f"`{row.name}`"]
        for key in ("min", "median", "mean", "max", "stddev", "iqr"):
            cells.append(human(stats[key]) if key in stats else "")
        cells.append(str(int(stats.get("rounds", 0))) if "rounds" in stats else "")
        lines.append("| " + " | ".join(cells) + " |")
    return [*lines, "", "</details>"]


def build_report(
    base: Run | dict[str, dict[str, float]],
    head: Run | dict[str, dict[str, float]],
    threshold: float,
    floor: float = 2e-6,
) -> tuple[str, list[str]]:
    if isinstance(base, dict):
        base = Run({name: Bench(stats) for name, stats in base.items()})
    if isinstance(head, dict):
        head = Run({name: Bench(stats) for name, stats in head.items()})
    lines = [MARKER, "## 📊 Benchmark report", ""]
    if not head.benches:
        lines.append("❌ No benchmark results were produced for this change.")
        return "\n".join(lines), ["no results"]

    names = sorted(set(head.benches) | set(base.benches))
    rows = [judge(n, base.benches.get(n), head.benches.get(n), threshold, floor) for n in names]
    regressions = [row.name for row in rows if row.verdict == "regression"]
    count = {verdict: sum(row.verdict == verdict for row in rows) for verdict in BADGES}

    if not base.benches:
        lines.append(
            "ℹ️ No baseline on the base branch yet, so there is nothing to compare against."
        )
    elif regressions:
        lines.append(
            f"❌ **{len(regressions)} benchmark(s) regressed by more than {threshold:g}%.**"
        )
    else:
        lines.append(f"✅ **No regression above {threshold:g}%.**")
    summary = [
        f"{BADGES[v]} {count[v]} {label}"
        for v, label in (
            ("faster", "faster"),
            ("slower", "a little slower"),
            ("same", "unchanged"),
            ("new", "new"),
            ("removed", "removed"),
        )
        if count[v]
    ]
    lines += ["", " · ".join([f"{len([r for r in rows if r.head])} benchmarks", *summary]), ""]
    refs = []
    if base.commit:
        refs.append(f"base `{base.commit}`" + (f" ({base.branch})" if base.branch else ""))
    if head.commit:
        refs.append(f"head `{head.commit}`")
    context = " vs ".join(refs)
    if head.machine:
        context += (" · " if context else "") + head.machine
    if context:
        lines += [
            f"<sub>{context} · both measured on the same runner, one after the other</sub>",
            "",
        ]

    moved = [r for r in rows if r.verdict in ("regression", "noise", "slower", "faster")]
    moved.sort(key=lambda r: abs(r.percent), reverse=True)
    if moved:
        lines += ["### Largest changes", ""]
        lines += table(moved[:TOP], audio=any(block_frames(r.name) for r in moved[:TOP]))
        lines.append("")

    grouped: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        section = SECTIONS.get(row.name.split("::", 1)[0], OTHER)
        grouped.setdefault(section, []).append(row)
    order = [*SECTIONS.values(), OTHER]
    for section in order:
        section_rows = grouped.get(section)
        if not section_rows:
            continue
        title, explanation = section
        lines += [f"### {title}", ""]
        if explanation:
            lines += [f"<sub>{explanation}</sub>", ""]
        lines += table(section_rows, audio=section == SECTIONS["test_bench_dsp.py"])
        lines.append("")

    lines += details(rows)
    lines += [
        "",
        f"<sub>Times are medians. 🔴 regression: median **and** minimum both more than "
        f"{threshold:g}% slower (fails the check) · 🟠 the same, but too fast to measure "
        f"reliably (under {human(floor)}) · 🟡 slower by more than {SMALL_CHANGE:g}% · "
        f"🟢 faster by more than {SMALL_CHANGE:g}% · ⚪ within {SMALL_CHANGE:g}% · "
        "Spread: half the interquartile range, as a share of the median.</sub>",
    ]
    return "\n".join(lines), regressions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", type=Path, help="benchmark JSON from the base branch (optional)")
    parser.add_argument("--head", type=Path, required=True, help="benchmark JSON from this change")
    parser.add_argument("--threshold", type=float, default=25.0, help="allowed slowdown in percent")
    parser.add_argument(
        "--floor", type=float, default=2e-6, help="ignore regressions under this many seconds"
    )
    parser.add_argument("--output", type=Path, help="also write the Markdown report here")
    args = parser.parse_args(argv)

    report, regressions = build_report(
        load_run(args.base), load_run(args.head), args.threshold, args.floor
    )
    print(report)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
