from src.api.webhooks import WebhookDispatcher


def test_valid_delivery_sanitizes_callback_payload():
    dispatcher = WebhookDispatcher()
    dispatcher.register_endpoint("endpoint-1", "workspace-a", "https://hook")
    received = []

    record = dispatcher.deliver(
        endpoint_id="endpoint-1",
        workspace_id="workspace-a",
        event_id="event-1",
        payload={
            "type": "task.created",
            "_run_id": "internal",
            "internal_trace": "secret",
        },
        callback=lambda payload: received.append(payload) or True,
    )

    assert record.status == "delivered"
    assert received == [{"type": "task.created"}]
    assert "_run_id" not in record.payload
    assert "internal_trace" not in record.payload


def test_retry_with_same_idempotency_key_does_not_duplicate_callback():
    dispatcher = WebhookDispatcher()
    dispatcher.register_endpoint("endpoint-1", "workspace-a", "https://hook")
    calls = []

    first = dispatcher.deliver(
        endpoint_id="endpoint-1",
        workspace_id="workspace-a",
        event_id="event-1",
        idempotency_key="delivery-key",
        payload={"type": "task.created"},
        callback=lambda payload: calls.append(payload) or True,
    )
    retry = dispatcher.deliver(
        endpoint_id="endpoint-1",
        workspace_id="workspace-a",
        event_id="event-1",
        idempotency_key="delivery-key",
        payload={"type": "task.created", "_secret": "do-not-send"},
        callback=lambda payload: calls.append(payload) or True,
    )

    assert retry == first
    assert calls == [{"type": "task.created"}]


def test_disabled_endpoint_rejects_delivery_without_callback():
    dispatcher = WebhookDispatcher()
    dispatcher.register_endpoint("endpoint-1", "workspace-a", "https://hook")
    dispatcher.disable_endpoint("endpoint-1")
    calls = []

    record = dispatcher.deliver(
        endpoint_id="endpoint-1",
        workspace_id="workspace-a",
        event_id="event-1",
        payload={"type": "task.created"},
        callback=lambda payload: calls.append(payload) or True,
    )

    assert record.status == "rejected"
    assert record.reason == "endpoint disabled"
    assert calls == []


def test_workspace_mismatch_rejects_delivery_without_callback():
    dispatcher = WebhookDispatcher()
    dispatcher.register_endpoint("endpoint-1", "workspace-a", "https://hook")
    calls = []

    record = dispatcher.deliver(
        endpoint_id="endpoint-1",
        workspace_id="workspace-b",
        event_id="event-1",
        payload={"type": "task.created"},
        callback=lambda payload: calls.append(payload) or True,
    )

    assert record.status == "rejected"
    assert record.reason == "endpoint workspace mismatch"
    assert calls == []


def test_rotated_endpoint_secret_rejects_stale_delivery():
    dispatcher = WebhookDispatcher()
    dispatcher.register_endpoint("endpoint-1", "workspace-a", "https://hook")
    dispatcher.rotate_endpoint_secret("endpoint-1")

    record = dispatcher.deliver(
        endpoint_id="endpoint-1",
        workspace_id="workspace-a",
        event_id="event-1",
        secret_version=1,
        payload={"type": "task.created"},
        callback=lambda payload: True,
    )

    assert record.status == "rejected"
    assert record.reason == "endpoint secret rotated"
