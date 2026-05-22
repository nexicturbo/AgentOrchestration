import pytest

from src.orchestrator.workflow import (
    StepStatus,
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)


def test_case_duplicate_step_rejected_without_mutating_running_workflow():
    workflow = Workflow("deploy")
    original = WorkflowStep("Build", lambda: "old")
    workflow.add_step(original)
    workflow.status = StepStatus.RUNNING

    with pytest.raises(WorkflowValidationError, match="duplicate"):
        workflow.add_step(WorkflowStep(" build ", lambda: "new"))

    assert workflow.status is StepStatus.RUNNING
    assert workflow.steps == [original]
    assert workflow.get_step(original.id) is original
    assert workflow.audit_events == [
        {
            "event": "workflow_step_rejected",
            "reason": "duplicate_step_identifier",
            "workflow_id": workflow.id,
            "workflow_status": "running",
            "step_identifier": "build",
        }
    ]


def test_dependencies_are_normalized_before_binding():
    workflow = Workflow("deploy")
    build = WorkflowStep("Build", lambda: "old")
    publish = WorkflowStep("Publish", lambda: "new", dependencies=[" build "])

    workflow.add_step(build)
    workflow.add_step(publish)

    assert publish.normalized_name == "publish"
    assert publish.normalized_dependencies == ["build"]


def test_duplicate_dependency_identifiers_are_rejected_before_mutation():
    workflow = Workflow("deploy")
    build = WorkflowStep("Build", lambda: "old")
    publish = WorkflowStep(
        "Publish",
        lambda: "new",
        dependencies=["Build", " build "],
    )

    workflow.add_step(build)

    with pytest.raises(WorkflowValidationError, match="duplicate dependency"):
        workflow.add_step(publish)

    assert workflow.steps == [build]
    assert (
        workflow.audit_events[-1]["reason"]
        == "duplicate_dependency_identifier"
    )
    assert workflow.audit_events[-1]["dependency_identifier"] == "build"
