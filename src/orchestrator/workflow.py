"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from inspect import signature
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        condition: Optional[Callable] = None,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.condition = condition
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING
        self.audit_log: List[Dict[str, str]] = []

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            try:
                decision = self._evaluate_condition(workflow, step)
                if decision is False:
                    step.status = StepStatus.SKIPPED
                    workflow.audit_log.append({
                        "step_id": step.id,
                        "step_name": step.name,
                        "decision": "skipped",
                        "reason": "condition_false",
                    })
                    continue

                step.status = StepStatus.RUNNING
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                return False

        workflow.status = StepStatus.COMPLETED
        return True

    def _evaluate_condition(
        self,
        workflow: Workflow,
        step: WorkflowStep,
    ) -> bool:
        if step.condition is None:
            return True

        snapshot = self._snapshot_workflow(workflow)
        try:
            decision = self._call_condition(step.condition, workflow, step)
        except Exception as e:
            self._restore_workflow(workflow, snapshot)
            step.error = "condition evaluation failed"
            workflow.audit_log.append({
                "step_id": step.id,
                "step_name": step.name,
                "decision": "rejected",
                "reason": "condition_error",
            })
            raise ValueError("Workflow condition evaluation failed") from e

        side_effects = self._condition_side_effects(workflow, snapshot)
        if side_effects:
            self._restore_workflow(workflow, snapshot)
            step.error = "condition caused workflow side effects"
            workflow.audit_log.append({
                "step_id": step.id,
                "step_name": step.name,
                "decision": "rejected",
                "reason": "condition_side_effect",
            })
            raise ValueError(
                "Workflow condition attempted lifecycle side effects"
            )

        if not isinstance(decision, bool):
            step.error = "condition must return a boolean"
            workflow.audit_log.append({
                "step_id": step.id,
                "step_name": step.name,
                "decision": "rejected",
                "reason": "condition_non_boolean",
            })
            raise ValueError("Workflow condition must return a boolean")
        return decision

    def _call_condition(
        self,
        condition: Callable,
        workflow: Workflow,
        step: WorkflowStep,
    ) -> Any:
        parameters = signature(condition).parameters
        if len(parameters) == 0:
            return condition()
        if len(parameters) == 1:
            return condition(workflow)
        return condition(workflow, step)

    def _snapshot_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        return {
            "audit_log": list(workflow.audit_log),
            "workflow_status": workflow.status,
            "steps": list(workflow.steps),
            "step_map": dict(workflow._step_map),
            "step_state": {
                step.id: self._snapshot_step(step)
                for step in workflow.steps
            },
        }

    def _snapshot_step(self, step: WorkflowStep) -> Tuple:
        return (
            step.name,
            step.handler,
            step.condition,
            step.retries,
            step.timeout,
            step.status,
            step.result,
            step.error,
        )

    def _restore_workflow(
        self,
        workflow: Workflow,
        snapshot: Dict[str, Any],
    ) -> None:
        workflow.status = snapshot["workflow_status"]
        workflow.steps = snapshot["steps"]
        workflow._step_map = snapshot["step_map"]
        workflow.audit_log = snapshot["audit_log"]
        for step in workflow.steps:
            state = snapshot["step_state"][step.id]
            (
                step.name,
                step.handler,
                step.condition,
                step.retries,
                step.timeout,
                step.status,
                step.result,
                step.error,
            ) = state

    def _condition_side_effects(
        self,
        workflow: Workflow,
        snapshot: Dict[str, Any],
    ) -> bool:
        if workflow.status != snapshot["workflow_status"]:
            return True
        if [step.id for step in workflow.steps] != [
            step.id for step in snapshot["steps"]
        ]:
            return True
        if workflow._step_map != snapshot["step_map"]:
            return True
        if workflow.audit_log != snapshot["audit_log"]:
            return True
        return any(
            self._snapshot_step(step) != snapshot["step_state"][step.id]
            for step in snapshot["steps"]
        )

# 2019-03-27T19:58:07 update

# 2019-05-09T09:42:56 update

# 2019-12-03T10:07:42 update

# 2020-01-16T18:43:28 update

# 2020-03-20T10:40:15 update

# 2020-04-17T15:36:50 update

# 2020-05-04T14:44:01 update

# 2020-06-16T13:17:31 update

# 2020-08-05T17:00:24 update

# 2020-09-04T08:29:23 update

# 2020-09-09T17:52:02 update

# 2020-10-23T10:57:44 update

# 2020-12-05T20:55:47 update

# 2021-01-15T19:23:40 update

# 2021-02-03T20:43:12 update

# 2021-03-16T12:26:47 update

# 2021-04-20T14:33:28 update

# 2021-10-14T15:03:32 update

# 2021-10-21T17:24:55 update

# 2021-11-16T17:01:08 update

# 2021-11-22T09:51:21 update

# 2021-12-21T16:15:47 update

# 2022-03-23T16:52:27 update

# 2022-12-21T09:25:50 update

# 2023-01-09T09:55:25 update

# 2023-01-13T11:06:15 update

# 2023-01-26T11:00:59 update

# 2023-02-23T08:56:54 update

# 2023-05-17T08:07:16 update

# 2023-06-06T17:09:34 update

# 2023-06-13T10:35:28 update

# 2023-08-24T20:36:06 update

# 2023-10-30T19:10:13 update

# 2024-01-02T08:27:25 update

# 2024-01-24T12:13:15 update

# 2024-02-08T13:35:49 update

# 2024-05-07T16:09:24 update

# 2024-05-11T09:48:46 update

# 2024-05-21T19:25:41 update

# 2024-06-05T12:00:30 update

# 2024-06-25T09:40:26 update

# 2024-09-17T13:49:39 update

# 2024-10-14T17:39:35 update

# 2024-11-27T20:14:35 update

# 2024-12-25T19:31:41 update

# 2025-01-16T13:15:09 update

# 2025-02-05T14:06:59 update

# 2025-02-17T20:55:11 update

# 2025-04-30T19:36:53 update

# 2025-07-17T10:14:40 update

# 2025-08-29T12:13:15 update

# 2025-09-03T13:51:11 update

# 2025-09-19T16:08:24 update

# 2025-11-27T08:38:12 update

# 2026-01-27T13:23:38 update

# 2026-01-28T11:22:50 update
