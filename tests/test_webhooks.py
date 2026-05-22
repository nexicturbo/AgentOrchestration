import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.api.webhook_auth import (
    MANAGE_WEBHOOKS_SCOPE,
    webhook_auth_guard,
)
from src.api.webhooks import webhook_service


AUTH_HEADERS = {"Authorization": "Bearer test-token"}


@pytest.fixture(autouse=True)
def clear_webhooks():
    webhook_service.clear()
    webhook_auth_guard.clear()
    webhook_auth_guard.add_token(
        "test-token",
        workspaces={"workspace-a", "workspace-b"},
        scopes={MANAGE_WEBHOOKS_SCOPE},
        role="admin",
    )
    webhook_auth_guard.add_session(
        "browser-session",
        workspaces={"workspace-a"},
        scopes={MANAGE_WEBHOOKS_SCOPE},
        role="owner",
    )
    yield
    webhook_service.clear()
    webhook_auth_guard.clear()


@pytest.fixture()
def client():
    return TestClient(create_app())


def create_subscription(
    client,
    workspace_id="workspace-a",
    event_types=None,
    enabled=True,
    endpoint=None,
):
    response = client.post(
        "/api/v2/webhooks/subscriptions",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": workspace_id,
            "endpoint": (
                endpoint or f"https://hooks.example.com/{workspace_id}"
            ),
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


def test_subscription_create_normalizes_endpoint_before_duplicate_check(
    client,
):
    first = create_subscription(
        client,
        endpoint="https://Hooks.Example.com:443/workspace-a/?b=2&a=1#frag",
    )
    second = create_subscription(
        client,
        endpoint="https://hooks.example.com/workspace-a?a=1&b=2",
    )
    other_workspace = create_subscription(
        client,
        workspace_id="workspace-b",
        endpoint="https://hooks.example.com/workspace-a?a=1&b=2",
    )

    assert second == first
    assert (
        first["endpoint"]
        == "https://hooks.example.com/workspace-a?a=1&b=2"
    )
    assert other_workspace["id"] != first["id"]

    response = client.get(
        "/api/v2/webhooks/subscriptions",
        headers=AUTH_HEADERS,
        params={"workspace_id": "workspace-a"},
    )
    assert response.json()["subscriptions"] == [first]


def test_disabled_normalized_endpoint_replacement_skips_duplicate_delivery(
    client,
):
    disabled = create_subscription(
        client,
        enabled=False,
        endpoint="https://hooks.example.com/workspace-a/",
    )
    replacement = create_subscription(
        client,
        endpoint="https://HOOKS.example.com:443/workspace-a",
    )

    assert replacement["id"] != disabled["id"]

    delivery = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-normalized",
            "payload": {},
        },
    )

    assert [
        record["subscription_id"]
        for record in delivery.json()["deliveries"]
    ] == [replacement["id"]]


@pytest.mark.parametrize(
    ("token", "status_code"),
    [
        ("disabled-token", 403),
        ("revoked-token", 403),
        ("expired-token", 401),
        ("viewer-token", 403),
        ("missing-scope-token", 403),
    ],
)
def test_webhook_management_rejects_invalid_principals(
    client,
    token,
    status_code,
):
    import time

    webhook_auth_guard.add_token(
        "disabled-token",
        workspaces={"workspace-a"},
        scopes={MANAGE_WEBHOOKS_SCOPE},
        role="admin",
        disabled=True,
    )
    webhook_auth_guard.add_token(
        "revoked-token",
        workspaces={"workspace-a"},
        scopes={MANAGE_WEBHOOKS_SCOPE},
        role="admin",
        revoked=True,
    )
    webhook_auth_guard.add_token(
        "expired-token",
        workspaces={"workspace-a"},
        scopes={MANAGE_WEBHOOKS_SCOPE},
        role="admin",
        expires_at=time.time() - 1,
    )
    webhook_auth_guard.add_token(
        "viewer-token",
        workspaces={"workspace-a"},
        scopes={MANAGE_WEBHOOKS_SCOPE},
        role="viewer",
    )
    webhook_auth_guard.add_token(
        "missing-scope-token",
        workspaces={"workspace-a"},
        scopes={"webhook:read"},
        role="admin",
    )

    response = client.post(
        "/api/v2/webhooks/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "workspace_id": "workspace-a",
            "endpoint": "https://hooks.example.com/workspace-a",
            "event_types": ["task.completed"],
        },
    )

    assert response.status_code == status_code
    assert webhook_service.list_subscriptions("workspace-a") == []


