# Metrics Label Cardinality

The deploy command validates metric labels before rollout. Any metric added to
an agent manifest must declare bounded label values or use one of the approved
shared labels below. Unbounded labels such as task IDs, user IDs, worker IDs,
hostnames, request IDs, trace IDs, and raw error messages are blocked unless the
observability owner approves a temporary exception.

## Manifest Format

Metrics can be declared at `metrics` or `observability.metrics`:

```yaml
observability:
  metrics:
    - name: task.events
      labels:
        environment: {}
        task_state: {}
        queue:
          values:
            - default
            - priority
```

Labels with a `values` list must stay within the default cardinality budget of
50 unique values. Duplicated values and empty lists fail validation.

## Allowed Shared Labels

The following labels already have bounded values and can be used without
declaring a `values` list in each manifest.

| Label | Allowed values |
| --- | --- |
| `agent_type` | `batch`, `interactive`, `service`, `worker` |
| `environment` | `dev`, `staging`, `prod` |
| `event` | `created`, `started`, `completed`, `failed`, `cancelled` |
| `priority` | `low`, `normal`, `high`, `critical` |
| `region` | `us-east`, `us-west`, `eu-central`, `ap-south` |
| `result` | `success`, `error`, `timeout`, `cancelled` |
| `run_state` | `queued`, `running`, `completed`, `failed`, `cancelled` |
| `task_state` | `queued`, `running`, `completed`, `failed`, `cancelled` |
| `worker_state` | `starting`, `ready`, `busy`, `draining`, `offline` |

## Exceptions

Exceptions must be explicit, owner-approved, and preferably temporary:

```yaml
observability:
  metrics:
    - name: worker.heartbeat
      labels:
        worker_id:
          exception:
            approved_by: observability-owner
            reason: Required during worker drain incident response
            expires_at: 2026-06-30
```

An exception without `approved_by` and `reason` blocks deployment. An expired
`expires_at` also blocks deployment.

## Deploy Gate

`ao deploy <manifest>` runs the cardinality check before rollout. A failed
check exits with code 2 and prints every offending metric label so the manifest
can be fixed before production deployment.
