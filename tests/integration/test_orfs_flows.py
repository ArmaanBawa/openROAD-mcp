"""
Integration tests for OpenROAD-MCP against real ORFS flows.

These tests require:
  - OpenROAD installed and in PATH
  - ORFS (OpenROAD-flow-scripts) available
  - Run via: make test-integration (uses Docker with openroad/orfs image)

Tests use the 'gcd' design (Greatest Common Divisor) which is small and ships
with ORFS, keeping test times reasonable (~2-5 minutes per flow).
"""

import os
import time

import pytest

# Skip entire module if OpenROAD is not available
pytestmark = pytest.mark.skipif(
    os.system("which openroad > /dev/null 2>&1") != 0,
    reason="OpenROAD not available in PATH",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _openroad_available() -> bool:
    """Check if OpenROAD binary is accessible."""
    return os.system("which openroad > /dev/null 2>&1") == 0


def _orfs_available() -> bool:
    """Check if ORFS environment is set up."""
    return os.path.isdir("/OpenROAD-flow-scripts") or os.environ.get("ORFS_PATH") is not None


def _get_orfs_path() -> str:
    """Return the ORFS root path."""
    return os.environ.get("ORFS_PATH", "/OpenROAD-flow-scripts")


# ---------------------------------------------------------------------------
# Session management helpers
# ---------------------------------------------------------------------------


async def _create_session():
    """Create an MCP session and return the session manager + session ID."""
    from openroad_mcp.core.manager import OpenROADManager

    manager = OpenROADManager()
    session_id = await manager.create_session()
    return manager, session_id


async def _execute_command(manager, session_id: str, command: str, timeout: int = 60):
    """Execute a command in a session and return the result."""
    result = await manager.execute_command(session_id, command, timeout=timeout)
    return result


# ---------------------------------------------------------------------------
# Tests: Session lifecycle
# ---------------------------------------------------------------------------


class TestSessionLifecycle:
    """Test basic session creation and management."""

    @pytest.mark.asyncio
    async def test_create_session(self):
        """Verify a new OpenROAD session can be created."""
        manager, session_id = await _create_session()
        assert session_id is not None
        assert len(session_id) > 0

        # Cleanup
        await manager.terminate_session(session_id)

    @pytest.mark.asyncio
    async def test_create_multiple_sessions(self):
        """Verify multiple concurrent sessions can exist."""
        manager, sid1 = await _create_session()
        _, sid2 = await _create_session()

        assert sid1 != sid2

        sessions = await manager.list_sessions()
        assert len(sessions) >= 2

        # Cleanup
        await manager.terminate_session(sid1)
        await manager.terminate_session(sid2)

    @pytest.mark.asyncio
    async def test_terminate_session(self):
        """Verify session termination cleans up resources."""
        manager, session_id = await _create_session()
        await manager.terminate_session(session_id)

        # Session should no longer be active
        sessions = await manager.list_sessions()
        active_ids = [s.get("session_id", s.get("id")) for s in sessions]
        assert session_id not in active_ids


# ---------------------------------------------------------------------------
# Tests: OpenROAD command execution
# ---------------------------------------------------------------------------


class TestCommandExecution:
    """Test running OpenROAD commands through MCP sessions."""

    @pytest.mark.asyncio
    async def test_simple_command(self):
        """Run a simple Tcl command in OpenROAD."""
        manager, session_id = await _create_session()

        result = await _execute_command(manager, session_id, "puts hello")
        assert result is not None

        await manager.terminate_session(session_id)

    @pytest.mark.asyncio
    async def test_openroad_version(self):
        """Verify OpenROAD version is retrievable."""
        manager, session_id = await _create_session()

        result = await _execute_command(manager, session_id, "puts [ord::openroad_version]")
        assert result is not None

        await manager.terminate_session(session_id)

    @pytest.mark.asyncio
    async def test_command_timeout(self):
        """Verify that commands respect timeout settings."""
        manager, session_id = await _create_session()

        start = time.time()
        try:
            # This should timeout — 'after' sleeps in Tcl
            await _execute_command(manager, session_id, "after 30000", timeout=3)
        except (TimeoutError, Exception):
            elapsed = time.time() - start
            assert elapsed < 10, f"Timeout took too long: {elapsed:.1f}s"

        await manager.terminate_session(session_id)


# ---------------------------------------------------------------------------
# Tests: Real ORFS flow stages (requires ORFS Docker image)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _orfs_available(),
    reason="ORFS not available — run with Docker: make test-integration",
)
class TestORFSFlows:
    """Integration tests using the gcd design through ORFS flow stages."""

    GCD_DESIGN = "gcd"
    PLATFORM = "nangate45"

    @pytest.mark.asyncio
    async def test_synthesis_stage(self):
        """Run synthesis on the gcd design."""
        manager, session_id = await _create_session()
        orfs_path = _get_orfs_path()

        # Source ORFS environment and run synthesis
        command = f"""
        source {orfs_path}/env.sh
        cd {orfs_path}/flow
        make DESIGN_CONFIG=designs/{self.PLATFORM}/{self.GCD_DESIGN}/config.mk synth
        """
        result = await _execute_command(manager, session_id, command, timeout=300)
        assert result is not None

        await manager.terminate_session(session_id)

    @pytest.mark.asyncio
    async def test_floorplan_stage(self):
        """Run floorplan on the gcd design (requires prior synthesis)."""
        manager, session_id = await _create_session()
        orfs_path = _get_orfs_path()

        command = f"""
        source {orfs_path}/env.sh
        cd {orfs_path}/flow
        make DESIGN_CONFIG=designs/{self.PLATFORM}/{self.GCD_DESIGN}/config.mk floorplan
        """
        result = await _execute_command(manager, session_id, command, timeout=300)
        assert result is not None

        await manager.terminate_session(session_id)

    @pytest.mark.asyncio
    async def test_complete_rtl_to_gdsii(self):
        """Run the complete RTL-to-GDSII flow on the gcd design.

        This is a long-running test (~5 minutes) that validates the full pipeline.
        """
        manager, session_id = await _create_session()
        orfs_path = _get_orfs_path()

        command = f"""
        source {orfs_path}/env.sh
        cd {orfs_path}/flow
        make DESIGN_CONFIG=designs/{self.PLATFORM}/{self.GCD_DESIGN}/config.mk finish
        """
        result = await _execute_command(manager, session_id, command, timeout=600)
        assert result is not None

        await manager.terminate_session(session_id)


