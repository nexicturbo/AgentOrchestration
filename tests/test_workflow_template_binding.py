import logging

from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
)


def test_unresolved_template_rejected_before_lifecycle_changes(caplog):
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy")
    calls = []

    def handler(target):
        calls.append(target)

    step = WorkflowStep(
        "render",
        handler,
        parameters={"target": "{{ missing_target }}"},
    )
    workflow.add_step(step)

    caplog.set_level(logging.WARNING, logger="src.orchestrator.workflow")
    executed = manager.execute_workflow(
        workflow.id,
        runtime_parameters={"secret": "private-runtime-value"},
    )

    assert executed is False
    assert calls == []
    assert workflow.status == StepStatus.PENDING
    assert step.status == StepStatus.PENDING
    assert step.error == "Unresolved template variable"
    assert workflow.audit_records == [{
        "decision": "template_binding_rejected",
        "reason": "unresolved_template",
        "workflow_id": workflow.id,
        "step_id": step.id,
        "step_name": "render",
    }]
    assert "private-runtime-value" not in caplog.text
    assert "missing_target" not in caplog.text


def test_runtime_value_that_renders_template_is_rejected():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy")
    calls = []

    def handler(target):
        calls.append(target)

    step = WorkflowStep(
        "render",
        handler,
        parameters={"target": "${target}"},
    )
    workflow.add_step(step)

    executed = manager.execute_workflow(
        workflow.id,
        runtime_parameters={"target": "{{ second_pass }}"},
    )

    assert executed is False
    assert calls == []
    assert workflow.status == StepStatus.PENDING
    assert step.status == StepStatus.PENDING
    assert step.bound_parameters == {}
    assert workflow.audit_records[0]["decision"] == (
        "template_binding_rejected"
    )


def test_template_binding_executes_handler_after_all_values_resolve():
    manager = WorkflowManager()
    workflow = manager.create_workflow("deploy")
    calls = []

    def handler(target, labels):
        calls.append((target, labels))
        return "ok"

    step = WorkflowStep(
        "render",
        handler,
        parameters={
            "target": "agent-${agent_id}",
            "labels": ["{{ environment }}", "static"],
        },
    )
    workflow.add_step(step)

    executed = manager.execute_workflow(
        workflow.id,
        runtime_parameters={
            "agent_id": "alpha",
            "environment": "prod",
        },
    )

    assert executed is True
    assert calls == [("agent-alpha", ["prod", "static"])]
    assert workflow.status == StepStatus.COMPLETED
    assert step.status == StepStatus.COMPLETED
    assert step.result == "ok"
    assert step.bound_parameters == {
        "target": "agent-alpha",
        "labels": ["prod", "static"],
    }
    assert workflow.audit_records == []


def test_no_parameter_workflow_remains_compatible():
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
