from src.orchestrator.workflow import (
    StepStatus,
    WorkflowManager,
    WorkflowStep,
)


def test_partial_rollback_blocks_downstream_steps_with_audit_record():
    manager = WorkflowManager()
    workflow = manager.create_workflow("release")
    calls = []

    def reserve_capacity():
        calls.append("reserve")

    def fail_dispatch():
        calls.append("dispatch")
        raise RuntimeError("dispatch failed with private payload")

    def broken_compensation():
        calls.append("compensate")
        raise RuntimeError("rollback backend timed out")

    def downstream_handler():
        calls.append("downstream")

    reserved = WorkflowStep(
        "reserve capacity",
        reserve_capacity,
        compensation_handler=broken_compensation,
    )
    dispatch = WorkflowStep("dispatch task", fail_dispatch)
    downstream = WorkflowStep("notify downstream", downstream_handler)
    workflow.add_step(reserved).add_step(dispatch).add_step(downstream)

    assert not manager.execute_workflow(workflow.id)

    assert calls == ["reserve", "dispatch", "compensate"]
    assert workflow.status == StepStatus.ROLLBACK_FAILED
    assert reserved.status == StepStatus.ROLLBACK_FAILED
    assert dispatch.status == StepStatus.FAILED
    assert downstream.status == StepStatus.BLOCKED
    assert downstream.result is None
    assert any(
        record["decision"] == "blocked"
        and record["step_id"] == downstream.id
        and "private payload" not in record["reason"]
        for record in workflow.audit_records
    )


def test_successful_compensation_still_blocks_downstream_after_failure():
    manager = WorkflowManager()
    workflow = manager.create_workflow("cleanup")
    calls = []

    workflow.add_step(
        WorkflowStep(
            "create resource",
            lambda: calls.append("create"),
            compensation_handler=lambda: calls.append("cleanup"),
        )
    )
    workflow.add_step(
        WorkflowStep(
            "bind resource",
            lambda: (_ for _ in ()).throw(RuntimeError("bind failed")),
        )
    )
    downstream = WorkflowStep("start worker", lambda: calls.append("start"))
    workflow.add_step(downstream)

    assert not manager.execute_workflow(workflow.id)

    assert calls == ["create", "cleanup"]
    assert workflow.status == StepStatus.FAILED
    assert workflow.steps[0].status == StepStatus.COMPENSATED
    assert downstream.status == StepStatus.BLOCKED
    assert any(
        record["decision"] == "compensated"
        for record in workflow.audit_records
    )


def test_completed_workflow_keeps_downstream_unblocked():
    manager = WorkflowManager()
    workflow = manager.create_workflow("happy path")
    first = WorkflowStep("first", lambda: "ok")
    second = WorkflowStep("second", lambda: "done")
    workflow.add_step(first).add_step(second)

    assert manager.execute_workflow(workflow.id)

    assert workflow.status == StepStatus.COMPLETED
    assert first.status == StepStatus.COMPLETED
    assert second.status == StepStatus.COMPLETED
    assert workflow.audit_records == []


def test_missing_workflow_execute_returns_false():
    assert not WorkflowManager().execute_workflow("missing")
