# =============================================================================
# Epguides API Docker Image
# =============================================================================
# Multi-stage build with uv for fast, reproducible installs.

# ---------------------------------------------------------------------------
# Stage 1: Builder — uv installs deps into a virtualenv
# ---------------------------------------------------------------------------
# Base image pinned by tag + digest: the digest is the immutable, reproducible
# provenance (so the build is byte-stable and a mutated upstream tag can't be
# adopted silently); the tag stays for readability + so the docker dependabot
# ecosystem can track and bump it. The digest is the MULTI-ARCH INDEX digest
# (resolved with `docker buildx imagetools inspect python:3.14.6-slim`), so each
# build host still resolves its own platform. Enforced by
# scripts/check_base_image_digest_pin_drift.py.
FROM python:3.14.6-slim@sha256:63a4c7f612a00f92042cbdcc7cdc6a306f38485af0a200b9c89de7d9b1607d15 AS builder

# uv is pinned to an exact version (not `latest`). It is deliberately NOT
# digest-pinned: the uv version is the single source of record, kept in lockstep
# across the fleet by an external sync that rewrites only the version on a
# reviewed bump. A digest here would NOT be updated by that sync, so the next
# version bump would leave the tag and digest disagreeing (the build would
# silently keep the old digest's bytes under a new version label). The version
# tag is the reviewed-bump control; the digest-pin guard forbids a digest on
# this line. The astral-sh/uv image only contains the static uv binary; we COPY
# it into our python base image rather than using it as the base (which lacks
# python).
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

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
FROM python:3.14.6-slim@sha256:63a4c7f612a00f92042cbdcc7cdc6a306f38485af0a200b9c89de7d9b1607d15 AS runtime

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
