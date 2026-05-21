from pathlib import Path

import pytest
import yaml

from src.orchestrator.scheduler_health import (
    SchedulerHealthConfig,
    SchedulerHealthError,
    check_scheduler_health,
    main,
)


def test_scheduler_health_passes_with_writable_storage(tmp_path):
    result = check_scheduler_health(
        SchedulerHealthConfig(storage_dir=tmp_path / "state")
    )

    assert result["status"] == "healthy"
    assert result["queue"] == "not-configured"


def test_scheduler_health_fails_when_storage_path_is_not_directory(tmp_path):
    storage_file = tmp_path / "state"
    storage_file.write_text("not a directory", encoding="utf-8")

    with pytest.raises(SchedulerHealthError, match="not a directory"):
        check_scheduler_health(
            SchedulerHealthConfig(storage_dir=storage_file)
        )


def test_scheduler_health_reflects_queue_dependency_failure(tmp_path):
    missing_queue_marker = tmp_path / "queue.ready"

    with pytest.raises(
        SchedulerHealthError,
        match="queue dependency is not ready",
    ):
        check_scheduler_health(
            SchedulerHealthConfig(
                storage_dir=tmp_path / "state",
                queue_ready_file=missing_queue_marker,
            )
        )


def test_scheduler_health_accepts_ready_queue_marker(tmp_path):
    queue_marker = tmp_path / "queue.ready"
    queue_marker.write_text("ready\n", encoding="utf-8")

    result = check_scheduler_health(
        SchedulerHealthConfig(
            storage_dir=tmp_path / "state",
            queue_ready_file=queue_marker,
        )
    )

    assert result["status"] == "healthy"
    assert result["queue"] == str(queue_marker)


def test_scheduler_health_cli_returns_unhealthy_exit_for_dependency_failure(
    tmp_path,
    monkeypatch,
    capsys,
):
    storage_file = tmp_path / "state"
    storage_file.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("AO_SCHEDULER_HEALTH_STORAGE_DIR", str(storage_file))

    assert main([]) == 1
    assert "unhealthy" in capsys.readouterr().err


def test_scheduler_image_defines_startup_grace_healthcheck():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert "AS scheduler" in dockerfile
    assert (
        "HEALTHCHECK --interval=30s --timeout=5s "
        "--start-period=20s --retries=3"
    ) in dockerfile
    assert "python -m src.orchestrator.scheduler_health" in dockerfile


def test_compose_consumes_scheduler_health_status():
    compose = yaml.safe_load(
        Path("infra/docker-compose.yml").read_text(encoding="utf-8")
    )

    scheduler = compose["services"]["scheduler"]
    api_depends_on = compose["services"]["api"]["depends_on"]
    assert scheduler["healthcheck"]["test"] == [
        "CMD",
        "python",
        "-m",
        "src.orchestrator.scheduler_health",
    ]
    assert api_depends_on["scheduler"]["condition"] == "service_healthy"
