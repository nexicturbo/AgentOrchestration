from fastapi import FastAPI
from fastapi.testclient import TestClient

import src.api.routes as routes
import src.api.run_events as run_events


class FailingRunEventStore:
    def list_events(self, workspace_id, run_id, offset, limit):
        raise AssertionError("protected lookup should not run")


class RecordingRunEventStore:
    def __init__(self):
        self.calls = []

    def list_events(self, workspace_id, run_id, offset, limit):
        self.calls.append((workspace_id, run_id, offset, limit))
        return [{"id": "event-1"}]


def make_client():
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_run_events_authorized_request_uses_bounded_lookup(monkeypatch):
    store = RecordingRunEventStore()
    monkeypatch.setattr(run_events, "run_event_store", store)
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=5&limit=10",
        headers={
            "Authorization": "Bearer token",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 200
    assert response.json()["events"] == [{"id": "event-1"}]
    assert response.json()["workspace_id"] == "workspace-a"
    assert store.calls == [("workspace-a", "run-1", 5, 10)]


def test_run_events_boundary_window_is_allowed(monkeypatch):
    store = RecordingRunEventStore()
    monkeypatch.setattr(run_events, "run_event_store", store)
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=900&limit=100",
        headers={
            "Authorization": "Bearer token",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 200
    assert store.calls == [("workspace-a", "run-1", 900, 100)]


def test_run_events_unauthorized_request_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get("/runs/run-1/events?offset=0&limit=10")

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_run_events_blank_bearer_token_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=0&limit=10",
        headers={
            "Authorization": "Bearer   ",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Unauthorized"


def test_blank_run_id_rejected_by_service_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())

    try:
        run_events.list_run_events(
            "workspace-a", " ", "Bearer token", offset=0, limit=10
        )
    except Exception as exc:
        assert exc.status_code == 400
        assert exc.detail == "run_id is required"
    else:
        raise AssertionError("blank run_id should fail before lookup")


def test_blank_workspace_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=0&limit=10",
        headers={"Authorization": "Bearer token", "X-Workspace-Id": "   "},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "workspace_id is required"


def test_missing_workspace_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=0&limit=10",
        headers={"Authorization": "Bearer token"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "workspace_id is required"


def test_run_events_limit_above_cap_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=0&limit=101",
        headers={
            "Authorization": "Bearer token",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "limit exceeds maximum"


def test_run_events_pagination_window_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=950&limit=100",
        headers={
            "Authorization": "Bearer token",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "pagination window exceeds maximum"


def test_run_events_window_past_boundary_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=901&limit=100",
        headers={
            "Authorization": "Bearer token",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "pagination window exceeds maximum"


def test_run_events_non_integer_query_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=not-an-int&limit=10",
        headers={
            "Authorization": "Bearer token",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 422


def test_run_events_negative_offset_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=-1&limit=10",
        headers={
            "Authorization": "Bearer token",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "offset must be non-negative"


def test_run_events_zero_limit_rejected_before_lookup(monkeypatch):
    monkeypatch.setattr(run_events, "run_event_store", FailingRunEventStore())
    client = make_client()

    response = client.get(
        "/runs/run-1/events?offset=0&limit=0",
        headers={
            "Authorization": "Bearer token",
            "X-Workspace-Id": "workspace-a",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "limit must be positive"
