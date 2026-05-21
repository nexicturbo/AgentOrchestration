import time

from fastapi.testclient import TestClient

from src.api.server import create_app


def _app():
    now = time.time()
    return create_app({
        "auth": {
            "tokens": {
                "docs-reader": {
                    "subject": "user-1",
                    "workspace_id": "workspace-a",
                    "scopes": ["docs:read"],
                    "roles": {"workspace-a": "reader"},
                    "expires_at": now + 3600,
                },
                "browser-session": {
                    "subject": "user-2",
                    "workspace_id": "workspace-a",
                    "scopes": ["docs:read"],
                    "roles": {"workspace-a": "admin"},
                    "expires_at": now + 3600,
                },
                "stale-token": {
                    "subject": "user-3",
                    "workspace_id": "workspace-a",
                    "scopes": ["docs:read"],
                    "roles": {"workspace-a": "reader"},
                    "expires_at": now - 1,
                },
                "no-doc-scope": {
                    "subject": "user-4",
                    "workspace_id": "workspace-a",
                    "scopes": ["agents:read"],
                    "roles": {"workspace-a": "reader"},
                    "expires_at": now + 3600,
                },
                "no-workspace-role": {
                    "subject": "user-5",
                    "workspace_id": "workspace-a",
                    "scopes": ["docs:read"],
                    "roles": {"workspace-a": "viewer"},
                    "expires_at": now + 3600,
                },
                "revoked-token": {
                    "subject": "user-6",
                    "workspace_id": "workspace-a",
                    "scopes": ["docs:read"],
                    "roles": {"workspace-a": "reader"},
                    "expires_at": now + 3600,
                    "revoked": True,
                },
            }
        }
    })


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_stays_public():
    response = TestClient(_app()).get("/health")
    assert response.status_code == 200


def test_openapi_schema_denies_anonymous_and_malformed_clients():
    client = TestClient(_app())
    assert client.get("/api/openapi.json").status_code == 401
    assert client.get(
        "/api/openapi.json",
        headers={"Authorization": "Basic nope"},
    ).status_code == 401
    assert client.get(
        "/api/openapi.json",
        headers={"Authorization": "Bearer "},
    ).status_code == 401


def test_openapi_schema_denies_stale_revoked_and_unknown_tokens():
    client = TestClient(_app())
    assert client.get(
        "/api/openapi.json",
        headers=_auth("stale-token"),
    ).status_code == 401
    assert client.get(
        "/api/openapi.json",
        headers=_auth("revoked-token"),
    ).status_code == 401
    assert client.get(
        "/api/openapi.json",
        headers=_auth("missing-token"),
    ).status_code == 401


def test_docs_fail_closed_when_no_token_registry_exists():
    response = TestClient(create_app()).get(
        "/api/openapi.json",
        headers=_auth("anything"),
    )
    assert response.status_code == 401


def test_openapi_schema_denies_missing_scope_or_workspace_role():
    client = TestClient(_app())
    assert client.get(
        "/api/openapi.json",
        headers=_auth("no-doc-scope"),
    ).status_code == 403
    assert client.get(
        "/api/openapi.json",
        headers=_auth("no-workspace-role"),
    ).status_code == 403


def test_openapi_schema_allows_authorized_bearer_token():
    response = TestClient(_app()).get(
        "/api/openapi.json",
        headers=_auth("docs-reader"),
    )
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Agent Orchestrator API"


def test_docs_allow_authorized_browser_session_and_disable_public_defaults():
    client = TestClient(_app())
    assert client.get("/docs").status_code == 401
    assert client.get("/openapi.json").status_code == 401

    client.cookies.set("ao_session", "browser-session")
    response = client.get("/api/docs")
    assert response.status_code == 200
    assert "/api/openapi.json" in response.text
