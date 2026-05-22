import logging

from src.common.metrics import metrics
from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
)


def test_sensitive_input_rejected_before_lifecycle_changes(caplog):
    manager = WorkflowManager()
    workflow = manager.create_workflow("safe wiring")
    calls = []

    def handler(api_token):
        calls.append(api_token)

    step = WorkflowStep(
        "call-api",
        handler,
        inputs={"api_token": "runtime-secret-value"},
    )
    workflow.add_step(step)

    caplog.set_level(logging.WARNING, logger="src.orchestrator.workflow")
    metric_before = metrics.snapshot()["counters"].get(
        "workflow.sensitive_input.rejected",
        0,
    )
    executed = manager.execute_workflow(workflow.id)
    metric_after = metrics.snapshot()["counters"].get(
        "workflow.sensitive_input.rejected",
        0,
    )

    assert executed is False
    assert calls == []
    assert workflow.status == StepStatus.PENDING
    assert step.status == StepStatus.PENDING
    assert step.error == "Sensitive input declaration required"
    assert workflow.audit_records == [{
        "decision": "sensitive_input_rejected",
        "reason": "missing_sensitive_declaration",
        "workflow_id": workflow.id,
        "step_id": step.id,
        "step_name": "call-api",
        "input_count": 1,
    }]
    assert metric_after == metric_before + 1
    assert "runtime-secret-value" not in caplog.text
    assert "api_token" not in caplog.text


def test_sensitive_input_must_be_declared_sensitive():
    manager = WorkflowManager()
    workflow = manager.create_workflow("safe wiring")
    calls = []

    def handler(password):
        calls.append(password)

    step = WorkflowStep(
        "login",
        handler,
        inputs={"password": "runtime-secret-value"},
        input_schema={"password": {"sensitive": False}},
    )
    workflow.add_step(step)

    executed = manager.execute_workflow(workflow.id)

    assert executed is False
    assert calls == []
    assert workflow.status == StepStatus.PENDING
    assert step.status == StepStatus.PENDING
    assert workflow.audit_records[0]["decision"] == (
        "sensitive_input_rejected"
    )


def test_explicit_sensitive_input_declaration_allows_execution():
    manager = WorkflowManager()
    workflow = manager.create_workflow("safe wiring")
    calls = []

    def handler(api_token, region):
        calls.append((api_token, region))
        return "ok"

    step = WorkflowStep(
        "call-api",
        handler,
        inputs={
            "api_token": "runtime-secret-value",
            "region": "us",
        },
        input_schema={"api_token": {"sensitive": True}},
    )
    workflow.add_step(step)

    executed = manager.execute_workflow(workflow.id)

    assert executed is True
    assert calls == [("runtime-secret-value", "us")]
    assert workflow.status == StepStatus.COMPLETED
    assert step.status == StepStatus.COMPLETED
    assert step.result == "ok"
    assert workflow.audit_records == []


def test_non_sensitive_inputs_do_not_require_schema_declarations():
    manager = WorkflowManager()
    workflow = manager.create_workflow("normal wiring")
    calls = []

    def handler(retries):
        calls.append(retries)
        return retries

    step = WorkflowStep(
        "retry",
        handler,
        inputs={"retries": 2},
    )
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id) is True
    assert calls == [2]
    assert step.result == 2


def test_no_input_workflow_remains_compatible():
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
    assert step.result == "done"
