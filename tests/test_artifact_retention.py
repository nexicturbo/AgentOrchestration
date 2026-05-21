import pytest

from src.orchestrator.artifact_retention import (
    ArtifactRetentionError,
    ArtifactRetentionPolicy,
)
from src.orchestrator.workflow import StepStatus, WorkflowManager, WorkflowStep


def _completed_workflow():
    manager = WorkflowManager()
    workflow = manager.create_workflow("artifact-cleanup")
    workflow.add_step(WorkflowStep("produce", lambda: {"ok": True}))
    assert manager.execute_workflow(workflow.id)
    return manager, workflow


def test_schedules_valid_retention_policy_after_workflow_completion():
    manager, workflow = _completed_workflow()
    revision = workflow.revision
    policy = ArtifactRetentionPolicy(
        name="reports/customer-export",
        max_age_seconds=86400,
        cleanup_after_seconds=3600,
        batch_size=50,
    )

    schedule = manager.schedule_artifact_cleanup(
        workflow.id,
        policy,
        expected_revision=revision,
    )

    assert schedule.workflow_id == workflow.id
    assert schedule.expected_revision == revision
    assert workflow.status is StepStatus.COMPLETED
    assert workflow.cleanup_schedules == [schedule]
    assert workflow.audit_log[-1]["decision"] == "accepted"
    assert workflow.audit_log[-1]["reason"] == "cleanup_scheduled"
    assert "reports/customer-export" not in str(workflow.audit_log[-1])


def test_rejects_cleanup_before_workflow_reaches_terminal_state():
    manager = WorkflowManager()
    workflow = manager.create_workflow("artifact-cleanup")
    workflow.status = StepStatus.RUNNING
    policy = ArtifactRetentionPolicy(
        name="intermediate-artifacts",
        max_age_seconds=3600,
    )

    with pytest.raises(ArtifactRetentionError) as excinfo:
        manager.schedule_artifact_cleanup(
            workflow.id,
            policy,
            expected_revision=workflow.revision,
        )

    assert excinfo.value.reason == "workflow_not_completed"
    assert workflow.status is StepStatus.RUNNING
    assert workflow.cleanup_schedules == []
    assert workflow.audit_log[-1]["decision"] == "rejected"
    assert workflow.audit_log[-1]["reason"] == "workflow_not_completed"


def test_rejects_stale_cleanup_transition_without_mutating_state():
    manager, workflow = _completed_workflow()
    policy = ArtifactRetentionPolicy(
        name="model-outputs",
        max_age_seconds=7200,
    )

    with pytest.raises(ArtifactRetentionError) as excinfo:
        manager.schedule_artifact_cleanup(
            workflow.id,
            policy,
            expected_revision=workflow.revision - 1,
        )

    assert excinfo.value.reason == "stale_workflow_revision"
    assert workflow.status is StepStatus.COMPLETED
    assert workflow.cleanup_schedules == []
    assert workflow.audit_log[-1]["actual_revision"] == workflow.revision


@pytest.mark.parametrize(
    ("policy", "reason"),
    [
        (
            ArtifactRetentionPolicy("", max_age_seconds=3600),
            "blank_policy_name",
        ),
        (
            ArtifactRetentionPolicy("held", max_age_seconds=3600,
                                    legal_hold=True),
            "legal_hold_blocks_cleanup",
        ),
        (
            ArtifactRetentionPolicy("bad-age", max_age_seconds=0),
            "non_positive_max_age",
        ),
        (
            ArtifactRetentionPolicy(
                "late-cleanup",
                max_age_seconds=10,
                cleanup_after_seconds=11,
            ),
            "cleanup_after_exceeds_max_age",
        ),
        (
            ArtifactRetentionPolicy(
                "huge-batch",
                max_age_seconds=3600,
                batch_size=1001,
            ),
            "invalid_batch_size",
        ),
    ],
)
def test_rejects_invalid_policy_without_storing_private_policy_values(
    policy,
    reason,
):
    manager, workflow = _completed_workflow()

    with pytest.raises(ArtifactRetentionError) as excinfo:
        manager.schedule_artifact_cleanup(
            workflow.id,
            policy,
            expected_revision=workflow.revision,
        )

    assert excinfo.value.reason == reason
    assert workflow.cleanup_schedules == []
    assert workflow.audit_log[-1]["reason"] == reason
    if policy.name:
        assert policy.name not in str(workflow.audit_log[-1])
