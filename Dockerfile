# syntax=docker/dockerfile:1.7

FROM python:3.11-slim AS builder

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir uv \
    && uv build

FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=builder /app/dist/*.whl /tmp/wheels/

RUN python -m pip install --no-cache-dir /tmp/wheels/*.whl \
    && rm -rf /tmp/wheels \
        /root/.cache \
        /var/cache/apt \
        /var/lib/apt/lists \
        /tmp/*

CMD ["ao", "--help"]
