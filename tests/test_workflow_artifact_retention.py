import logging

from src.common.metrics import metrics
from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
)

FUTURE_TS = 4102444800


def test_stale_artifact_cleanup_rejected_before_lifecycle_changes(caplog):
    manager = WorkflowManager()
    workflow = manager.create_workflow("cleanup")
    calls = []

    def handler():
        calls.append("ran")

    step = WorkflowStep(
        "write-artifact",
        handler,
        artifact_retention_policy={
            "artifact_id": "private-report-id",
            "cleanup_after": 1,
        },
    )
    workflow.add_step(step)

    caplog.set_level(logging.WARNING, logger="src.orchestrator.workflow")
    metric_before = metrics.snapshot()["counters"].get(
        "workflow.artifact_retention.rejected",
        0,
    )
    executed = manager.execute_workflow(workflow.id)
    metric_after = metrics.snapshot()["counters"].get(
        "workflow.artifact_retention.rejected",
        0,
    )

    assert executed is False
    assert calls == []
    assert workflow.status == StepStatus.PENDING
    assert step.status == StepStatus.PENDING
    assert step.error == "Invalid artifact retention policy"
    assert workflow.cleanup_schedule == []
    assert workflow.audit_records == [{
        "decision": "artifact_retention_rejected",
        "reason": "stale_cleanup_schedule",
        "workflow_id": workflow.id,
        "step_id": step.id,
        "step_name": "write-artifact",
        "policy_count": 1,
    }]
    assert metric_after == metric_before + 1
    assert "private-report-id" not in caplog.text


def test_duplicate_artifact_cleanup_policy_is_rejected():
    manager = WorkflowManager()
    workflow = manager.create_workflow("cleanup")
    calls = []

    def handler():
        calls.append("ran")

    first = WorkflowStep(
        "first",
        handler,
        artifact_retention_policy={
            "artifact_id": "artifact-1",
            "cleanup_after": FUTURE_TS,
        },
    )
    second = WorkflowStep(
        "second",
        handler,
        artifact_retention_policy={
            "artifact_id": "artifact-1",
            "cleanup_after": FUTURE_TS + 60,
        },
    )
    workflow.add_step(first).add_step(second)

    assert manager.execute_workflow(workflow.id) is False
    assert calls == []
    assert workflow.status == StepStatus.PENDING
    assert first.status == StepStatus.PENDING
    assert second.status == StepStatus.PENDING
    assert workflow.cleanup_schedule == []
    assert workflow.audit_records[0]["reason"] == (
        "duplicate_artifact_policy"
    )


def test_retention_window_after_cleanup_deadline_is_rejected():
    manager = WorkflowManager()
    workflow = manager.create_workflow("cleanup")
    calls = []

    def handler():
        calls.append("ran")

    step = WorkflowStep(
        "archive",
        handler,
        artifact_retention_policy={
            "artifact_id": "artifact-1",
            "retain_until": FUTURE_TS + 60,
            "cleanup_after": FUTURE_TS,
        },
    )
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id) is False
    assert calls == []
    assert workflow.cleanup_schedule == []
    assert workflow.audit_records[0]["reason"] == (
        "retention_exceeds_cleanup_window"
    )


def test_valid_artifact_cleanup_schedule_binds_before_execution():
    manager = WorkflowManager()
    workflow = manager.create_workflow("cleanup")
    calls = []

    def handler():
        calls.append("ran")
        return "ok"

    step = WorkflowStep(
        "archive",
        handler,
        artifact_retention_policy={
            "artifact_id": "artifact-1",
            "retain_until": FUTURE_TS - 60,
            "cleanup_after": FUTURE_TS,
        },
    )
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id) is True
    assert calls == ["ran"]
    assert workflow.status == StepStatus.COMPLETED
    assert step.status == StepStatus.COMPLETED
    assert step.result == "ok"
    assert workflow.audit_records == []
    assert workflow.cleanup_schedule == [{
        "workflow_id": workflow.id,
        "step_id": step.id,
        "step_name": "archive",
        "artifact_id": "artifact-1",
        "cleanup_after": FUTURE_TS,
    }]


def test_workflow_without_artifact_policy_remains_compatible():
    manager = WorkflowManager()
    workflow = manager.create_workflow("simple")
    calls = []

    def handler():
        calls.append("ran")
        return "done"

    step = WorkflowStep("plain", handler)
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id) is True
    assert calls == ["ran"]
    assert workflow.cleanup_schedule == []
    assert step.result == "done"
