###############################################################################
#                    OpenROAD-MCP Production Docker Image                     #
#                                                                             #
#  Multi-stage build for production deployment.                               #
#  Based on openroad/orfs:latest (includes OpenROAD + Yosys + ORFS).          #
#                                                                             #
#  Build:  docker build -t openroad-mcp .                                     #
#  Run:    docker run --rm -it openroad-mcp                                   #
###############################################################################

# =============================================================================
# Stage 1: Builder — Install Python deps, build the MCP server package
# =============================================================================
FROM openroad/orfs:latest AS builder

# Install uv package manager
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /build

# Copy dependency manifests first for optimal layer caching.
# Changes to source code won't invalidate the dependency layer.
COPY pyproject.toml uv.lock README.md ./
COPY requirements.txt requirements-test.txt ./

# Install production dependencies only (no dev extras)
RUN uv sync --inexact --no-dev

# Now copy the full source tree
COPY src/ src/

# =============================================================================
# Stage 2: Runtime — Minimal production image
# =============================================================================
FROM openroad/orfs:latest AS runtime

LABEL org.opencontainers.image.title="openroad-mcp"
LABEL org.opencontainers.image.description="MCP server for OpenROAD — AI-assisted chip design"
LABEL org.opencontainers.image.source="https://github.com/armaanbawa/openroad-mcp"
LABEL org.opencontainers.image.licenses="BSD-3-Clause"
LABEL org.opencontainers.image.vendor="Precision Innovations"

# Install uv (needed for runtime entrypoint via `uv run`)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

WORKDIR /app

# Copy the pre-built virtual environment and source from builder
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/src /app/src
COPY pyproject.toml uv.lock ./

# Set up the Python and tool paths
ENV PYTHONPATH=/app/src
ENV PATH="/app/.venv/bin:/OpenROAD-flow-scripts/tools/install/OpenROAD/bin:/OpenROAD-flow-scripts/tools/install/yosys/bin:$PATH"
ENV VIRTUAL_ENV=/app/.venv

# MCP server configuration defaults
ENV MCP_SERVER_REQUEST_TIMEOUT=120
ENV MCP_REQUEST_MAX_TOTAL_TIMEOUT=300

# Expose the default MCP server port
EXPOSE 8080

# Health check — verify the MCP module is importable
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "from openroad_mcp import main; print('healthy')" || exit 1

# Default entrypoint: launch the MCP server
ENTRYPOINT ["python", "-m", "openroad_mcp.main"]
CMD []
