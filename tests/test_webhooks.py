import pytest

from src.orchestrator.webhooks import (
    WebhookManager,
    WebhookValidationError,
    validate_endpoint_url,
)


def test_register_rejects_localhost_before_persisting_endpoint():
    manager = WebhookManager()

    with pytest.raises(WebhookValidationError):
        manager.register_endpoint("workspace-a", "http://localhost/callback")

    assert manager._endpoints == {}


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/callback",
        "http://[::1]/callback",
        "http://10.0.0.12/callback",
        "ftp://hooks.example.com/callback",
        "https://token:secret@hooks.example.com/callback",
    ],
)
def test_endpoint_url_validation_rejects_unsafe_targets(url):
    with pytest.raises(WebhookValidationError):
        validate_endpoint_url(url)


def test_register_allows_localhost_only_when_explicitly_enabled():
    manager = WebhookManager()

    endpoint = manager.register_endpoint(
        "workspace-a",
        "http://127.0.0.1:8080/callback",
        allow_localhost=True,
    )

    assert endpoint.url == "http://127.0.0.1:8080/callback"
    assert endpoint.allow_localhost is True


def test_valid_delivery_dispatches_public_payload_once():
    dispatched = []

    def dispatcher(endpoint, payload):
        dispatched.append((endpoint.url, dict(payload)))
        return {"status": 202}

    manager = WebhookManager(dispatcher=dispatcher)
    endpoint = manager.register_endpoint(
        "workspace-a",
        "https://hooks.example.com/callback",
    )

    first = manager.deliver(
        "workspace-a",
        endpoint.id,
        "event-1",
        {
            "event": "agent.completed",
            "worker": {"host": "internal-runner"},
            "nested": {"ok": True, "debug": "raw-trace"},
            "items": [{"value": 1, "token": "secret"}],
        },
    )
    retry = manager.deliver(
        "workspace-a",
        endpoint.id,
        "event-1",
        {"event": "agent.completed", "worker": "different"},
    )

    assert retry is first
    assert first.status == "delivered"
    assert first.attempts == 1
    assert dispatched == [
        (
            "https://hooks.example.com/callback",
            {
                "event": "agent.completed",
                "nested": {"ok": True},
                "items": [{"value": 1}],
            },
        )
    ]


def test_delivery_rejects_cross_workspace_before_recording():
    manager = WebhookManager()
    endpoint = manager.register_endpoint(
        "workspace-a",
        "https://hooks.example.com/callback",
    )

    with pytest.raises(WebhookValidationError):
        manager.deliver(
            "workspace-b",
            endpoint.id,
            "event-1",
            {"event": "agent.completed"},
        )

    assert manager._deliveries == {}


def test_delivery_rejects_disabled_endpoint_before_recording():
    manager = WebhookManager()
    endpoint = manager.register_endpoint(
        "workspace-a",
        "https://hooks.example.com/callback",
    )
    manager.set_endpoint_enabled(endpoint.id, False)

    with pytest.raises(WebhookValidationError):
        manager.deliver(
            "workspace-a",
            endpoint.id,
            "event-1",
            {"event": "agent.completed"},
        )

    assert manager._deliveries == {}


def test_delivery_revalidates_rotated_endpoint_before_recording():
    manager = WebhookManager()
    endpoint = manager.register_endpoint(
        "workspace-a",
        "https://hooks.example.com/callback",
    )
    endpoint.url = "http://localhost/callback"

    with pytest.raises(WebhookValidationError):
        manager.deliver(
            "workspace-a",
            endpoint.id,
            "event-1",
            {"event": "agent.completed"},
        )

    assert manager._deliveries == {}
