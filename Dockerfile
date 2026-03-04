# =============================================================================
# Epguides API Docker Image
# =============================================================================
# Multi-stage build for optimal size and security

# ---------------------------------------------------------------------------
# Stage 1: Builder - Install dependencies with build tools
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build dependencies for uvloop and httptools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install production-only Python dependencies (excludes test/lint tools)
COPY requirements-prod.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-prod.txt

# ---------------------------------------------------------------------------
# Stage 2: Runtime - Minimal production image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# OCI image metadata
LABEL org.opencontainers.image.title="Epguides API" \
      org.opencontainers.image.description="REST API for TV show metadata, episodes, and air dates" \
      org.opencontainers.image.source="https://github.com/frecar/epguides-api" \
      org.opencontainers.image.licenses="MIT"

# Build argument for version
ARG APP_VERSION=dev

# Environment configuration
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    APP_VERSION=${APP_VERSION} \
    PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -s /sbin/nologin appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=appuser:appgroup . .

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 3000

# Health check — validates response status and body content
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "healthcheck.py"]

# Default command (overridden by docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
