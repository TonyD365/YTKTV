#!/usr/bin/env python3
"""Compare two pytest-benchmark JSON files and report regressions.

    python benchmarks/compare.py --base base.json --head head.json --threshold 25

Prints a Markdown report (also written to --output when given) and exits 1
when any benchmark got slower than the threshold. A benchmark only counts as
regressed when both its median and its minimum slowed down, which filters out
most of the scheduling noise on shared CI runners. Benchmarks faster than
--floor (default 2 µs) are listed but never fail the run: at that scale a
few nanoseconds of jitter is already tens of percent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MARKER = "<!-- ytktv-benchmark-report -->"


def load(path: Path | None) -> dict[str, dict[str, float]]:
    if path is None or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        bench["fullname"].split("benchmarks/")[-1]: {
            "median": bench["stats"]["median"],
            "min": bench["stats"]["min"],
        }
        for bench in data.get("benchmarks", [])
    }


def human(seconds: float) -> str:
    for unit, scale in (("s", 1.0), ("ms", 1e-3), ("µs", 1e-6)):
        if seconds >= scale:
            return f"{seconds / scale:.2f} {unit}"
    return f"{seconds / 1e-9:.0f} ns"


def change(base: float, head: float) -> float:
    return (head - base) / base * 100.0 if base > 0 else 0.0


def build_report(
    base: dict[str, dict[str, float]],
    head: dict[str, dict[str, float]],
    threshold: float,
    floor: float = 2e-6,
) -> tuple[str, list[str]]:
    lines = [MARKER, "## Benchmark report", ""]
    regressions: list[str] = []
    if not head:
        return "\n".join([*lines, "No benchmark results were produced for this change."]), [
            "no results"
        ]
    if not base:
        lines += ["No baseline on the base branch yet, so there is nothing to compare against.", ""]
    lines += ["| Benchmark | Base | Head | Change | |", "|---|---:|---:|---:|---|"]
    for name in sorted(head):
        new = head[name]
        old = base.get(name)
        if old is None:
            lines.append(f"| `{name}` | - | {human(new['median'])} | new | |")
            continue
        median_change = change(old["median"], new["median"])
        min_change = change(old["min"], new["min"])
        slower = median_change > threshold and min_change > threshold
        if slower and new["median"] < floor:
            verdict = "slower (below noise floor)"
        elif slower:
            verdict = "regression"
            regressions.append(name)
        elif median_change < -threshold and min_change < -threshold:
            verdict = "faster"
        else:
            verdict = ""
        before, after = human(old["median"]), human(new["median"])
        lines.append(f"| `{name}` | {before} | {after} | {median_change:+.1f}% | {verdict} |")
    for name in sorted(set(base) - set(head)):
        lines.append(f"| `{name}` | {human(base[name]['median'])} | - | removed | |")
    lines.append("")
    if regressions:
        lines.append(f"**{len(regressions)} benchmark(s) regressed by more than {threshold:g}%.**")
    elif base:
        lines.append(f"No regression above {threshold:g}%.")
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

    report, regressions = build_report(load(args.base), load(args.head), args.threshold, args.floor)
    print(report)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    return 1 if regressions else 0


if __name__ == "__main__":
    sys.exit(main())
