import time

from fastapi.testclient import TestClient

from src.api.auth import (
    READ_SCOPE,
    WRITE_SCOPE,
    CredentialValidator,
    build_principal,
)
from src.api.middleware import AuthMiddleware
from src.api.server import create_app


def make_client(*principals):
    app = create_app()
    for middleware in app.user_middleware:
        if middleware.cls is AuthMiddleware:
            middleware.kwargs["validator"] = CredentialValidator(
                {principal.token: principal for principal in principals}
            )
            break
    return TestClient(app, follow_redirects=False)


class TestProtectedRouteAuth:
    def test_anonymous_trailing_slash_request_is_denied_before_redirect(self):
        client = make_client()

        response = client.get("/api/v2/agents/")

        assert response.status_code == 401
        assert response.text == "missing_credentials"

    def test_stale_bearer_token_is_denied(self):
        client = make_client(
            build_principal(
                token="stale-token",
                expires_at=time.time() - 1,
            )
        )

        response = client.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer stale-token"},
        )

        assert response.status_code == 401
        assert response.text == "stale_credentials"

    def test_revoked_browser_session_cookie_is_denied(self):
        client = make_client(build_principal("revoked-session", revoked=True))

        response = client.get(
            "/api/v2/agents",
            cookies={"ao_session": "revoked-session"},
        )

        assert response.status_code == 401
        assert response.text == "revoked_credentials"

    def test_insufficient_role_is_denied(self):
        client = make_client(build_principal("viewer-token", role="viewer"))

        response = client.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer viewer-token"},
        )

        assert response.status_code == 401
        assert response.text == "insufficient_role"

    def test_insufficient_scope_is_denied_for_mutating_route(self):
        client = make_client(
            build_principal(
                token="read-token",
                scopes={READ_SCOPE},
            )
        )

        response = client.post(
            "/api/v2/agents",
            params={"name": "runner", "agent_type": "worker"},
            headers={"Authorization": "Bearer read-token"},
        )

        assert response.status_code == 401
        assert response.text == "insufficient_scope"

    def test_authorized_bearer_token_can_read_protected_route(self):
        client = make_client(build_principal("valid-token"))

        response = client.get(
            "/api/v2/agents",
            headers={"Authorization": "Bearer valid-token"},
        )

        assert response.status_code == 200
        assert response.json() == {"agents": []}

    def test_authorized_browser_session_can_complete_mutating_workflow(self):
        client = make_client(
            build_principal(
                token="session-token",
                scopes={READ_SCOPE, WRITE_SCOPE},
            )
        )

        response = client.post(
            "/api/v2/agents",
            params={"name": "runner", "agent_type": "worker"},
            cookies={"ao_session": "session-token"},
        )

        assert response.status_code == 200
        assert response.json()["status"] == "registered"
