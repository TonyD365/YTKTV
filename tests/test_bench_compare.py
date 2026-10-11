from __future__ import annotations

import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "bench_compare", Path(__file__).parent.parent / "benchmarks" / "compare.py"
)
compare = importlib.util.module_from_spec(spec)
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
    assert "| `a` | 1.00 ms | 2.00 ms | +100.0% | regression |" in report
    assert "| `noisy` | 1.00 ms | 2.00 ms | +100.0% |  |" in report
    assert "| `new` | - | 5.00 µs | new | |" in report
    assert "| `gone` | 1.00 s | - | removed | |" in report
    assert compare.MARKER in capsys.readouterr().out


def test_missing_baseline_passes(tmp_path):
    head = write(tmp_path / "head.json", {"a": (1e-3, 9e-4)})
    assert compare.main(["--base", str(tmp_path / "none.json"), "--head", str(head)]) == 0
    assert compare.main(["--head", str(head), "--threshold", "5"]) == 0


def test_within_threshold_passes(tmp_path):
    base = write(tmp_path / "base.json", {"a": (1.0e-3, 9e-4)})
    head = write(tmp_path / "head.json", {"a": (1.1e-3, 9.9e-4)})
    assert compare.main(["--base", str(base), "--head", str(head)]) == 0
