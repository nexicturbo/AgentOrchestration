# Sidecar Runtime Filesystems

Helper and observability sidecars run with read-only root filesystems. This
keeps runtime drift auditable and makes writable state explicit.

Current sidecars:

| Service | Purpose | Writable paths |
| --- | --- | --- |
| `metrics-sidecar` | Emits local metrics heartbeat data | `/tmp` |
| `log-forwarder-sidecar` | Emits local log-forwarder heartbeat data | `/tmp` |

Required writable paths are mounted as tmpfs entries in
`infra/docker-compose.yml`. New sidecar services must set `read_only: true`,
declare at least one tmpfs writable path, and document the same paths here.
