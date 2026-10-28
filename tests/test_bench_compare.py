from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bench_compare", Path(__file__).parent.parent / "benchmarks" / "compare.py"
)
compare = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = compare  # dataclasses look their module up there
spec.loader.exec_module(compare)


def write(path: Path, values: dict[str, tuple[float, float]]) -> Path:
    benches = [
        {"fullname": f"benchmarks/{name}", "stats": {"median": median, "min": minimum}}
        for name, (median, minimum) in values.items()
    ]
    path.write_text(json.dumps({"benchmarks": benches}))
    return path


def test_regression_needs_both_median_and_min_to_slow_down(tmp_path, capsys):
    base = write(
        tmp_path / "base.json", {"a": (1e-3, 9e-4), "noisy": (1e-3, 9e-4), "gone": (1.0, 1.0)}
    )
    head = write(
        tmp_path / "head.json", {"a": (2e-3, 1.8e-3), "noisy": (2e-3, 9.1e-4), "new": (5e-6, 4e-6)}
    )
    out = tmp_path / "report.md"
    code = compare.main(["--base", str(base), "--head", str(head), "--output", str(out)])
    report = out.read_text(encoding="utf-8")
    assert code == 1
    assert "| `a` | 1.00 ms | 2.00 ms | 🔴 +100.0% **regression** |" in report
    # Only the median slowed down: shown, but not a regression.
    assert "| `noisy` | 1.00 ms | 2.00 ms | 🟡 +100.0% |" in report
    assert "| `new` | – | 5.00 µs | 🆕 new |" in report
    assert "| `gone` | 1.00 s | – | ➖ removed |" in report
    assert "❌ **1 benchmark(s) regressed by more than 25%.**" in report
    assert compare.MARKER in capsys.readouterr().out


def test_missing_baseline_passes(tmp_path):
    head = write(tmp_path / "head.json", {"a": (1e-3, 9e-4)})
    assert compare.main(["--base", str(tmp_path / "none.json"), "--head", str(head)]) == 0
    assert compare.main(["--head", str(head), "--threshold", "5"]) == 0


def test_within_threshold_passes(tmp_path):
    base = write(tmp_path / "base.json", {"a": (1.0e-3, 9e-4)})
    head = write(tmp_path / "head.json", {"a": (1.1e-3, 9.9e-4)})
    assert compare.main(["--base", str(base), "--head", str(head)]) == 0


def write_full(path: Path, entries: dict[str, float], commit: str = "abcdef0123") -> Path:
    benches = []
    for name, median in entries.items():
        stats = {
            "median": median,
            "min": median * 0.9,
            "mean": median,
            "max": median * 1.5,
            "stddev": median * 0.05,
            "iqr": median * 0.04,
            "rounds": 100,
        }
        benches.append({"fullname": f"benchmarks/{name}", "stats": stats})
    data = {
        "benchmarks": benches,
        "commit_info": {"id": commit, "branch": "main"},
        "machine_info": {"python_version": "3.13.1", "cpu": {"brand_raw": "Test CPU"}},
    }
    path.write_text(json.dumps(data))
    return path


def test_report_is_grouped_and_explains_itself(tmp_path):
    names = {
        "test_bench_dsp.py::test_mic_chain[512]": 1e-3,
        "test_bench_dsp.py::test_limiter": 1e-5,
        "test_bench_queue.py::test_add": 4e-6,
        "test_bench_api.py::test_get_state": 2e-3,
    }
    base = write_full(tmp_path / "base.json", names)
    faster = {**names, "test_bench_queue.py::test_add": 2e-6}
    head = write_full(tmp_path / "head.json", faster, commit="1234567890")
    out = tmp_path / "report.md"
    assert compare.main(["--base", str(base), "--head", str(head), "--output", str(out)]) == 0
    report = out.read_text(encoding="utf-8")
    assert "✅ **No regression above 25%.**" in report
    assert "4 benchmarks · 🟢 1 faster · ⚪ 3 unchanged" in report
    assert "base `abcdef0` (main) vs head `1234567` · Python 3.13.1, Test CPU" in report
    # The largest changes come first, then one section per area, in a fixed order.
    assert report.index("### Largest changes") < report.index("### 🎚️ Audio processing")
    assert report.index("### 🎚️ Audio processing") < report.index("### 📋 Queue and controller")
    assert report.index("### 📋 Queue and controller") < report.index("### 📱 Phone page API")
    # Audio blocks are measured against their own duration: 1 ms of a 10.7 ms block.
    assert (
        "| `test_mic_chain[512]` | 1.00 ms | 1.00 ms | ⚪ +0.0% | 9.4% of 10.7 ms | ±2% |" in report
    )
    assert "| `test_add` | 4.00 µs | 2.00 µs | 🟢 -50.0% | ±2% |" in report
    assert "<details><summary>All statistics (head)</summary>" in report
    assert (
        "| `test_bench_api.py::test_get_state` | 1.80 ms | 2.00 ms | 2.00 ms | 3.00 ms |" in report
    )


def test_tiny_benchmarks_cannot_fail_the_check(tmp_path):
    base = write(tmp_path / "base.json", {"tiny": (5e-7, 5e-7)})
    head = write(tmp_path / "head.json", {"tiny": (1e-6, 1e-6)})
    out = tmp_path / "report.md"
    assert compare.main(["--base", str(base), "--head", str(head), "--output", str(out)]) == 0
    assert "🟠 +100.0% (below noise floor)" in out.read_text(encoding="utf-8")


def test_no_results_fails(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"benchmarks": []}))
    assert compare.main(["--head", str(empty)]) == 1
