"""
Performance benchmarks for OpenROAD-MCP.

Measures key performance metrics:
  - Session creation time (p50, p95, p99)
  - Command execution latency
  - Throughput (commands/second)

Results are output as JSON for historical tracking.
Run via: make test-performance (Docker) or pytest tests/performance/
"""

import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import pytest

# Skip if OpenROAD not available
pytestmark = pytest.mark.skipif(
    os.system("which openroad > /dev/null 2>&1") != 0,
    reason="OpenROAD not available in PATH",
)

# Output directory for benchmark results
BENCHMARK_OUTPUT_DIR = Path(__file__).parent / "results"


def _percentile(data: list[float], pct: int) -> float:
    """Calculate the given percentile of a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    idx = int(len(sorted_data) * pct / 100)
    return sorted_data[min(idx, len(sorted_data) - 1)]


def _save_benchmark_results(name: str, results: dict) -> None:
    """Save benchmark results to JSON for historical tracking."""
    BENCHMARK_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = BENCHMARK_OUTPUT_DIR / f"{name}.json"
    results["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results["commit"] = os.environ.get("GITHUB_SHA", "local")
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n📊 Benchmark results saved to: {output_file}")


# ---------------------------------------------------------------------------
# Benchmark: Session creation
# ---------------------------------------------------------------------------

class TestSessionCreationBenchmark:
    """Benchmark session creation time."""

    NUM_ITERATIONS = 10

    @pytest.mark.asyncio
    async def test_session_creation_latency(self):
        """Measure session creation time over multiple iterations."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        times: list[float] = []
        session_ids: list[str] = []

        for _ in range(self.NUM_ITERATIONS):
            start = time.perf_counter()
            sid = await manager.create_session()
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            session_ids.append(sid)

        # Clean up
        for sid in session_ids:
            await manager.terminate_session(sid)

        results = {
            "metric": "session_creation_time",
            "unit": "seconds",
            "iterations": self.NUM_ITERATIONS,
            "p50": _percentile(times, 50),
            "p95": _percentile(times, 95),
            "p99": _percentile(times, 99),
            "mean": statistics.mean(times),
            "stdev": statistics.stdev(times) if len(times) > 1 else 0,
            "min": min(times),
            "max": max(times),
        }

        _save_benchmark_results("session_creation", results)

        print(f"\n📊 Session creation: p50={results['p50']:.3f}s, "
              f"p95={results['p95']:.3f}s, p99={results['p99']:.3f}s")

        # Assertion: session creation should be under 5 seconds
        assert results["p95"] < 5.0, f"Session creation p95 too slow: {results['p95']:.3f}s"


# ---------------------------------------------------------------------------
# Benchmark: Command execution latency
# ---------------------------------------------------------------------------

class TestCommandLatencyBenchmark:
    """Benchmark command execution latency."""

    NUM_COMMANDS = 20

    @pytest.mark.asyncio
    async def test_command_execution_latency(self):
        """Measure command execution time for simple Tcl commands."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        session_id = await manager.create_session()
        times: list[float] = []

        # Warm up
        await manager.execute_command(session_id, "puts warmup", timeout=30)

        # Benchmark
        for i in range(self.NUM_COMMANDS):
            start = time.perf_counter()
            await manager.execute_command(session_id, f"puts iteration_{i}", timeout=30)
            elapsed = time.perf_counter() - start
            times.append(elapsed)

        await manager.terminate_session(session_id)

        results = {
            "metric": "command_execution_latency",
            "unit": "seconds",
            "iterations": self.NUM_COMMANDS,
            "p50": _percentile(times, 50),
            "p95": _percentile(times, 95),
            "p99": _percentile(times, 99),
            "mean": statistics.mean(times),
            "stdev": statistics.stdev(times) if len(times) > 1 else 0,
            "min": min(times),
            "max": max(times),
            "throughput_per_second": self.NUM_COMMANDS / sum(times) if sum(times) > 0 else 0,
        }

        _save_benchmark_results("command_latency", results)

        print(f"\n📊 Command latency: p50={results['p50']:.3f}s, "
              f"throughput={results['throughput_per_second']:.1f} cmd/s")

        # Assertion: simple commands should complete under 2 seconds
        assert results["p95"] < 2.0, f"Command latency p95 too slow: {results['p95']:.3f}s"


# ---------------------------------------------------------------------------
# Benchmark: Throughput
# ---------------------------------------------------------------------------

class TestThroughputBenchmark:
    """Benchmark sustained throughput."""

    DURATION_SECONDS = 10

    @pytest.mark.asyncio
    async def test_sustained_throughput(self):
        """Measure how many commands can be executed per second over a window."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        session_id = await manager.create_session()

        command_count = 0
        start = time.perf_counter()

        while time.perf_counter() - start < self.DURATION_SECONDS:
            await manager.execute_command(session_id, f"puts cmd_{command_count}", timeout=10)
            command_count += 1

        elapsed = time.perf_counter() - start
        throughput = command_count / elapsed

        await manager.terminate_session(session_id)

        results = {
            "metric": "sustained_throughput",
            "unit": "commands_per_second",
            "duration_seconds": elapsed,
            "total_commands": command_count,
            "throughput": throughput,
        }

        _save_benchmark_results("throughput", results)

        print(f"\n📊 Throughput: {throughput:.1f} cmd/s ({command_count} commands in {elapsed:.1f}s)")

        # Assertion: should sustain at least 1 cmd/s
        assert throughput > 1.0, f"Throughput too low: {throughput:.1f} cmd/s"
