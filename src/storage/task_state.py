"""Workspace-scoped task state repository.

Task IDs are not globally unique in multi-workspace deployments. This module
keeps workspace scope in the repository contract so callers cannot accidentally
read or mutate another workspace's task state by task ID alone.
"""

import time
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from src.common.errors import AgentOrchestratorError


class UnscopedTaskStateAccessError(AgentOrchestratorError):
    """Raised when task state is accessed without workspace scope."""

    def __init__(self, operation: str):
        super().__init__(
            f"Task state operation '{operation}' requires workspace_id scope"
        )


class UnscopedTaskStateQueryError(AgentOrchestratorError):
    """Raised when task_state SQL omits a workspace predicate."""

    def __init__(self, operation: str):
        super().__init__(
            f"task_state {operation} query requires workspace_id scope"
        )


@dataclass(frozen=True)
class TaskStateRecord:
    """Immutable task state record keyed by workspace and task."""

    workspace_id: str
    task_id: str
    state: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)
    version: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "task_id": self.task_id,
            "state": self.state,
            "payload": deepcopy(dict(self.payload)),
            "updated_at": self.updated_at,
            "version": self.version,
        }


class ScopedTaskStateRepository:
    """In-memory task-state repository that requires workspace scope."""

    def __init__(self):
        self._records: Dict[Tuple[str, str], TaskStateRecord] = {}

    def put(
        self,
        workspace_id: str,
        task_id: str,
        state: str,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> TaskStateRecord:
        workspace_id = self._require_scope(workspace_id)
        task_id = self._require_task_id(task_id)
        key = (workspace_id, task_id)
        existing = self._records.get(key)
        record = TaskStateRecord(
            workspace_id=workspace_id,
            task_id=task_id,
            state=state,
            payload=deepcopy(dict(payload or {})),
            version=existing.version + 1 if existing else 1,
        )
        self._records[key] = record
        return record

    def get(
        self, workspace_id: str, task_id: str
    ) -> Optional[TaskStateRecord]:
        workspace_id = self._require_scope(workspace_id)
        task_id = self._require_task_id(task_id)
        return self._records.get((workspace_id, task_id))

    def delete(self, workspace_id: str, task_id: str) -> bool:
        workspace_id = self._require_scope(workspace_id)
        task_id = self._require_task_id(task_id)
        return self._records.pop((workspace_id, task_id), None) is not None

    def exists(self, workspace_id: str, task_id: str) -> bool:
        workspace_id = self._require_scope(workspace_id)
        task_id = self._require_task_id(task_id)
        return (workspace_id, task_id) in self._records

    def list_for_workspace(self, workspace_id: str) -> List[TaskStateRecord]:
        workspace_id = self._require_scope(workspace_id)
        return [
            record
            for key, record in sorted(self._records.items())
            if key[0] == workspace_id
        ]

    def count_for_workspace(self, workspace_id: str) -> int:
        workspace_id = self._require_scope(workspace_id)
        return sum(1 for key in self._records if key[0] == workspace_id)

    def get_by_task_id(self, task_id: str) -> Optional[TaskStateRecord]:
        raise UnscopedTaskStateAccessError("get_by_task_id")

    def delete_by_task_id(self, task_id: str) -> bool:
        raise UnscopedTaskStateAccessError("delete_by_task_id")

    def list_all(self) -> List[TaskStateRecord]:
        raise UnscopedTaskStateAccessError("list_all")

    @staticmethod
    def _require_scope(workspace_id: str) -> str:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise ValueError("workspace_id is required for task state access")
        return workspace_id.strip()

    @staticmethod
    def _require_task_id(task_id: str) -> str:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id is required for task state access")
        return task_id.strip()


def postgres_workspace_scope_policy_sql(
    table_name: str = "task_state",
    workspace_column: str = "workspace_id",
    setting_name: str = "app.current_workspace_id",
) -> str:
    """Return PostgreSQL RLS policy SQL for workspace-scoped task state."""

    table_name = _safe_identifier(table_name, "table_name")
    workspace_column = _safe_identifier(workspace_column, "workspace_column")
    setting_literal = setting_name.replace("'", "''")
    policy_name = f"{table_name}_workspace_scope"

    return (
        f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY;\n"
        f"ALTER TABLE {table_name} FORCE ROW LEVEL SECURITY;\n"
        f"DROP POLICY IF EXISTS {policy_name} ON {table_name};\n"
        f"CREATE POLICY {policy_name} ON {table_name}\n"
        "USING (\n"
        f"    {workspace_column} = "
        f"current_setting('{setting_literal}', true)\n"
        ")\n"
        "WITH CHECK (\n"
        f"    {workspace_column} = "
        f"current_setting('{setting_literal}', true)\n"
        ");"
    )


def assert_task_state_sql_scoped(
    sql: str,
    table_name: str = "task_state",
    workspace_column: str = "workspace_id",
) -> str:
    """Reject task_state DML that is not scoped by workspace_id."""

    table_name = _safe_identifier(table_name, "table_name")
    workspace_column = _safe_identifier(workspace_column, "workspace_column")
    normalized = _normalize_sql(sql)
    if not normalized:
        return sql

    operation = normalized.split(" ", 1)[0]
    if operation == "insert" and f"insert into {table_name}" in normalized:
        _require_insert_workspace_column(
            normalized, table_name, workspace_column
        )
    elif operation in {"select", "update", "delete"} and _touches_task_state(
        normalized, operation, table_name
    ):
        _require_where_workspace_predicate(
            normalized, operation, workspace_column
        )
    return sql


def _require_insert_workspace_column(
    sql: str, table_name: str, workspace_column: str
) -> None:
    match = re.search(rf"insert\s+into\s+{table_name}\s*\(([^)]*)\)", sql)
    columns = match.group(1) if match else ""
    column_names = {column.strip() for column in columns.split(",")}
    if workspace_column not in column_names:
        raise UnscopedTaskStateQueryError("insert")


def _touches_task_state(sql: str, operation: str, table_name: str) -> bool:
    if operation == "select":
        return re.search(rf"\bfrom\s+{table_name}\b", sql) is not None
    if operation == "update":
        return re.search(rf"\bupdate\s+{table_name}\b", sql) is not None
    if operation == "delete":
        return re.search(rf"\bfrom\s+{table_name}\b", sql) is not None
    return False


def _require_where_workspace_predicate(
    sql: str, operation: str, workspace_column: str
) -> None:
    where_match = re.search(r"\bwhere\b(.+)", sql)
    if not where_match:
        raise UnscopedTaskStateQueryError(operation)
    where_clause = re.split(
        r"\b(returning|order\s+by|group\s+by|limit)\b",
        where_match.group(1),
        maxsplit=1,
    )[0]
    if re.search(rf"\b{workspace_column}\b", where_clause) is None:
        raise UnscopedTaskStateQueryError(operation)


def _normalize_sql(sql: str) -> str:
    if not isinstance(sql, str):
        raise TypeError("sql must be a string")
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return " ".join(sql.lower().split())


def _safe_identifier(value: str, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty identifier")
    if not value.replace("_", "").isalnum() or value[0].isdigit():
        raise ValueError(
            f"{name} must contain only letters, numbers, and underscores"
        )
    return value
