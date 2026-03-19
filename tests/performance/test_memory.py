"""
Memory profiling and leak detection for OpenROAD-MCP.

Tests:
  - Create/destroy 100+ sessions and verify memory returns to baseline
  - Run many commands in a single session and check bounded growth
  - File descriptor cleanup verification
  - Zombie process detection after session termination

Uses tracemalloc (stdlib) and psutil for resource tracking.
Run via: make test-performance (Docker) or pytest tests/performance/
"""

import asyncio
import gc
import os
import tracemalloc

import psutil
import pytest

# Skip if OpenROAD not available
pytestmark = pytest.mark.skipif(
    os.system("which openroad > /dev/null 2>&1") != 0,
    reason="OpenROAD not available in PATH",
)

# Memory growth tolerance (in MB)
MEMORY_GROWTH_TOLERANCE_MB = 50
# Number of iterations for leak detection
LEAK_TEST_ITERATIONS = 50


def _get_memory_mb() -> float:
    """Get current process RSS in MB."""
    return psutil.Process().memory_info().rss / (1024 * 1024)


def _get_zombie_processes() -> list:
    """Find any zombie child processes."""
    current = psutil.Process()
    zombies = []
    for child in current.children(recursive=True):
        try:
            if child.status() == psutil.STATUS_ZOMBIE:
                zombies.append(child.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return zombies


# ---------------------------------------------------------------------------
# Memory leak detection: session create/destroy cycle
# ---------------------------------------------------------------------------


class TestMemoryLeaks:
    """Detect memory leaks through repeated session lifecycle operations."""

    @pytest.mark.asyncio
    async def test_session_create_destroy_memory(self):
        """Create and destroy sessions repeatedly, checking for memory leaks.

        After creating and destroying LEAK_TEST_ITERATIONS sessions, memory
        should return close to the baseline (within tolerance).
        """
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()

        # Force garbage collection and establish baseline
        gc.collect()
        await asyncio.sleep(1)
        baseline_mb = _get_memory_mb()

        tracemalloc.start()

        for i in range(LEAK_TEST_ITERATIONS):
            sid = await manager.create_session()
            await manager.execute_command(sid, f"puts leak_test_{i}", timeout=15)
            await manager.terminate_session(sid)

            # Periodic GC to simulate real-world conditions
            if i % 10 == 0:
                gc.collect()
                current_mb = _get_memory_mb()
                print(
                    f"  Iteration {i}/{LEAK_TEST_ITERATIONS}: {current_mb:.1f}MB "
                    f"(delta: {current_mb - baseline_mb:+.1f}MB)"
                )

        # Final cleanup
        gc.collect()
        await asyncio.sleep(2)

        snapshot = tracemalloc.take_snapshot()
        tracemalloc.stop()

        final_mb = _get_memory_mb()
        growth_mb = final_mb - baseline_mb

        print("\n📊 Memory leak test results:")
        print(f"   Baseline:    {baseline_mb:.1f}MB")
        print(f"   Final:       {final_mb:.1f}MB")
        print(f"   Growth:      {growth_mb:+.1f}MB")
        print(f"   Iterations:  {LEAK_TEST_ITERATIONS}")

        # Print top memory allocations
        print("\n   Top 5 memory allocations:")
        for stat in snapshot.statistics("lineno")[:5]:
            print(f"     {stat}")

        assert growth_mb < MEMORY_GROWTH_TOLERANCE_MB, (
            f"Memory leak detected: {growth_mb:.1f}MB growth after "
            f"{LEAK_TEST_ITERATIONS} create/destroy cycles "
            f"(tolerance: {MEMORY_GROWTH_TOLERANCE_MB}MB)"
        )

    @pytest.mark.asyncio
    async def test_long_running_session_memory(self):
        """Run many commands in a single session and check memory stays bounded."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        sid = await manager.create_session()

        gc.collect()
        baseline_mb = _get_memory_mb()

        num_commands = 200
        for i in range(num_commands):
            await manager.execute_command(sid, f"puts long_session_cmd_{i}", timeout=10)

        gc.collect()
        final_mb = _get_memory_mb()
        growth_mb = final_mb - baseline_mb

        await manager.terminate_session(sid)

        print("\n📊 Long session memory test:")
        print(f"   Commands:  {num_commands}")
        print(f"   Baseline:  {baseline_mb:.1f}MB")
        print(f"   Final:     {final_mb:.1f}MB")
        print(f"   Growth:    {growth_mb:+.1f}MB")

        assert growth_mb < MEMORY_GROWTH_TOLERANCE_MB, (
            f"Memory grew by {growth_mb:.1f}MB during {num_commands} commands "
            f"in a single session (tolerance: {MEMORY_GROWTH_TOLERANCE_MB}MB)"
        )


# ---------------------------------------------------------------------------
# Zombie process and cleanup detection
# ---------------------------------------------------------------------------


class TestProcessCleanup:
    """Verify proper cleanup of child processes and file descriptors."""

    @pytest.mark.asyncio
    async def test_no_zombie_processes_after_termination(self):
        """Ensure no zombie processes remain after session termination."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()

        zombies_before = _get_zombie_processes()

        # Create and destroy 10 sessions
        for i in range(10):
            sid = await manager.create_session()
            await manager.execute_command(sid, f"puts zombie_test_{i}", timeout=10)
            await manager.terminate_session(sid)
            await asyncio.sleep(0.3)

        # Wait for process cleanup
        await asyncio.sleep(2)
        gc.collect()

        zombies_after = _get_zombie_processes()

        new_zombies = len(zombies_after) - len(zombies_before)
        print("\n📊 Zombie process check:")
        print(f"   Before: {len(zombies_before)}")
        print(f"   After:  {len(zombies_after)}")
        print(f"   New:    {new_zombies}")

        assert new_zombies == 0, (
            f"Found {new_zombies} zombie processes after session termination. PIDs: {zombies_after}"
        )

    @pytest.mark.asyncio
    async def test_file_descriptor_cleanup(self):
        """Verify file descriptors are properly released after session cleanup."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        process = psutil.Process()

        # Baseline
        gc.collect()
        fds_baseline = process.num_fds() if hasattr(process, "num_fds") else 0

        # Create 20 sessions, run commands, terminate
        for i in range(20):
            sid = await manager.create_session()
            await manager.execute_command(sid, f"puts fd_cleanup_{i}", timeout=10)
            await manager.terminate_session(sid)

        # Allow cleanup
        await asyncio.sleep(2)
        gc.collect()

        fds_final = process.num_fds() if hasattr(process, "num_fds") else 0
        fd_leak = fds_final - fds_baseline

        print("\n📊 FD cleanup verification:")
        print(f"   Baseline: {fds_baseline}")
        print(f"   Final:    {fds_final}")
        print(f"   Leak:     {fd_leak}")

        assert fd_leak < 10, (
            f"File descriptor leak detected: {fd_leak} FDs not cleaned up after 20 session create/destroy cycles"
        )

    @pytest.mark.asyncio
    async def test_child_process_cleanup(self):
        """Verify no lingering child processes after session termination."""
        from openroad_mcp.session.manager import SessionManager

        manager = SessionManager()
        process = psutil.Process()

        children_before = len(process.children(recursive=True))

        # Create 5 sessions
        sids = []
        for _ in range(5):
            sid = await manager.create_session()
            sids.append(sid)

        children_during = len(process.children(recursive=True))

        # Terminate all
        for sid in sids:
            await manager.terminate_session(sid)

        await asyncio.sleep(2)
        gc.collect()

        children_after = len(process.children(recursive=True))

        print("\n📊 Child process cleanup:")
        print(f"   Before creation:      {children_before}")
        print(f"   During (5 sessions):  {children_during}")
        print(f"   After termination:    {children_after}")

        residual = children_after - children_before
        assert residual <= 1, f"Found {residual} lingering child processes after all sessions terminated"
