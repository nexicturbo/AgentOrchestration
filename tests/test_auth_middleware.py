from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.middleware import AuthMiddleware


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/api/v2/protected")
    async def protected_read(request: Request):
        return {"subject": request.state.principal.subject}

    @app.post("/api/v2/protected")
    async def protected_write(request: Request):
        return {"subject": request.state.principal.subject}

    @app.get("/health")
    async def health():
        return {"ok": True}

    return TestClient(app)


def _token(
    *,
    subject: str = "alice",
    role: str = "operator",
    scopes: str = "agents:read,agents:write",
    workspace: str = "main",
    **flags,
) -> str:
    fields = {
        "sub": subject,
        "role": role,
        "scopes": scopes,
        "workspace": workspace,
    }
    fields.update({key: str(value).lower() for key, value in flags.items()})
    return ";".join(f"{key}={value}" for key, value in fields.items())


def test_bearer_scheme_is_case_insensitive_for_authorized_user():
    response = _client().get(
        "/api/v2/protected",
        headers={"Authorization": f"bEaReR {_token()}"},
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "alice"}


def test_anonymous_request_is_denied_before_route_handler():
    response = _client().get("/api/v2/protected")

    assert response.status_code == 401


def test_non_bearer_scheme_is_denied():
    response = _client().get(
        "/api/v2/protected",
        headers={"Authorization": f"Basic {_token()}"},
    )

    assert response.status_code == 401


def test_stale_principal_is_denied():
    response = _client().get(
        "/api/v2/protected",
        headers={"Authorization": f"Bearer {_token(stale=True)}"},
    )

    assert response.status_code == 401


def test_revoked_principal_is_denied():
    response = _client().get(
        "/api/v2/protected",
        headers={"Authorization": f"Bearer {_token(revoked=True)}"},
    )

    assert response.status_code == 401


def test_anonymous_principal_is_denied():
    response = _client().get(
        "/api/v2/protected",
        headers={"Authorization": f"Bearer {_token(subject='anonymous')}"},
    )

    assert response.status_code == 401


def test_insufficient_scope_is_denied():
    response = _client().post(
        "/api/v2/protected",
        headers={"Authorization": f"Bearer {_token(scopes='agents:read')}"},
    )

    assert response.status_code == 403


def test_insufficient_workspace_role_is_denied():
    response = _client().post(
        "/api/v2/protected",
        headers={"Authorization": f"Bearer {_token(role='viewer')}"},
    )

    assert response.status_code == 403


def test_authorized_workspace_role_can_mutate():
    response = _client().post(
        "/api/v2/protected",
        headers={"Authorization": f"Bearer {_token(role='admin')}"},
    )

    assert response.status_code == 200
    assert response.json() == {"subject": "alice"}


def test_non_api_route_does_not_require_auth():
    response = _client().get("/health")

    assert response.status_code == 200
