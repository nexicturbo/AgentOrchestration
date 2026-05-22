import logging

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.api.middleware import CacheControlMiddleware
from src.api.server import create_app


CACHE_STATE_ATTR = "_ao_authenticated_json_cache"


def test_authenticated_json_response_is_no_store(caplog):
    caplog.set_level(logging.INFO, logger="src.api.middleware")

    response = TestClient(create_app()).get(
        "/api/v2/agents",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert response.headers["Vary"] == "Authorization, Cookie"
    assert "test-token" not in caplog.text
    assert "Applied authenticated JSON cache controls" in caplog.text


def test_rejected_request_does_not_get_authenticated_cache_headers():
    response = TestClient(create_app()).get("/api/v2/agents")

    assert response.status_code == 401
    assert "Cache-Control" not in response.headers
    assert "Pragma" not in response.headers
    assert "Expires" not in response.headers


def test_public_json_response_does_not_get_authenticated_cache_headers():
    response = TestClient(create_app()).get("/health")

    assert response.status_code == 200
    assert "Cache-Control" not in response.headers
    assert "Pragma" not in response.headers
    assert "Expires" not in response.headers


def test_authenticated_json_appends_required_vary_values():
    app = FastAPI()

    @app.get("/json")
    async def json_route():
        return JSONResponse(
            {"ok": True},
            headers={"Vary": "Accept-Encoding, authorization"},
        )

    app.add_middleware(CacheControlMiddleware)
    response = TestClient(app).get(
        "/json",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.headers["Vary"] == (
        "Accept-Encoding, authorization, Cookie"
    )


def test_cache_middleware_clears_state_after_success():
    app = FastAPI()
    seen_state = []
    captured_requests = []

    @app.get("/json")
    async def json_route(request: Request):
        captured_requests.append(request)
        seen_state.append(hasattr(request.state, CACHE_STATE_ATTR))
        return {"ok": True}

    app.add_middleware(CacheControlMiddleware)
    response = TestClient(app).get(
        "/json",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert seen_state == [True]
    assert captured_requests
    assert not hasattr(captured_requests[0].state, CACHE_STATE_ATTR)


def test_cache_middleware_clears_state_after_exception():
    app = FastAPI()
    seen_state = []
    captured_requests = []

    @app.get("/boom")
    async def boom(request: Request):
        captured_requests.append(request)
        seen_state.append(hasattr(request.state, CACHE_STATE_ATTR))
        raise RuntimeError("boom")

    app.add_middleware(CacheControlMiddleware)

    with pytest.raises(RuntimeError):
        TestClient(app, raise_server_exceptions=True).get(
            "/boom",
            headers={"Authorization": "Bearer test-token"},
        )

    assert seen_state == [True]
    assert captured_requests
    assert not hasattr(captured_requests[0].state, CACHE_STATE_ATTR)
