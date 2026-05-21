# Deployment Health

The scheduler image exposes a Docker `HEALTHCHECK` that runs:

```bash
python -m src.orchestrator.scheduler_health
```

The probe verifies that the configured scheduler storage directory is writable. If
`AO_SCHEDULER_HEALTH_QUEUE_READY_FILE` is set, it also verifies that the queue
dependency has written a ready marker containing `ready`, `healthy`, `1`, or
`true`.

The startup grace period is set in both the image metadata and compose manifest
so queue and storage dependencies can warm up before orchestrators mark the
scheduler unhealthy. The compose deployment consumes the image health status with
`depends_on: condition: service_healthy`, keeping API traffic from starting until
the scheduler health gate passes.
