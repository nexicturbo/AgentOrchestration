"""Exception tracking sanitization tests."""

import asyncio
import json
import logging

from src.common.exception_tracking import (
    build_exception_event,
    sanitize_exception_context,
)
from src.common.logging import StructuredFormatter
from src.orchestrator.engine import OrchestrationEngine


def test_sanitizer_drops_nested_payloads_and_preserves_lookup_fields():
    event = sanitize_exception_context(
        {
            "task_id": "task-1",
            "payload": {"token": "secret-token", "user": "ada"},
            "request": {"body": "raw-request"},
            "nested": {
                "error_class": "ValueError",
                "locals": {"password": "secret"},
                "agent_id": "agent-1",
            },
        },
    )

    assert event == {
        "task_id": "task-1",
        "error_class": "ValueError",
        "agent_id": "agent-1",
    }
    assert "secret-token" not in json.dumps(event)
    assert "raw-request" not in json.dumps(event)


def test_sanitizer_overrides_error_class_from_exception():
    event = build_exception_event(
        RuntimeError("payload password should not appear"),
        {"task_id": "task-1", "error_class": "ValueError"},
    )

    assert event == {"task_id": "task-1", "error_class": "RuntimeError"}
    assert "payload password" not in json.dumps(event)


def test_structured_formatter_sanitizes_exception_context_extra():
    record = logging.LogRecord(
        "test",
        logging.ERROR,
        __file__,
        1,
        "failed",
        args=(),
        exc_info=None,
    )
    record.exception_context = {
        "task_id": "task-1",
        "payload": {"secret": "raw"},
        "locals": {"token": "token"},
    }

    output = json.loads(StructuredFormatter().format(record))

    assert output["exception_context"] == {"task_id": "task-1"}
    assert "raw" not in json.dumps(output)
    assert "token" not in json.dumps(output)


def test_engine_on_error_hook_receives_sanitized_event():
    engine = OrchestrationEngine()
    events = []
    task = {
        "id": "task-1",
        "target_agent": "missing-agent",
        "payload": {"secret": "raw-payload"},
    }

    async def on_error(event):
        events.append(event)

    engine.register_hook("on_error", on_error)

    asyncio.run(engine._execute_task(task))

    assert events == [
        {
            "task_id": "task-1",
            "agent_id": "missing-agent",
            "error_class": "ValueError",
        }
    ]
    assert "raw-payload" not in json.dumps(events)