def test_webhook_management_rejects_anonymous_before_mutation(client):
    response = client.post(
        "/api/v2/webhooks/subscriptions",
        json={
            "workspace_id": "workspace-a",
            "endpoint": "https://hooks.example.com/workspace-a",
            "event_types": ["task.completed"],
        },
    )

    assert response.status_code == 401
    assert webhook_service.list_subscriptions("workspace-a") == []


def test_webhook_management_rejects_wrong_workspace(client):
    response = client.post(
        "/api/v2/webhooks/subscriptions",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-c",
            "endpoint": "https://hooks.example.com/workspace-c",
            "event_types": ["task.completed"],
        },
    )

    assert response.status_code == 403
    assert webhook_service.list_subscriptions("workspace-c") == []


def test_browser_session_can_manage_webhooks(client):
    client.cookies.set("ao_session", "browser-session")

    response = client.post(
        "/api/v2/webhooks/subscriptions",
        json={
            "workspace_id": "workspace-a",
            "endpoint": "https://hooks.example.com/workspace-a",
            "event_types": ["task.completed"],
        },
    )

    assert response.status_code == 201
    assert response.json()["workspace_id"] == "workspace-a"


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


def test_duplicate_delivery_id_rejects_changed_public_event(client):
    create_subscription(client)
    original = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-conflict",
            "payload": {"result": "ok"},
        },
    )
    conflict = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-conflict",
            "payload": {"result": "changed"},
        },
    )

    assert original.status_code == 200
    assert conflict.status_code == 400
    assert "delivery_id already used" in conflict.json()["detail"]

    retry = client.post(
        "/api/v2/webhooks/deliveries/delivery-conflict/retry",
        headers=AUTH_HEADERS,
        json={"workspace_id": "workspace-a"},
    )
    assert retry.json() == original.json()


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


def test_rotate_rejects_normalized_duplicate_endpoint_before_overwrite(client):
    original = create_subscription(
        client,
        endpoint="https://hooks.example.com/original",
    )
    existing = create_subscription(
        client,
        endpoint="https://hooks.example.com/target?a=1&b=2",
    )

    response = client.post(
        f"/api/v2/webhooks/subscriptions/{original['id']}/rotate",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "endpoint": "https://HOOKS.example.com:443/target/?b=2&a=1#frag",
        },
    )

    assert response.status_code == 400
    assert "endpoint already registered" in response.json()["detail"]

    delivery = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-duplicate-rotate",
            "payload": {},
        },
    )

    assert [
        record["subscription_id"]
        for record in delivery.json()["deliveries"]
    ] == [original["id"], existing["id"]]


def test_rotated_subscription_versions_delivery_idempotency(client):
    subscription = create_subscription(client)
    first = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-rotated",
            "payload": {"result": "ok"},
        },
    )
    rotated = client.post(
        f"/api/v2/webhooks/subscriptions/{subscription['id']}/rotate",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "endpoint": "https://hooks.example.com/workspace-a-v2",
        },
    )
    second = client.post(
        "/api/v2/webhooks/deliveries",
        headers=AUTH_HEADERS,
        json={
            "workspace_id": "workspace-a",
            "event_type": "task.completed",
            "delivery_id": "delivery-rotated",
            "payload": {"result": "ok"},
        },
    )

    assert first.status_code == 200
    assert rotated.status_code == 200
    assert (
        rotated.json()["endpoint"]
        == "https://hooks.example.com/workspace-a-v2"
    )
    assert "_secret_version" not in rotated.text

    assert second.status_code == 200
    assert second.json()["deliveries"] == [{
        "delivery_id": "delivery-rotated",
        "subscription_id": subscription["id"],
        "workspace_id": "workspace-a",
        "event_type": "task.completed",
        "endpoint": "https://hooks.example.com/workspace-a-v2",
        "status": "delivered",
        "attempts": 1,
    }]

    retry = client.post(
        "/api/v2/webhooks/deliveries/delivery-rotated/retry",
        headers=AUTH_HEADERS,
        json={"workspace_id": "workspace-a"},
    )
    assert {
        delivery["endpoint"]
        for delivery in retry.json()["deliveries"]
    } == {
        "https://hooks.example.com/workspace-a",
        "https://hooks.example.com/workspace-a-v2",
    }
