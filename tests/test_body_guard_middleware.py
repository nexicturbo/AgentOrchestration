import gzip

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.testclient import TestClient

from src.api.middleware import BodyGuardMiddleware, body_guard_context


def make_app():
    app = FastAPI()
    app.state.echo_calls = 0

    @app.post("/echo")
    async def echo(request: Request):
        app.state.echo_calls += 1
        body = await request.body()
        return {
            "body": body.decode(),
            "encoding": request.headers.get("content-encoding"),
            "guard": request.state.body_guard["status"],
        }

    @app.post("/boom")
    async def boom(request: Request):
        app.state.echo_calls += 1
        await request.body()
        raise RuntimeError("handler failed")

    app.add_middleware(
        BodyGuardMiddleware,
        max_compressed_bytes=512,
        max_decompressed_bytes=1024,
        max_expansion_ratio=20,
    )
    return app


def test_valid_gzip_body_is_decompressed_for_handler():
    app = make_app()
    client = TestClient(app)
    payload = b"hello guard"

    response = client.post(
        "/echo",
        content=gzip.compress(payload),
        headers={"content-encoding": "gzip"},
    )

    assert response.status_code == 200
    assert response.headers["x-body-guard"] == "ok"
    assert response.json() == {
        "body": "hello guard",
        "encoding": None,
        "guard": "accepted",
    }
    assert app.state.echo_calls == 1
    assert body_guard_context.get() is None


def test_gzip_expansion_ratio_rejects_before_handler():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/echo",
        content=gzip.compress(b"A" * 1024),
        headers={"content-encoding": "gzip"},
    )

    assert response.status_code == 413
    assert response.headers["x-body-guard"] == "rejected"
    assert "gzip expansion ratio too high" in response.text
    assert "AAAA" not in response.text
    assert app.state.echo_calls == 0
    assert body_guard_context.get() is None


def test_invalid_gzip_body_rejects_without_leaking_body():
    app = make_app()
    client = TestClient(app)

    response = client.post(
        "/echo",
        content=b"not a valid compressed request body",
        headers={"content-encoding": "gzip"},
    )

    assert response.status_code == 400
    assert response.headers["x-body-guard"] == "rejected"
    assert response.text == "invalid gzip body"
    assert "not a valid" not in response.text
    assert app.state.echo_calls == 0
    assert body_guard_context.get() is None


def test_context_is_cleared_when_handler_raises():
    app = make_app()

    @app.exception_handler(RuntimeError)
    async def runtime_error_handler(request: Request, exc: RuntimeError):
        assert body_guard_context.get() is not None
        return Response(status_code=500, content="internal error")

    client = TestClient(app)

    response = client.post(
        "/boom",
        content=gzip.compress(b"small body"),
        headers={"content-encoding": "gzip"},
    )

    assert response.status_code == 500
    assert response.headers["x-body-guard"] == "ok"
    assert response.text == "internal error"
    assert app.state.echo_calls == 1
    assert body_guard_context.get() is None
