"""Scheduler container health checks."""

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional
from uuid import uuid4


class SchedulerHealthError(RuntimeError):
    """Raised when a scheduler dependency health check fails."""


@dataclass(frozen=True)
class SchedulerHealthConfig:
    storage_dir: Path
    queue_ready_file: Optional[Path] = None

    @classmethod
    def from_env(cls) -> "SchedulerHealthConfig":
        storage_dir = Path(
            os.getenv(
                "AO_SCHEDULER_HEALTH_STORAGE_DIR",
                "/tmp/ao-scheduler-health",
            )
        )
        queue_ready = os.getenv("AO_SCHEDULER_HEALTH_QUEUE_READY_FILE")
        return cls(
            storage_dir=storage_dir,
            queue_ready_file=Path(queue_ready) if queue_ready else None,
        )


def check_scheduler_health(
    config: Optional[SchedulerHealthConfig] = None,
) -> Dict[str, str]:
    """Verify scheduler storage and optional queue readiness dependencies."""
    config = config or SchedulerHealthConfig.from_env()
    _check_storage(config.storage_dir)
    _check_queue_ready(config.queue_ready_file)
    return {
        "status": "healthy",
        "storage": str(config.storage_dir),
        "queue": (
            str(config.queue_ready_file)
            if config.queue_ready_file
            else "not-configured"
        ),
    }


def _check_storage(storage_dir: Path) -> None:
    if storage_dir.exists() and not storage_dir.is_dir():
        raise SchedulerHealthError(
            f"storage dependency is not a directory: {storage_dir}"
        )

    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SchedulerHealthError(
            f"storage dependency is not writable: {storage_dir}"
        ) from exc

    probe = storage_dir / f".scheduler-health-{uuid4().hex}"
    try:
        probe.write_text("ok", encoding="utf-8")
        if probe.read_text(encoding="utf-8") != "ok":
            raise SchedulerHealthError(
                f"storage dependency failed readback: {storage_dir}"
            )
    except OSError as exc:
        raise SchedulerHealthError(
            f"storage dependency failed write/read probe: {storage_dir}"
        ) from exc
    finally:
        try:
            probe.unlink()
        except FileNotFoundError:
            pass


def _check_queue_ready(queue_ready_file: Optional[Path]) -> None:
    if queue_ready_file is None:
        return
    try:
        value = queue_ready_file.read_text(encoding="utf-8").strip().lower()
    except OSError as exc:
        raise SchedulerHealthError(
            f"queue dependency is not ready: {queue_ready_file}"
        ) from exc
    if value not in {"ready", "healthy", "1", "true"}:
        raise SchedulerHealthError(
            f"queue dependency reported unhealthy: {queue_ready_file}"
        )


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check scheduler container dependencies"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="keep the scheduler container alive and recheck health",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=30.0,
        help="watch-mode health interval in seconds",
    )
    args = parser.parse_args(argv)

    if args.watch:
        while True:
            check_scheduler_health()
            time.sleep(args.interval)

    try:
        result = check_scheduler_health()
    except SchedulerHealthError as exc:
        print(
            json.dumps({"status": "unhealthy", "reason": str(exc)}),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
