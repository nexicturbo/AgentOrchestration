"""Regression tests for SDK decorator metadata exposure."""

import asyncio

from src.sdk.decorators import on_event, task


def test_task_metadata_is_attached_to_returned_wrapper():
    @task(name="sync", retries=2, timeout=7)
    async def sync_task():
        return "ok"

    assert sync_task.__task_config__ == {
        "name": "sync",
        "retries": 2,
        "timeout": 7,
    }
    assert asyncio.run(sync_task()) == "ok"


def test_task_metadata_is_visible_on_class_method_for_discovery():
    class Worker:
        @task(timeout=9)
        async def process(self):
            return "done"

    discovered = {
        name: method.__task_config__
        for name, method in Worker.__dict__.items()
        if hasattr(method, "__task_config__")
    }

    assert discovered == {
        "process": {
            "name": "process",
            "retries": 0,
            "timeout": 9,
        },
    }
    assert asyncio.run(Worker().process()) == "done"


def test_event_metadata_is_attached_to_returned_wrapper():
    @on_event("agent.started")
    async def handle_event():
        return "handled"

    assert handle_event.__event_handler__ == "agent.started"
    assert asyncio.run(handle_event()) == "handled"
