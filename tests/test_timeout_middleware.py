import asyncio
import logging

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from src.api.middleware import TimeoutMiddleware, get_request_timeout_state


def _build_app(timeout_seconds=0.05):
    app = FastAPI()
    app.add_middleware(TimeoutMiddleware, timeout_seconds=timeout_seconds)
    return app


def test_timeout_middleware_adds_safe_headers_for_normal_request():
    app = _build_app()

    @app.get("/ok")
    async def ok():
        assert get_request_timeout_state()["active"] is True
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get("/ok")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["x-request-timeout"] == "enforced"
    assert response.headers["x-request-timeout-cleared"] == "true"
    assert get_request_timeout_state() is None


def test_timeout_middleware_rejects_slow_stream_before_body_leaks(caplog):
    app = _build_app(timeout_seconds=0.01)

    async def slow_stream():
        await asyncio.sleep(0.05)
        yield b"private stream body"

    @app.get("/stream")
    async def stream():
        return StreamingResponse(slow_stream(), media_type="text/plain")

    with caplog.at_level(logging.WARNING, logger="src.api.middleware"):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/stream")

    assert response.status_code == 504
    assert response.text == "Request timed out"
    assert response.headers["x-request-timeout"] == "exceeded"
    assert response.headers["x-request-timeout-cleared"] == "true"
    assert "private stream body" not in response.text
    assert "private stream body" not in caplog.text
    assert "request timeout" in caplog.text
    assert get_request_timeout_state() is None


def test_timeout_middleware_clears_state_after_exception_without_secret_log(
    caplog,
):
    app = _build_app()

    @app.get("/boom")
    async def boom():
        assert get_request_timeout_state()["active"] is True
        raise RuntimeError("secret-token-123")

    with caplog.at_level(logging.ERROR, logger="src.api.middleware"):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/boom")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    assert response.headers["x-request-timeout"] == "error"
    assert response.headers["x-request-timeout-cleared"] == "true"
    assert "RuntimeError" in caplog.text
    assert "secret-token-123" not in caplog.text
    assert get_request_timeout_state() is None
