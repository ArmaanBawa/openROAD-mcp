#!/usr/bin/env python3
"""
benchmark_track.py — Historical benchmark tracking and regression detection.

Compares current benchmark results against a baseline or previous run.
Fails with a non-zero exit code if any metric regresses beyond the threshold.

Usage:
    python scripts/benchmark_track.py [--baseline BASELINE_DIR] [--current RESULTS_DIR] [--threshold 0.20]

The script reads JSON files from the results directory and compares them
against the baseline. Each JSON file should have been produced by
tests/performance/test_benchmarks.py.
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 0.20  # 20% regression threshold
DEFAULT_RESULTS_DIR = Path("tests/performance/results")
DEFAULT_BASELINE_DIR = Path("tests/performance/baseline")

# Metrics where higher is better (invert comparison)
HIGHER_IS_BETTER = {"throughput", "throughput_per_second"}

# Metrics to compare
TRACKED_METRICS = {"p50", "p95", "p99", "mean", "throughput", "throughput_per_second"}


def load_results(directory: Path) -> dict[str, dict]:
    """Load all JSON result files from a directory."""
    results: dict[str, dict] = {}
    if not directory.exists():
        return results
    for f in directory.glob("*.json"):
        with open(f) as fh:
            results[f.stem] = json.load(fh)
    return results


def compare_metric(name: str, baseline_val: float, current_val: float, threshold: float) -> tuple[str, bool]:
    """Compare a single metric. Returns (message, passed)."""
    if baseline_val == 0:
        return f"  {name}: baseline=0, current={current_val:.4f} (skipped)", True

    if name in HIGHER_IS_BETTER:
        # For throughput, regression means current < baseline
        change = (baseline_val - current_val) / baseline_val
        direction = "slower"
    else:
        # For latency, regression means current > baseline
        change = (current_val - baseline_val) / baseline_val
        direction = "slower"

    passed = change <= threshold
    symbol = "✅" if passed else "❌"
    sign = "+" if change > 0 else ""
    msg = f"  {symbol} {name}: {baseline_val:.4f} → {current_val:.4f} ({sign}{change*100:.1f}% {direction})"

    return msg, passed


def compare_results(
    baseline: dict[str, dict],
    current: dict[str, dict],
    threshold: float,
) -> tuple[list[str], bool]:
    """Compare current results against baseline. Returns (messages, all_passed)."""
    messages: list[str] = []
    all_passed = True

    for bench_name, current_data in current.items():
        messages.append(f"\n📊 {bench_name} (metric: {current_data.get('metric', 'unknown')})")

        if bench_name not in baseline:
            messages.append("  ⚠️  No baseline found — setting current as baseline")
            continue

        baseline_data = baseline[bench_name]

        for metric in TRACKED_METRICS:
            if metric in current_data and metric in baseline_data:
                msg, passed = compare_metric(metric, baseline_data[metric], current_data[metric], threshold)
                messages.append(msg)
                if not passed:
                    all_passed = False

    return messages, all_passed


def save_as_baseline(results_dir: Path, baseline_dir: Path) -> None:
    """Copy current results to baseline."""
    baseline_dir.mkdir(parents=True, exist_ok=True)
    for f in results_dir.glob("*.json"):
        dest = baseline_dir / f.name
        dest.write_text(f.read_text())
    print(f"📁 Saved current results as baseline in {baseline_dir}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Track and compare benchmark results")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE_DIR, help="Baseline results directory")
    parser.add_argument("--current", type=Path, default=DEFAULT_RESULTS_DIR, help="Current results directory")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD, help="Regression threshold (0.20 = 20%%)")
    parser.add_argument("--save-baseline", action="store_true", help="Save current results as the new baseline")
    args = parser.parse_args()

    print("=" * 60)
    print("  OpenROAD-MCP Benchmark Tracker")
    print("=" * 60)

    current = load_results(args.current)
    if not current:
        print(f"\n⚠️  No results found in {args.current}")
        print("   Run benchmarks first: make test-performance")
        return 1

    if args.save_baseline:
        save_as_baseline(args.current, args.baseline)
        return 0

    baseline = load_results(args.baseline)
    if not baseline:
        print(f"\n⚠️  No baseline found in {args.baseline}")
        print("   Saving current results as baseline...")
        save_as_baseline(args.current, args.baseline)
        return 0

    messages, all_passed = compare_results(baseline, current, args.threshold)

    for msg in messages:
        print(msg)

    print()
    if all_passed:
        print(f"✅ All benchmarks within {args.threshold*100:.0f}% regression threshold")
        return 0
    else:
        print(f"❌ Some benchmarks regressed beyond {args.threshold*100:.0f}% threshold")
        return 1


if __name__ == "__main__":
    sys.exit(main())