# ---------------------------------------------------------------------------
# Tests: Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """Test that errors are handled gracefully."""

    @pytest.mark.asyncio
    async def test_invalid_tcl_command(self):
        """Sending an invalid Tcl command should not crash the session."""
        manager, session_id = await _create_session()

        await _execute_command(manager, session_id, "this_is_not_a_valid_command_12345")
        # Session should still be alive after error
        sessions = await manager.list_sessions()
        active_ids = [s.get("session_id", s.get("id")) for s in sessions]
        assert session_id in active_ids

        await manager.terminate_session(session_id)

    @pytest.mark.asyncio
    async def test_empty_command(self):
        """Empty commands should be handled gracefully."""
        manager, session_id = await _create_session()

        await _execute_command(manager, session_id, "")
        # Should not crash
        assert True

        await manager.terminate_session(session_id)


# ---------------------------------------------------------------------------
# Tests: Report image tools
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _orfs_available(),
    reason="ORFS not available — run with Docker: make test-integration",
)
class TestReportImages:
    """Test report image listing and reading after ORFS flow completion."""

    @pytest.mark.asyncio
    async def test_list_report_images(self):
        """Verify list_report_images returns images after a flow run."""
        try:
            from openroad_mcp.tools.report import list_report_images
        except ImportError:
            pytest.skip("report tools module not available")

        # This test assumes a prior flow run has produced images
        result = await list_report_images()
        # May return empty list if no flow has been run, which is OK
        assert isinstance(result, list | dict | str)

    @pytest.mark.asyncio
    async def test_read_report_image_not_found(self):
        """Reading a non-existent report image should error gracefully."""
        try:
            from openroad_mcp.tools.report import read_report_image
        except ImportError:
            pytest.skip("report tools module not available")

        try:
            await read_report_image("nonexistent_image.png")
        except (FileNotFoundError, Exception):
            pass  # Expected behavior
