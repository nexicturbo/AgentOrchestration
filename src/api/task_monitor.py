"""Task monitor long-polling with per-iteration authorization checks."""

from typing import Any, Callable, Dict, Mapping, Optional

from src.api.auth import PermissionService


class TaskMonitor:
    def __init__(self, permission_service: PermissionService):
        self.permission_service = permission_service
        self._task_status: Dict[str, Dict[str, Any]] = {}

    def set_task_status(
        self,
        task_id: str,
        workspace_id: str,
        status: str,
        result: Optional[Any] = None,
    ) -> None:
        self._task_status[task_id] = {
            "task_id": task_id,
            "workspace_id": workspace_id,
            "status": status,
            "result": result,
        }

    def long_poll(
        self,
        task_id: str,
        workspace_id: str,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
        *,
        max_checks: int = 1,
        on_wait: Optional[Callable[[int], None]] = None,
    ) -> Dict[str, Any]:
        checks = max(1, max_checks)
        for attempt in range(checks):
            principal = self.permission_service.authorize_request(
                headers,
                cookies,
                workspace_id=workspace_id,
                required_scope="task:monitor",
                allowed_roles={"owner", "admin", "monitor"},
            )
            task = self._task_status.get(task_id)
            if task and task["workspace_id"] == workspace_id:
                return {
                    "task_id": task_id,
                    "status": task["status"],
                    "principal_id": principal.id,
                    "result": task["result"],
                }
            if on_wait is not None:
                on_wait(attempt)

        return {
            "task_id": task_id,
            "status": "pending",
            "result": None,
        }
