import pytest

from src.orchestrator.webhook import (
    WebhookDeliveryError,
    WebhookDeliveryService,
    WebhookEndpoint,
)


def endpoint(**overrides):
    values = {
        "endpoint_id": "endpoint-1",
        "workspace_id": "workspace-a",
        "url": "https://hooks.example.test/events",
        "secret_version": 2,
        "enabled": True,
    }
    values.update(overrides)
    return WebhookEndpoint(**values)


def event_payload():
    return {
        "event_id": "run-1",
        "event_type": "run.completed",
        "workspace_id": "workspace-a",
        "data": {
            "status": "completed",
            "run_metadata": {"worker_id": "worker-7"},
            "steps": [
                {"name": "fetch", "trace_id": "trace-1", "result": "ok"},
                {"name": "emit", "_internal_state": "hidden"},
            ],
        },
        "debug": {"queue": "private"},
        "operator_token": "secret-token",
    }


def test_delivery_shapes_public_payload_before_transport():
    deliveries = []
    service = WebhookDeliveryService(
        transport=lambda target, payload: deliveries.append((target, payload))
    )
    service.register_endpoint(endpoint())

    record = service.deliver_event(
        "endpoint-1",
        "workspace-a",
        event_payload(),
        secret_version=2,
    )

    assert record.status == "delivered"
    assert record.attempts == 1
    assert len(deliveries) == 1
    target, payload = deliveries[0]
    assert target.url == "https://hooks.example.test/events"
    assert payload == record.payload
    assert payload["event_id"] == "run-1"
    assert payload["data"]["status"] == "completed"
    assert payload["data"]["steps"][0] == {"name": "fetch", "result": "ok"}
    assert payload["data"]["steps"][1] == {"name": "emit"}
    assert "debug" not in payload
    assert "operator_token" not in payload
    assert "run_metadata" not in payload["data"]


def test_rejects_unsafe_or_disabled_endpoints_before_delivery():
    deliveries = []
    service = WebhookDeliveryService(
        transport=lambda target, payload: deliveries.append((target, payload))
    )

    with pytest.raises(WebhookDeliveryError, match="HTTPS"):
        service.register_endpoint(
            endpoint(url="http://hooks.example.test/events")
        )

    service.register_endpoint(endpoint(enabled=False))
    with pytest.raises(WebhookDeliveryError, match="disabled"):
        service.deliver_event("endpoint-1", "workspace-a", event_payload())

    assert deliveries == []


def test_rejects_rotated_or_cross_workspace_delivery_before_transport():
    deliveries = []
    service = WebhookDeliveryService(
        transport=lambda target, payload: deliveries.append((target, payload))
    )
    service.register_endpoint(endpoint())

    with pytest.raises(WebhookDeliveryError, match="rotated"):
        service.deliver_event(
            "endpoint-1",
            "workspace-a",
            event_payload(),
            secret_version=1,
        )

    with pytest.raises(WebhookDeliveryError, match="another workspace"):
        service.deliver_event("endpoint-1", "workspace-b", event_payload())

    assert deliveries == []


def test_delivery_is_idempotent_for_repeated_delivery_key():
    deliveries = []
    service = WebhookDeliveryService(
        transport=lambda target, payload: deliveries.append((target, payload))
    )
    service.register_endpoint(endpoint())

    first = service.deliver_event(
        "endpoint-1",
        "workspace-a",
        event_payload(),
        idempotency_key="run-1",
    )
    second = service.deliver_event(
        "endpoint-1",
        "workspace-a",
        {"event_id": "run-1", "debug": "late leak"},
        idempotency_key="run-1",
    )

    assert second is first
    assert first.status == "delivered"
    assert first.attempts == 1
    assert len(deliveries) == 1
    assert "debug" not in first.payload


def test_failed_delivery_retries_same_shaped_public_payload():
    calls = []

    def flaky_transport(target, payload):
        calls.append(payload)
        if len(calls) == 1:
            raise RuntimeError("temporary outage")

    service = WebhookDeliveryService(transport=flaky_transport)
    service.register_endpoint(endpoint())

    record = service.deliver_event(
        "endpoint-1",
        "workspace-a",
        event_payload(),
    )
    assert record.status == "failed"
    assert record.attempts == 1
    assert "run_metadata" not in record.payload["data"]

    retried = service.retry_delivery(record.delivery_id)

    assert retried is record
    assert record.status == "delivered"
    assert record.attempts == 2
    assert calls[0] == calls[1] == record.payload
