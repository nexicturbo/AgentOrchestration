import time

from fastapi.testclient import TestClient

from src.api.auth import SECRET_METADATA_READ_SCOPE, auth_store
from src.api.secret_metadata import secret_metadata_store
from src.api.server import create_app


WORKSPACE_ID = "workspace-a"
PROJECT_ID = "project-a"
SECRET_NAME = "DATABASE_URL"
SECRET_URL = (
    f"/api/v2/workspaces/{WORKSPACE_ID}/projects/{PROJECT_ID}"
    f"/environment/{SECRET_NAME}/metadata"
)


def setup_function():
    auth_store.reset()
    secret_metadata_store.reset()
    secret_metadata_store.put(
        WORKSPACE_ID,
        PROJECT_ID,
        SECRET_NAME,
        {
            "value": "should-never-return",
            "created_by": "ops@example.com",
            "updated_at": "2026-05-22T14:00:00Z",
        },
    )


def _client():
    return TestClient(create_app())


def _register_token(token, **overrides):
    values = {
        "subject": "user-1",
        "workspace_id": WORKSPACE_ID,
        "project_id": PROJECT_ID,
        "role": "developer",
        "scopes": [SECRET_METADATA_READ_SCOPE],
    }
    values.update(overrides)
    auth_store.register_token(token, **values)


def test_token_client_with_project_role_can_read_secret_metadata():
    _register_token("current-token")

    response = _client().get(
        SECRET_URL,
        headers={"Authorization": "Bearer current-token"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "workspace_id": WORKSPACE_ID,
        "project_id": PROJECT_ID,
        "name": SECRET_NAME,
        "metadata": {
            "created_by": "ops@example.com",
            "updated_at": "2026-05-22T14:00:00Z",
        },
    }
    assert "should-never-return" not in response.text
    assert secret_metadata_store.lookup_count == 1


def test_browser_session_with_project_role_can_read_secret_metadata():
    auth_store.register_session(
        "current-session",
        subject="user-1",
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        role="admin",
        scopes=[SECRET_METADATA_READ_SCOPE],
    )

    client = _client()
    client.cookies.set("ao_session", "current-session")
    response = client.get(SECRET_URL)

    assert response.status_code == 200
    assert response.json()["metadata"]["created_by"] == "ops@example.com"
    assert secret_metadata_store.lookup_count == 1


def test_browser_session_does_not_bypass_other_api_routes():
    auth_store.register_session(
        "current-session",
        subject="user-1",
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        role="admin",
        scopes=[SECRET_METADATA_READ_SCOPE],
    )

    client = _client()
    client.cookies.set("ao_session", "current-session")
    response = client.get("/api/v2/agents")

    assert response.status_code == 401
    assert secret_metadata_store.lookup_count == 0


def test_anonymous_secret_metadata_request_is_denied_before_lookup():
    response = _client().get(SECRET_URL)

    assert response.status_code == 401
    assert secret_metadata_store.lookup_count == 0


def test_malformed_bearer_secret_metadata_request_is_denied_before_lookup():
    response = _client().get(
        SECRET_URL,
        headers={"Authorization": "Token not-bearer"},
    )

    assert response.status_code == 401
    assert secret_metadata_store.lookup_count == 0


def test_stale_token_is_denied_before_secret_metadata_lookup():
    _register_token("expired-token", expires_at=time.time() - 1)

    response = _client().get(
        SECRET_URL,
        headers={"Authorization": "Bearer expired-token"},
    )

    assert response.status_code == 401
    assert secret_metadata_store.lookup_count == 0


def test_revoked_token_is_denied_before_secret_metadata_lookup():
    _register_token("revoked-token", revoked=True)

    response = _client().get(
        SECRET_URL,
        headers={"Authorization": "Bearer revoked-token"},
    )

    assert response.status_code == 401
    assert secret_metadata_store.lookup_count == 0


def test_insufficient_scope_is_denied_before_secret_metadata_lookup():
    _register_token("low-scope-token", scopes=["agents:read"])

    response = _client().get(
        SECRET_URL,
        headers={"Authorization": "Bearer low-scope-token"},
    )

    assert response.status_code == 403
    assert secret_metadata_store.lookup_count == 0


def test_wrong_workspace_role_is_denied_before_secret_metadata_lookup():
    _register_token("wrong-ws-token", workspace_id="workspace-b")

    response = _client().get(
        SECRET_URL,
        headers={"Authorization": "Bearer wrong-ws-token"},
    )

    assert response.status_code == 403
    assert secret_metadata_store.lookup_count == 0
