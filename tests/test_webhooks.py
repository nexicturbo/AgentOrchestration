import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.api.webhooks import webhook_service


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def clear_webhooks():
    webhook_service.clear()
    yield
    webhook_service.clear()


@pytest.fixture()
def client():
    return TestClient(create_app())


def create_subscription(
    client,
    workspace_id="workspace-a",
    event_types=None,
    enabled=True,
):
    response = client.post(
        "/api/v2/webhooks/subscriptions",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": workspace_id,
            "endpoint": f"https://hooks.example.com/{workspace_id}",
            "event_types": event_types or ["task.completed"],
            "enabled": enabled,
        },
    )
    assert response.status_code == 201
    return response.json()


def test_subscription_create_rejects_event_type_before_persistence(client):
    response = client.post(
        "/api/v2/webhooks/subscriptions",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "endpoint": "https://hooks.example.com/workspace-a",
            "event_types": ["task.completed", "internal.audit"],
        },
    )

    assert response.status_code == 400
    assert "Unsupported webhook event type" in response.json()["detail"]

    response = client.get(
        "/api/v2/webhooks/subscriptions",
        headers=AUTH_HEADERS,
        params={"workspace_id": "workspace-a"},
    )
    assert response.json() == {"subscriptions": []}


def test_valid_delivery_is_idempotent_and_hides_internal_fields(client):
    subscription = create_subscription(client)
    payload = {
        "result": "ok",
        "internal_metadata": {"worker": "hidden"},
        "_private": "hidden",
    }

    first = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-1",
            "payload": payload,
        },
    )
    second = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-1",
            "payload": payload,
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()

    deliveries = first.json()["deliveries"]
    assert deliveries == [{
        "delivery_id": "delivery-1",
        "subscription_id": subscription["id"],
        "workspace_id": "workspace-a",
        "event_type": "task.completed",
        "endpoint": "https://hooks.example.com/workspace-a",
        "status": "delivered",
        "attempts": 1,
    }]
    assert "internal_metadata" not in first.text
    assert "_private" not in first.text
    assert "callback_headers" not in first.text


def test_rejected_delivery_does_not_create_records(client):
    create_subscription(client)

    response = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "internal.audit",
            "delivery_id": "delivery-2",
            "payload": {},
        },
    )

    assert response.status_code == 400
    retry = client.post(
        "/api/v2/webhooks/deliveries/delivery-2/retry",
        headers=AUTH_HEADERS,
        json={"workspace_id": "workspace-a"},
    )
    assert retry.json() == {"deliveries": []}


def test_retry_transitions_once_and_remains_idempotent(client):
    create_subscription(client)

    delivery = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-3",
            "payload": {},
            "simulate_failure": True,
        },
    )
    assert delivery.json()["deliveries"][0]["status"] == "pending_retry"
    assert delivery.json()["deliveries"][0]["attempts"] == 1

    first_retry = client.post(
        "/api/v2/webhooks/deliveries/delivery-3/retry",
        headers=AUTH_HEADERS,
        json={"workspace_id": "workspace-a"},
    )
    second_retry = client.post(
        "/api/v2/webhooks/deliveries/delivery-3/retry",
        headers=AUTH_HEADERS,
        json={"workspace_id": "workspace-a"},
    )

    assert first_retry.json()["deliveries"][0]["status"] == "delivered"
    assert first_retry.json()["deliveries"][0]["attempts"] == 2
    assert second_retry.json() == first_retry.json()


def test_delivery_respects_workspace_and_disabled_subscription_scope(client):
    workspace_a = create_subscription(client, workspace_id="workspace-a")
    create_subscription(client, workspace_id="workspace-a", enabled=False)
    workspace_b = create_subscription(client, workspace_id="workspace-b")

    response_a = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-4",
            "payload": {},
        },
    )
    response_b = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-b",
            "event_type": "task.completed",
            "delivery_id": "delivery-4",
            "payload": {},
        },
    )

    assert [
        delivery["subscription_id"]
        for delivery in response_a.json()["deliveries"]
    ] == [workspace_a["id"]]
    assert [
        delivery["subscription_id"]
        for delivery in response_b.json()["deliveries"]
    ] == [workspace_b["id"]]
