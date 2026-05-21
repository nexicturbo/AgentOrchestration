from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api.middleware import UploadBoundaryMiddleware


def create_upload_app():
    app = FastAPI()
    app.add_middleware(UploadBoundaryMiddleware)
    calls = {"count": 0, "state_seen": False}

    @app.post("/upload")
    async def upload(request: Request):
        calls["count"] += 1
        calls["state_seen"] = getattr(
            request.state,
            "upload_boundary_validated",
            False,
        )
        await request.body()
        return {"ok": True}

    @app.post("/upload-error")
    async def upload_error(request: Request):
        calls["count"] += 1
        calls["state_seen"] = getattr(
            request.state,
            "upload_boundary_validated",
            False,
        )
        raise RuntimeError("boom")

    app.state.calls = calls
    return app


def test_valid_multipart_boundary_reaches_handler():
    app = create_upload_app()
    client = TestClient(app)

    response = client.post(
        "/upload",
        content=b"--safe\r\n\r\n--safe--\r\n",
        headers={"Content-Type": "multipart/form-data; boundary=safe"},
    )

    assert response.status_code == 200
    assert response.headers["X-Upload-Guard"] == "accepted"
    assert app.state.calls == {"count": 1, "state_seen": True}


def test_missing_multipart_boundary_is_rejected_before_handler():
    app = create_upload_app()
    client = TestClient(app)

    response = client.post(
        "/upload",
        content=b"large body never buffered by handler",
        headers={"Content-Type": "multipart/form-data"},
    )

    assert response.status_code == 400
    assert response.headers["X-Upload-Guard"] == "rejected"
    assert "missing" in response.text
    assert app.state.calls == {"count": 0, "state_seen": False}


def test_malformed_multipart_boundary_is_rejected_without_echoing_value():
    app = create_upload_app()
    client = TestClient(app)

    response = client.post(
        "/upload",
        content=b"large body never buffered by handler",
        headers={
            "Content-Type": (
                "multipart/form-data; boundary=secret-token@leak"
            )
        },
    )

    assert response.status_code == 400
    assert response.headers["X-Upload-Guard"] == "rejected"
    assert "secret-token" not in response.text
    assert app.state.calls == {"count": 0, "state_seen": False}


def test_upload_middleware_exception_path_clears_state():
    app = create_upload_app()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        "/upload-error",
        content=b"--safe\r\n\r\n--safe--\r\n",
        headers={"Content-Type": "multipart/form-data; boundary=safe"},
    )

    assert response.status_code == 500
    assert response.headers["X-Upload-Guard"] == "error"
    assert app.state.calls == {"count": 1, "state_seen": True}
