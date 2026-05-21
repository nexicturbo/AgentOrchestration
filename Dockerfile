FROM python:3.11-slim AS base

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

FROM base AS scheduler

ENV AO_SCHEDULER_HEALTH_STORAGE_DIR=/tmp/ao-scheduler-health
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -m src.orchestrator.scheduler_health

CMD ["python", "-m", "src.orchestrator.scheduler_health", "--watch"]

FROM base AS api

EXPOSE 8000
CMD ["uvicorn", "src.api.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
