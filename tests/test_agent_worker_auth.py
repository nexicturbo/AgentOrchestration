import time

from fastapi.testclient import TestClient

from src.api.auth import AuthService
from src.api.server import create_app


def make_client(revoked=None):
    auth = AuthService(
        secret="test-secret",
        max_token_age=60,
        revoked_token_ids=revoked,
    )
    return TestClient(create_app({"auth_service": auth})), auth


def token_for(auth, **overrides):
    now = int(time.time())
    claims = {
        "sub": "worker-1",
        "workspace_id": "workspace-a",
        "scope": "agents:read agents:write",
        "role": "operator",
        "iat": now,
        "nbf": now - 1,
        "exp": now + 60,
        "jti": "token-1",
    }
    claims.update(overrides)
    return auth.create_token(claims)


def auth_headers(token, workspace_id="workspace-a"):
    return {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": workspace_id,
    }


def test_anonymous_agent_worker_request_is_denied():
    client, _ = make_client()

    response = client.get(
        "/api/v2/agents",
        headers={"X-Workspace-ID": "workspace-a"},
    )

    assert response.status_code == 401


def test_wrong_jwt_audience_is_denied():
    client, auth = make_client()
    token = token_for(auth, aud="public-api")

    response = client.get("/api/v2/agents", headers=auth_headers(token))

    assert response.status_code == 401


def test_stale_token_is_denied():
    client, auth = make_client()
    now = int(time.time())
    token = token_for(auth, iat=now - 120, exp=now + 60)

    response = client.get("/api/v2/agents", headers=auth_headers(token))

    assert response.status_code == 401


def test_revoked_token_is_denied():
    client, auth = make_client(revoked={"token-1"})
    token = token_for(auth)

    response = client.get("/api/v2/agents", headers=auth_headers(token))

    assert response.status_code == 401


def test_insufficient_scope_is_denied_before_write():
    client, auth = make_client()
    token = token_for(auth, scope="agents:read")

    response = client.post(
        "/api/v2/agents?name=worker&agent_type=worker.processor",
        headers=auth_headers(token),
    )

    assert response.status_code == 401


def test_insufficient_workspace_role_is_denied_before_write():
    client, auth = make_client()
    token = token_for(auth, role="reader")

    response = client.post(
        "/api/v2/agents?name=worker&agent_type=worker.processor",
        headers=auth_headers(token),
    )

    assert response.status_code == 401


def test_browser_session_cookie_uses_same_authorization_path():
    client, auth = make_client()
    token = token_for(auth)
    client.cookies.set("ao_session", token)

    response = client.get(
        "/api/v2/agents",
        headers={"X-Workspace-ID": "workspace-a"},
    )

    assert response.status_code == 200


def test_authorized_worker_can_complete_agent_workflow():
    client, auth = make_client()
    token = token_for(auth)

    created = client.post(
        "/api/v2/agents?name=worker&agent_type=worker.processor",
        headers=auth_headers(token),
    )
    assert created.status_code == 200
    agent_id = created.json()["agent_id"]

    started = client.post(
        f"/api/v2/agents/{agent_id}/start",
        headers=auth_headers(token),
    )
    listed = client.get("/api/v2/agents", headers=auth_headers(token))

    assert started.status_code == 200
    assert listed.status_code == 200
    assert listed.json()["agents"][0]["status"] == "running"


def test_workspace_mismatch_is_denied():
    client, auth = make_client()
    token = token_for(auth, workspace_id="workspace-a")

    response = client.get(
        "/api/v2/agents",
        headers=auth_headers(token, workspace_id="workspace-b"),
    )

    assert response.status_code == 401
