import pytest

from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowMetadataError,
    WorkflowStep,
)


def test_rejects_reserved_workflow_metadata_before_registration():
    manager = WorkflowManager()

    with pytest.raises(WorkflowMetadataError):
        manager.create_workflow(
            "deploy",
            metadata={"owner": "user", "status": "running"},
        )

    assert manager.list_workflows() == []


def test_rejects_nested_reserved_step_metadata_before_binding():
    workflow = WorkflowManager().create_workflow("deploy")

    with pytest.raises(WorkflowMetadataError):
        WorkflowStep(
            "publish",
            lambda: "ok",
            metadata={"ui": {"routingKey": "internal-worker"}},
        )

    assert workflow.status == StepStatus.PENDING
    assert workflow.steps == []


def test_execution_revalidates_metadata_and_preserves_lifecycle_state():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy", metadata={"owner": "user"})
    called = False

    def handler():
        nonlocal called
        called = True

    workflow.add_step(
        WorkflowStep("publish", handler, metadata={"label": "v1"}),
    )
    workflow.metadata["task-id"] = "smuggled-control-field"

    assert not manager.execute_workflow(workflow.id)
    assert workflow.status == StepStatus.PENDING
    assert workflow.steps[0].status == StepStatus.PENDING
    assert not called


def test_rejection_audit_is_sanitized_without_metadata_values():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy", metadata={"owner": "user"})
    workflow.metadata["result"] = {"token": "secret-value"}

    assert not manager.execute_workflow(workflow.id)

    audit = manager.audit_records()
    assert audit == [{
        "event": "workflow_metadata_rejected",
        "workflow_id": workflow.id,
        "workflow_status": "pending",
        "key_path": "workflow.metadata.result",
        "reason": "reserved_metadata_key",
    }]
    assert "secret-value" not in repr(audit)


def test_valid_metadata_executes_workflow():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy", metadata={"owner": "user"})
    workflow.add_step(
        WorkflowStep("publish", lambda: "ok", metadata={"label": "v1"}),
    )

    assert manager.execute_workflow(workflow.id)
    assert workflow.status == StepStatus.COMPLETED
    assert workflow.steps[0].status == StepStatus.COMPLETED
