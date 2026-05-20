from datetime import date, timedelta

import pytest

from src.common.metrics_policy import (
    MetricsPolicyError,
    load_metrics_schema,
    validate_metrics_schema,
)


def test_bounded_metric_labels_pass():
    validate_metrics_schema(
        [
            {
                "name": "task.events",
                "labels": {
                    "environment": {},
                    "task_state": {},
                    "queue": {"values": ["default", "priority"]},
                },
            }
        ]
    )


def test_unbounded_label_blocks_rollout():
    with pytest.raises(MetricsPolicyError) as exc_info:
        validate_metrics_schema(
            [
                {
                    "name": "task.events",
                    "labels": {
                        "task_id": {"source": "task.id"},
                    },
                }
            ]
        )

    assert "task.events.task_id" in str(exc_info.value)
    assert "unbounded label" in str(exc_info.value)


def test_approved_exception_allows_unbounded_label():
    validate_metrics_schema(
        [
            {
                "name": "worker.heartbeat",
                "labels": {
                    "worker_id": {
                        "exception": {
                            "approved_by": "observability-owner",
                            "reason": "Required for incident isolation",
                            "expires_at": (
                                date.today() + timedelta(days=30)
                            ).isoformat(),
                        }
                    }
                },
            }
        ]
    )


def test_expired_exception_blocks_rollout():
    with pytest.raises(MetricsPolicyError) as exc_info:
        validate_metrics_schema(
            [
                {
                    "name": "worker.heartbeat",
                    "labels": {
                        "worker_id": {
                            "exception": {
                                "approved_by": "observability-owner",
                                "reason": "Legacy dashboard migration",
                                "expires_at": (
                                    date.today() - timedelta(days=1)
                                ).isoformat(),
                            }
                        }
                    },
                }
            ]
        )

    assert "exception expired" in str(exc_info.value)


def test_loads_metrics_from_observability_manifest(tmp_path):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(
        """
name: hello-agent
observability:
  metrics:
    - name: run.duration
      labels:
        result: {}
        environment: {}
""",
        encoding="utf-8",
    )

    assert load_metrics_schema(str(manifest)) == [
        {
            "name": "run.duration",
            "labels": {
                "result": {},
                "environment": {},
            },
        }
    ]
