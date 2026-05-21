"""Workflow Manager — Defines and executes multi-step agent workflows."""

import logging
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from uuid import uuid4

import yaml

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowDefinitionError(ValueError):
    def __init__(
        self,
        message: str,
        audit_record: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.audit_record = audit_record or {}


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        step_id: Optional[str] = None,
    ):
        self.id = step_id or str(uuid4())
        self.name = name
        self.handler = handler
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

    def add_step(self, step: WorkflowStep) -> "Workflow":
        if step.id in self._step_map:
            raise WorkflowDefinitionError(
                f"Duplicate workflow step id: {step.id}",
                {
                    "event": "workflow_registration_rejected",
                    "decision": "duplicate_node_id",
                    "node_id": step.id,
                    "workflow_id": self.id,
                },
            )
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}
        self._audit_records: List[Dict[str, Any]] = []

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def create_workflow_from_yaml(
        self,
        yaml_text: str,
        handlers: Optional[Dict[str, Callable]] = None,
        import_resolver: Optional[Callable[[str], Dict[str, Any]]] = None,
        base_path: Optional[Path] = None,
    ) -> Workflow:
        definition = yaml.safe_load(yaml_text) or {}
        if not isinstance(definition, dict):
            raise WorkflowDefinitionError("Workflow YAML must be a mapping")
        return self.create_workflow_from_definition(
            definition,
            handlers=handlers,
            import_resolver=import_resolver,
            base_path=base_path,
        )

    def load_workflow_from_yaml(
        self,
        path: str,
        handlers: Optional[Dict[str, Callable]] = None,
        import_resolver: Optional[Callable[[str], Dict[str, Any]]] = None,
    ) -> Workflow:
        workflow_path = Path(path)
        return self.create_workflow_from_yaml(
            workflow_path.read_text(),
            handlers=handlers,
            import_resolver=import_resolver,
            base_path=workflow_path.parent,
        )

    def create_workflow_from_definition(
        self,
        definition: Dict[str, Any],
        handlers: Optional[Dict[str, Callable]] = None,
        import_resolver: Optional[Callable[[str], Dict[str, Any]]] = None,
        base_path: Optional[Path] = None,
    ) -> Workflow:
        handlers = handlers or {}
        step_specs = self._collect_step_specs(
            definition,
            import_resolver=import_resolver,
            base_path=base_path,
        )
        self._reject_duplicate_node_ids(step_specs)

        workflow = Workflow(
            definition.get("name", "workflow"),
            definition.get("description", ""),
        )
        for step_id, _, spec in step_specs:
            handler_key = spec.get("handler", step_id)
            handler = handlers.get(handler_key, handlers.get(step_id))
            if handler is None:
                handler = self._unbound_handler(step_id)
            workflow.add_step(
                WorkflowStep(
                    spec.get("name", step_id),
                    handler,
                    retries=int(spec.get("retries", 0)),
                    timeout=int(spec.get("timeout", 300)),
                    step_id=step_id,
                )
            )

        self._workflows[workflow.id] = workflow
        return workflow

    def audit_records(self) -> List[Dict[str, Any]]:
        return list(self._audit_records)

    def _collect_step_specs(
        self,
        definition: Dict[str, Any],
        import_resolver: Optional[Callable[[str], Dict[str, Any]]] = None,
        source: str = "root",
        import_stack: Optional[Set[str]] = None,
        base_path: Optional[Path] = None,
    ) -> List[Tuple[str, str, Dict[str, Any]]]:
        import_stack = import_stack or set()
        specs: List[Tuple[str, str, Dict[str, Any]]] = []

        for import_name in definition.get("imports", []) or []:
            imported, import_source, next_base_path = self._resolve_import(
                str(import_name),
                import_resolver,
                base_path,
            )
            if import_source in import_stack:
                raise WorkflowDefinitionError(
                    f"Recursive workflow import rejected: {import_name}"
                )
            if not isinstance(imported, dict):
                raise WorkflowDefinitionError(
                    f"Workflow import is not a mapping: {import_name}"
                )
            specs.extend(
                self._collect_step_specs(
                    imported,
                    import_resolver,
                    source=import_source,
                    import_stack=import_stack | {import_source},
                    base_path=next_base_path,
                )
            )

        raw_steps = definition.get("steps", definition.get("nodes", [])) or []
        if not isinstance(raw_steps, list):
            raise WorkflowDefinitionError("Workflow steps must be a list")
        for index, spec in enumerate(raw_steps):
            if not isinstance(spec, dict):
                raise WorkflowDefinitionError(
                    "Workflow step must be a mapping"
                )
            step_id = spec.get("id")
            if not step_id:
                raise WorkflowDefinitionError(
                    f"Workflow step at {source}[{index}] is missing id"
                )
            specs.append((str(step_id), source, spec))

        return specs

    def _resolve_import(
        self,
        import_name: str,
        import_resolver: Optional[Callable[[str], Dict[str, Any]]],
        base_path: Optional[Path],
    ) -> Tuple[Dict[str, Any], str, Optional[Path]]:
        if import_resolver:
            return import_resolver(import_name), import_name, base_path

        import_path = Path(import_name)
        if not import_path.is_absolute() and base_path is not None:
            import_path = base_path / import_path
        import_path = import_path.resolve()
        return (
            yaml.safe_load(import_path.read_text()) or {},
            str(import_path),
            import_path.parent,
        )

    def _reject_duplicate_node_ids(
        self,
        step_specs: List[Tuple[str, str, Dict[str, Any]]],
    ) -> None:
        seen: Dict[str, str] = {}
        for step_id, source, _ in step_specs:
            if step_id in seen:
                audit_record = {
                    "event": "workflow_registration_rejected",
                    "decision": "duplicate_node_id",
                    "node_id": step_id,
                    "first_source": seen[step_id],
                    "duplicate_source": source,
                }
                self._audit_records.append(audit_record)
                logger.warning(
                    "Rejected workflow registration with duplicate node id %s",
                    step_id,
                )
                raise WorkflowDefinitionError(
                    f"Duplicate workflow node id: {step_id}",
                    audit_record,
                )
            seen[step_id] = source

    @staticmethod
    def _unbound_handler(step_id: str) -> Callable:
        def handler():
            raise RuntimeError(
                f"No handler registered for workflow step {step_id}"
            )

        return handler

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
            step.status = StepStatus.RUNNING
            try:
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
