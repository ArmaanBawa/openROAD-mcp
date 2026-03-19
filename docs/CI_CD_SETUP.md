# CI/CD Setup Guide — OpenROAD MCP

## Overview

The project uses three GitHub Actions workflows:

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| **CI** | `ci.yaml` | push/PR to main, nightly | Lint, test, coverage |
| **Docker Publish** | `docker-publish.yml` | push to main, tags `v*.*.*` | Build & push to GHCR |
| **Cross-Platform** | `cross-platform.yml` | push/PR to main, weekly | Ubuntu/macOS/Windows validation |
| **Release** | `release.yml` | tags `v*.*.*` | PyPI publish + GitHub Release |

## Setting Up GHCR Publishing

### 1. Repository Permissions

The `docker-publish.yml` workflow uses `GITHUB_TOKEN` with `packages: write` permission. No additional secrets are needed for GHCR — it works automatically for public repos.

For private repos, ensure the repository's Actions settings allow:
- **Settings → Actions → General → Workflow permissions** → "Read and write permissions"

### 2. First-Time Package Visibility

After the first image push, set package visibility:
1. Go to `https://github.com/users/<owner>/packages/container/openroad-mcp`
2. Click **Package settings**
3. Set visibility to **Public**

### 3. Testing Locally

```bash
# Simulate the Docker build locally
docker build -t openroad-mcp-local .

# Verify the image works
docker run --rm openroad-mcp-local python -c "from openroad_mcp import main; print('ok')"
```

## Adding a New Platform to CI

Edit `.github/workflows/cross-platform.yml`:

```yaml
# Add to the matrix in the ubuntu job:
strategy:
  matrix:
    os: [ubuntu-22.04, ubuntu-24.04, ubuntu-24.10]  # ← add new version
```

For a completely new OS, add a new job block following the existing patterns.

## CI Secrets Reference

| Secret | Used by | Purpose |
|--------|---------|---------|
| `GITHUB_TOKEN` | `docker-publish.yml` | Push images to GHCR (automatic) |
| `CODECOV_TOKEN` | `ci.yaml` | Upload coverage reports |

## Workflow Dependency Graph

```
push to main
  ├── ci.yaml (lint → test → coverage)
  ├── docker-publish.yml (build → security-scan + smoke-test)
  └── cross-platform.yml (ubuntu + macos + windows-wsl2 → summary)

tag v*.*.*
  ├── release.yml (test → build → pypi + github-release)
  └── docker-publish.yml (build → security-scan + smoke-test)
```
