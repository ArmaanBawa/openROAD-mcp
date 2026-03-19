"""
Load testing for OpenROAD-MCP — validates concurrent session handling.

Tests:
  - 10, 25, and 50+ concurrent sessions
  - Resource monitoring (CPU, memory, file descriptors)
  - Identifies bottlenecks and breaking points

Run via: make test-performance (Docker) or pytest tests/performance/
"""

import asyncio
import os
import time

import psutil
import pytest

# Skip if OpenROAD not available
pytestmark = pytest.mark.skipif(
    os.system("which openroad > /dev/null 2>&1") != 0,
    reason="OpenROAD not available in PATH",
)


def _get_system_metrics() -> dict:
    """Capture current system resource usage."""
    process = psutil.Process()
    return {
        "cpu_percent": psutil.cpu_percent(interval=0.1),
        "memory_rss_mb": process.memory_info().rss / (1024 * 1024),
        "memory_percent": process.memory_percent(),
        "open_fds": process.num_fds() if hasattr(process, "num_fds") else -1,
        "num_threads": process.num_threads(),
        "children": len(process.children(recursive=True)),
    }


async def _create_and_run_session(manager, session_idx: int, commands: int = 3):
    """Create a session, run commands, and return timing info."""
    start = time.perf_counter()
    try:
        session_id = await manager.create_session()
        creation_time = time.perf_counter() - start

        # Run some commands
        for i in range(commands):
            await manager.execute_command(session_id, f"puts session_{session_idx}_cmd_{i}", timeout=30)

        return {
            "session_idx": session_idx,
            "session_id": session_id,
            "creation_time": creation_time,
            "total_time": time.perf_counter() - start,
            "status": "success",
        }
    except Exception as e:
        return {
            "session_idx": session_idx,
            "session_id": None,
            "creation_time": time.perf_counter() - start,
            "total_time": time.perf_counter() - start,
            "status": f"error: {e}",
        }


# ---------------------------------------------------------------------------
# Load tests
# ---------------------------------------------------------------------------

class TestConcurrentSessions:
    """Test the system under concurrent session load."""

    @pytest.mark.asyncio
    async def test_10_concurrent_sessions(self):
        """Validate 10 concurrent sessions can coexist."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        metrics_before = _get_system_metrics()

        tasks = [_create_and_run_session(manager, i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        metrics_after = _get_system_metrics()

        successes = [r for r in results if r["status"] == "success"]
        failures = [r for r in results if r["status"] != "success"]

        print(f"\n🔄 10 sessions: {len(successes)} success, {len(failures)} failed")
        print(f"   Memory: {metrics_before['memory_rss_mb']:.0f}MB → {metrics_after['memory_rss_mb']:.0f}MB")
        print(f"   FDs: {metrics_before['open_fds']} → {metrics_after['open_fds']}")

        # Cleanup
        for r in successes:
            if r["session_id"]:
                await manager.terminate_session(r["session_id"])

        assert len(successes) >= 8, f"Too many failures: {len(failures)}/10"

    @pytest.mark.asyncio
    async def test_25_concurrent_sessions(self):
        """Validate 25 concurrent sessions."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        metrics_before = _get_system_metrics()

        tasks = [_create_and_run_session(manager, i) for i in range(25)]
        results = await asyncio.gather(*tasks)

        metrics_after = _get_system_metrics()

        successes = [r for r in results if r["status"] == "success"]
        failures = [r for r in results if r["status"] != "success"]

        print(f"\n🔄 25 sessions: {len(successes)} success, {len(failures)} failed")
        print(f"   Memory delta: +{metrics_after['memory_rss_mb'] - metrics_before['memory_rss_mb']:.0f}MB")

        # Cleanup
        for r in successes:
            if r["session_id"]:
                await manager.terminate_session(r["session_id"])

        assert len(successes) >= 20, f"Too many failures: {len(failures)}/25"

    @pytest.mark.asyncio
    async def test_50_concurrent_sessions(self):
        """Validate 50+ concurrent sessions — the target for production readiness."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        metrics_before = _get_system_metrics()

        # Stagger session creation slightly to avoid thundering herd
        results = []
        batch_size = 10
        for batch_start in range(0, 50, batch_size):
            batch = [
                _create_and_run_session(manager, i)
                for i in range(batch_start, min(batch_start + batch_size, 50))
            ]
            batch_results = await asyncio.gather(*batch)
            results.extend(batch_results)
            await asyncio.sleep(0.5)  # Brief pause between batches

        metrics_after = _get_system_metrics()

        successes = [r for r in results if r["status"] == "success"]
        failures = [r for r in results if r["status"] != "success"]

        print(f"\n🔄 50 sessions: {len(successes)} success, {len(failures)} failed")
        print(f"   Memory: {metrics_before['memory_rss_mb']:.0f}MB → {metrics_after['memory_rss_mb']:.0f}MB")
        print(f"   FDs: {metrics_before['open_fds']} → {metrics_after['open_fds']}")
        print(f"   Children: {metrics_before['children']} → {metrics_after['children']}")

        if failures:
            reasons = {r['status'] for r in failures}
            print(f"   Failure reasons: {reasons}")

        # Cleanup
        for r in successes:
            if r["session_id"]:
                try:
                    await manager.terminate_session(r["session_id"])
                except Exception:
                    pass

        # At least 80% should succeed
        assert len(successes) >= 40, f"Too many failures: {len(failures)}/50"


class TestResourceExhaustion:
    """Test behavior near resource limits."""

    @pytest.mark.asyncio
    async def test_file_descriptor_tracking(self):
        """Ensure file descriptors are properly cleaned up after sessions."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        process = psutil.Process()

        fds_before = process.num_fds() if hasattr(process, "num_fds") else 0

        # Create and destroy 10 sessions
        for i in range(10):
            sid = await manager.create_session()
            await manager.execute_command(sid, f"puts fd_test_{i}", timeout=10)
            await manager.terminate_session(sid)
            await asyncio.sleep(0.2)

        # Allow cleanup
        await asyncio.sleep(1)

        fds_after = process.num_fds() if hasattr(process, "num_fds") else 0

        fd_leak = fds_after - fds_before
        print(f"\n📊 FD leak check: before={fds_before}, after={fds_after}, delta={fd_leak}")

        # Allow some small FD growth but flag significant leaks
        assert fd_leak < 20, f"Possible FD leak: {fd_leak} file descriptors not cleaned up"
