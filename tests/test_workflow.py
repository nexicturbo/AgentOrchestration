from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
)


def test_workflow_runs_step_when_condition_is_true():
    manager = WorkflowManager()
    workflow = manager.create_workflow("safe")
    calls = []
    step = WorkflowStep(
        "guarded",
        lambda: calls.append("ran") or "ok",
        condition=lambda workflow, step: workflow.status == StepStatus.RUNNING,
    )
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id)

    assert calls == ["ran"]
    assert step.status == StepStatus.COMPLETED
    assert step.result == "ok"
    assert workflow.status == StepStatus.COMPLETED
    assert workflow.audit_log == []


def test_workflow_skips_false_condition_before_lifecycle_transition():
    manager = WorkflowManager()
    workflow = manager.create_workflow("skip")
    calls = []
    step = WorkflowStep(
        "guarded",
        lambda: calls.append("ran"),
        condition=lambda workflow, step: False,
    )
    workflow.add_step(step)

    assert manager.execute_workflow(workflow.id)

    assert calls == []
    assert step.status == StepStatus.SKIPPED
    assert step.result is None
    assert workflow.status == StepStatus.COMPLETED
    assert workflow.audit_log == [{
        "step_id": step.id,
        "step_name": "guarded",
        "decision": "skipped",
        "reason": "condition_false",
    }]


def test_workflow_rejects_condition_status_side_effects():
    manager = WorkflowManager()
    workflow = manager.create_workflow("side-effect")
    calls = []

    def condition(workflow, step):
        step.status = StepStatus.COMPLETED
        workflow.status = StepStatus.COMPLETED
        return True

    step = WorkflowStep(
        "guarded",
        lambda: calls.append("ran"),
        condition=condition,
    )
    workflow.add_step(step)

    assert not manager.execute_workflow(workflow.id)

    assert calls == []
    assert step.status == StepStatus.FAILED
    assert step.result is None
    assert step.error == (
        "Workflow condition attempted lifecycle side effects"
    )
    assert workflow.status == StepStatus.FAILED
    assert workflow.audit_log == [{
        "step_id": step.id,
        "step_name": "guarded",
        "decision": "rejected",
        "reason": "condition_side_effect",
    }]


def test_workflow_rejects_condition_graph_side_effects():
    manager = WorkflowManager()
    workflow = manager.create_workflow("graph-side-effect")
    calls = []
    injected = WorkflowStep("injected", lambda: calls.append("injected"))

    def condition(workflow, step):
        workflow.add_step(injected)
        return True

    step = WorkflowStep(
        "guarded",
        lambda: calls.append("ran"),
        condition=condition,
    )
    workflow.add_step(step)

    assert not manager.execute_workflow(workflow.id)

    assert calls == []
    assert workflow.steps == [step]
    assert workflow.get_step(injected.id) is None
    assert step.status == StepStatus.FAILED
    assert workflow.status == StepStatus.FAILED
    assert workflow.audit_log[-1]["reason"] == "condition_side_effect"


def test_workflow_rejects_non_boolean_condition_without_private_result():
    manager = WorkflowManager()
    workflow = manager.create_workflow("bad-condition")
    step = WorkflowStep(
        "guarded",
        lambda: {"private": "payload"},
        condition=lambda workflow, step: "yes",
    )
    workflow.add_step(step)

    assert not manager.execute_workflow(workflow.id)

    assert step.status == StepStatus.FAILED
    assert step.result is None
    assert step.error == "Workflow condition must return a boolean"
    assert workflow.status == StepStatus.FAILED
    assert workflow.audit_log == [{
        "step_id": step.id,
        "step_name": "guarded",
        "decision": "rejected",
        "reason": "condition_non_boolean",
    }]
