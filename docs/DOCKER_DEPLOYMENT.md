# Docker Deployment Guide — OpenROAD MCP

## Quick Start

Pull and run the latest image:

```bash
docker run --rm -it ghcr.io/armaanbawa/openroad-mcp:latest
```

Or use a specific version:

```bash
docker run --rm -it ghcr.io/armaanbawa/openroad-mcp:0.2.0
```

## Docker Compose

### Production

```bash
docker compose up openroad-mcp
```

The MCP server will be available on port `8080`. The workspace volume at `/workspace` persists design files between restarts.

### Development (hot-reload)

```bash
docker compose up openroad-mcp-dev
```

Source code is mounted read-only — edits on the host are reflected immediately.

### Running Tests

```bash
# Core tests
docker compose run --rm --profile test test

# Integration tests (requires ORFS)
docker compose run --rm --profile test test-integration

# Performance + memory profiling
docker compose run --rm --profile test test-performance
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_SERVER_REQUEST_TIMEOUT` | `120` | Per-request timeout (seconds) |
| `MCP_REQUEST_MAX_TOTAL_TIMEOUT` | `300` | Total request timeout (seconds) |
| `MEMORY_PROFILE` | unset | Set to `1` to enable memory profiling |
| `ORFS_PATH` | `/OpenROAD-flow-scripts` | Path to ORFS inside the container |

## Building Locally

```bash
# Production image
docker build -t openroad-mcp .

# Test image
docker build -f Dockerfile.test -t openroad-mcp-test .
```

## Image Architecture

The production `Dockerfile` uses a two-stage build:

1. **Builder** — installs `uv`, syncs Python dependencies (no dev extras)
2. **Runtime** — copies only the virtual environment and source from the builder

This keeps the runtime image lean by excluding build tools and dev dependencies.

## Health Check

The container includes a built-in health check:

```bash
docker inspect --format='{{.State.Health.Status}}' openroad-mcp
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `openroad: not found` | The base image `openroad/orfs:latest` must include OpenROAD. Verify with `docker run --rm openroad/orfs:latest openroad -version`. |
| Container exits immediately | Check logs: `docker logs openroad-mcp`. Ensure no port conflict on `8080`. |
| Out of memory | Increase Docker memory limit. The compose file reserves 2 GB and limits to 8 GB. |
| Permission denied | The runtime image runs as root by default. Use `--user` flag or modify the Dockerfile to add a non-root user if needed. |
| Slow build | Enable BuildKit: `DOCKER_BUILDKIT=1 docker build .` — this enables parallel layer building and caching. |
