# =============================================================================
# Epguides API Docker Image
# =============================================================================
# Multi-stage build with uv for fast, reproducible installs.

# ---------------------------------------------------------------------------
# Stage 1: Builder — uv installs deps into a virtualenv
# ---------------------------------------------------------------------------
FROM python:3.14.5-slim AS builder

# Pin uv to an exact version — `latest` would silently move on every build.
# The astral-sh/uv image only contains the static uv binary; we COPY it
# into our python base image rather than using it as the base (which lacks
# python).
COPY --from=ghcr.io/astral-sh/uv:0.11.17 /uv /usr/local/bin/uv

WORKDIR /build

# uvloop and httptools (transitive of uvicorn[standard]) ship pre-built
# wheels for cpython-3.14 on Linux x86_64, so the build toolchain isn't
# strictly required. Keep gcc + libc-dev around in case a future
# transitive needs to compile from source on this base image.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy lock + project metadata only (better cache hit on rebuilds when
# source changes but deps don't).
COPY pyproject.toml uv.lock ./

# `--frozen` enforces the lockfile (errors if pyproject.toml deps drift).
# `--no-dev` excludes the dev dependency group (pytest, ruff, mypy, etc.).
# `--no-install-project` skips installing this project itself — only the
# external deps. The app code is mounted/copied separately in stage 2.
ENV UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 2: Runtime — minimal production image
# ---------------------------------------------------------------------------
FROM python:3.14.5-slim AS runtime

LABEL org.opencontainers.image.title="Epguides API" \
      org.opencontainers.image.description="REST API for TV show metadata, episodes, and air dates" \
      org.opencontainers.image.source="https://github.com/frecar/epguides-api" \
      org.opencontainers.image.licenses="MIT"

ARG APP_VERSION=dev

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    APP_VERSION=${APP_VERSION} \
    PATH="/build/.venv/bin:$PATH"

# Non-root user
RUN groupadd -r -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -s /sbin/nologin appuser

WORKDIR /app

# Copy the uv-managed virtualenv from the builder stage. uv puts it at
# /build/.venv relative to the project (the WORKDIR in stage 1).
COPY --from=builder /build/.venv /build/.venv

COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
