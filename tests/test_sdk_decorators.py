import asyncio

import pytest

from src.sdk.decorators import on_event


def test_on_event_rejects_empty_event_type():
    with pytest.raises(
        ValueError,
        match="event_type must be a non-empty string",
    ):
        on_event("")


def test_on_event_rejects_whitespace_event_type():
    with pytest.raises(
        ValueError,
        match="event_type must be a non-empty string",
    ):
        on_event("   ")


def test_on_event_rejects_tab_newline_event_type():
    with pytest.raises(
        ValueError,
        match="event_type must be a non-empty string",
    ):
        on_event("\t\n")


def test_on_event_rejects_non_string_event_type():
    with pytest.raises(
        ValueError,
        match="event_type must be a non-empty string",
    ):
        on_event(None)


def test_on_event_marks_valid_event_handler():
    @on_event("workflow.completed")
    async def handle_event(payload):
        return payload["id"]

    assert handle_event.__event_handler__ == "workflow.completed"


def test_on_event_normalizes_surrounding_whitespace():
    @on_event("  workflow.completed  ")
    async def handle_event(payload):
        return payload["id"]

    assert handle_event.__event_handler__ == "workflow.completed"


def test_on_event_wrapper_preserves_handler_result():
    @on_event("workflow.completed")
    async def handle_event(payload):
        return {"seen": payload["id"]}

    assert asyncio.run(handle_event({"id": "run-123"})) == {"seen": "run-123"}
