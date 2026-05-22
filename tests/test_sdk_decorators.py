import asyncio
import time

import pytest

from src.sdk.decorators import task


class TestTaskDecorator:
    def test_sync_task_return_value_is_supported(self):
        @task(name="sync-greeting")
        def greet(name):
            return f"hello {name}"

        assert asyncio.run(greet("worker")) == "hello worker"

    def test_sync_task_keyword_arguments_are_supported(self):
        @task()
        def combine(prefix, *, suffix):
            return f"{prefix}-{suffix}"

        assert asyncio.run(combine("left", suffix="right")) == "left-right"

    def test_async_task_behavior_is_preserved(self):
        @task(name="async-greeting")
        async def greet(name):
            await asyncio.sleep(0)
            return f"hello {name}"

        assert asyncio.run(greet("worker")) == "hello worker"

    def test_sync_task_exception_propagates(self):
        @task()
        def fail():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(fail())

    def test_sync_task_timeout_uses_task_name(self):
        @task(name="slow-sync", timeout=0.01)
        def slow():
            time.sleep(0.05)
            return "done"

        with pytest.raises(TimeoutError, match="slow-sync"):
            asyncio.run(slow())

    def test_task_metadata_is_preserved_on_wrapper(self):
        @task(name="metadata", retries=2, timeout=7)
        def handler():
            return "ok"

        assert handler.__task_config__ == {
            "name": "metadata",
            "retries": 2,
            "timeout": 7,
        }
