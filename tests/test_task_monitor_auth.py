import time

import pytest
from fastapi.testclient import TestClient

from src.api import routes
from src.api.auth import AuthorizationError, PermissionService
from src.api.server import create_app
from src.api.task_monitor import TaskMonitor


def make_monitor():
    permissions = PermissionService()
    permissions.add_principal(
        "user-1",
        {"workspace-a": "monitor"},
        scopes={"task:monitor"},
    )
    permissions.issue_api_key(
        "valid-key",
        "user-1",
        scopes={"task:monitor"},
    )
    permissions.issue_session(
        "valid-session",
        "user-1",
        scopes={"task:monitor"},
    )
    monitor = TaskMonitor(permissions)
    monitor.set_task_status(
        "task-1",
        "workspace-a",
        "completed",
        result={"ok": True},
    )
    return permissions, monitor


def configure_route_monitor():
    permissions, monitor = make_monitor()
    routes.permission_service = permissions
    routes.task_monitor = monitor
    return permissions, monitor


def test_long_poll_allows_authorized_api_key():
    _, monitor = make_monitor()

    result = monitor.long_poll(
        "task-1",
        "workspace-a",
        {"Authorization": "Bearer valid-key"},
        {},
    )

    assert result == {
        "task_id": "task-1",
        "status": "completed",
        "principal_id": "user-1",
        "result": {"ok": True},
    }


def test_long_poll_allows_authorized_browser_session():
    _, monitor = make_monitor()

    result = monitor.long_poll(
        "task-1",
        "workspace-a",
        {},
        {"ao_session": "valid-session"},
    )

    assert result["status"] == "completed"
    assert result["principal_id"] == "user-1"


def test_monitor_route_allows_authorized_browser_session():
    configure_route_monitor()
    client = TestClient(create_app())
    client.cookies.set("ao_session", "valid-session")

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        params={"workspace_id": "workspace-a"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["principal_id"] == "user-1"


def test_monitor_route_rejects_revoked_api_key():
    permissions, _ = configure_route_monitor()
    permissions.revoke_api_key("valid-key")
    client = TestClient(create_app())

    response = client.get(
        "/api/v2/tasks/task-1/monitor",
        params={"workspace_id": "workspace-a"},
        headers={"Authorization": "Bearer valid-key"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "credential has been revoked"


def test_long_poll_denies_anonymous_principal_before_monitoring():
    _, monitor = make_monitor()

    with pytest.raises(AuthorizationError, match="credentials are required"):
        monitor.long_poll("task-1", "workspace-a", {}, {})


def test_long_poll_denies_anonymous_principal_when_checks_are_zero():
    _, monitor = make_monitor()

    with pytest.raises(AuthorizationError, match="credentials are required"):
        monitor.long_poll(
            "task-1",
            "workspace-a",
            {},
            {},
            max_checks=0,
        )


def test_long_poll_denies_stale_expired_api_key():
    permissions, monitor = make_monitor()
    permissions.issue_api_key(
        "expired-key",
        "user-1",
        scopes={"task:monitor"},
        expires_at=time.time() - 1,
    )

    with pytest.raises(AuthorizationError, match="expired"):
        monitor.long_poll(
            "task-1",
            "workspace-a",
            {"Authorization": "Bearer expired-key"},
            {},
        )


def test_long_poll_denies_insufficient_scope():
    permissions, monitor = make_monitor()
    permissions.issue_api_key(
        "wrong-scope",
        "user-1",
        scopes={"agents:read"},
    )

    with pytest.raises(AuthorizationError, match="missing required scope"):
        monitor.long_poll(
            "task-1",
            "workspace-a",
            {"Authorization": "Bearer wrong-scope"},
            {},
        )


def test_long_poll_denies_insufficient_principal_scope():
    permissions, monitor = make_monitor()
    permissions.add_principal(
        "unscoped-user",
        {"workspace-a": "monitor"},
        scopes={"agents:read"},
    )
    permissions.issue_api_key(
        "unscoped-key",
        "unscoped-user",
        scopes={"task:monitor"},
    )

    with pytest.raises(AuthorizationError, match="principal is missing"):
        monitor.long_poll(
            "task-1",
            "workspace-a",
            {"Authorization": "Bearer unscoped-key"},
            {},
        )


def test_long_poll_denies_insufficient_workspace_role():
    permissions, monitor = make_monitor()
    permissions.add_principal(
        "viewer",
        {"workspace-a": "viewer"},
        scopes={"task:monitor"},
    )
    permissions.issue_api_key(
        "viewer-key",
        "viewer",
        scopes={"task:monitor"},
    )

    with pytest.raises(AuthorizationError, match="role is insufficient"):
        monitor.long_poll(
            "task-1",
            "workspace-a",
            {"Authorization": "Bearer viewer-key"},
            {},
        )


def test_long_poll_denies_disabled_principal():
    permissions, monitor = make_monitor()
    permissions.disable_principal("user-1")

    with pytest.raises(AuthorizationError, match="disabled"):
        monitor.long_poll(
            "task-1",
            "workspace-a",
            {"Authorization": "Bearer valid-key"},
            {},
        )


def test_long_poll_revalidates_revoked_api_key_before_each_wait():
    permissions, monitor = make_monitor()

    def revoke_after_first_check(attempt):
        if attempt == 0:
            permissions.revoke_api_key("valid-key")

    with pytest.raises(AuthorizationError, match="revoked"):
        monitor.long_poll(
            "pending-task",
            "workspace-a",
            {"Authorization": "Bearer valid-key"},
            {},
            max_checks=2,
            on_wait=revoke_after_first_check,
        )

    monitor.set_task_status("pending-task", "workspace-a", "completed")
    with pytest.raises(AuthorizationError, match="revoked"):
        monitor.long_poll(
            "pending-task",
            "workspace-a",
            {"Authorization": "Bearer valid-key"},
            {},
        )
