import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.middleware import (
    SECURITY_HEADERS,
    SecurityHeadersMiddleware,
    get_request_context,
)
from src.api.server import create_app


def assert_security_headers(response):
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value


def test_security_headers_on_normal_response():
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert_security_headers(response)
    assert get_request_context() is None


def test_security_headers_on_rejected_auth_response():
    client = TestClient(create_app())

    response = client.get("/api/v2/agents")

    assert response.status_code == 401
    assert response.text == "Unauthorized"
    assert_security_headers(response)
    assert get_request_context() is None


def test_exception_response_does_not_leak_request_data(caplog):
    app = create_app()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("sensitive-marker=abc123")

    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="src.api.middleware"):
        response = client.get("/boom?marker=hidden-value")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert_security_headers(response)
    assert get_request_context() is None

    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["Unhandled request error for GET /boom"]
    assert "hidden-value" not in caplog.text
    assert "sensitive-marker" not in caplog.text


def test_request_context_is_available_only_during_request():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/context")
    async def context():
        return {"context": get_request_context()}

    client = TestClient(app)

    response = client.get("/context")

    assert response.status_code == 200
    assert response.json() == {
        "context": {"method": "GET", "path": "/context"},
    }
    assert_security_headers(response)
    assert get_request_context() is None
