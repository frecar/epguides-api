
FROM python:3.14.10-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

WORKDIR /build

ARG OS_SECURITY_EPOCH
RUN : "${OS_SECURITY_EPOCH:?OS_SECURITY_EPOCH build-arg is required}" \
    && apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libc-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./

ENV UV_LINK_MODE=copy
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14.10-slim@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS runtime

LABEL org.opencontainers.image.title="Epguides API" \
      org.opencontainers.image.description="REST API for TV show metadata, episodes, and air dates" \
      org.opencontainers.image.source="https://github.com/frecar/epguides-api" \
      org.opencontainers.image.licenses="MIT"

ARG APP_VERSION=dev
ARG GIT_SHA=

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA} \
    PATH="/build/.venv/bin:$PATH"

ARG OS_SECURITY_EPOCH
RUN : "${OS_SECURITY_EPOCH:?OS_SECURITY_EPOCH build-arg is required}" \
    && apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN python -m pip uninstall --yes pip

RUN groupadd -r -g 1000 appgroup && \
    useradd -r -u 1000 -g appgroup -s /sbin/nologin appuser

WORKDIR /app

COPY --from=builder /build/.venv /build/.venv

COPY --chown=appuser:appgroup . .

USER appuser

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD ["python", "healthcheck.py"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "3000"]
