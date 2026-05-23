import asyncio
import math

import pytest

from src.sdk.decorators import task


@pytest.mark.parametrize(
    "bad_timeout",
    [0, -1, -0.5, False, "1", None, math.inf],
)
def test_task_rejects_invalid_timeout_when_decorator_is_created(bad_timeout):
    with pytest.raises(ValueError, match="positive number"):
        task(timeout=bad_timeout)


def test_task_preserves_valid_timeout_metadata():
    @task(name="quick", retries=2, timeout=0.5)
    async def quick_task():
        return "ok"

    assert quick_task.__task_config__ == {
        "name": "quick",
        "retries": 2,
        "timeout": 0.5,
    }
    assert asyncio.run(quick_task()) == "ok"


def test_task_validated_timeout_still_bounds_runtime_execution():
    @task(timeout=0.01)
    async def slow_task():
        await asyncio.sleep(0.05)

    with pytest.raises(TimeoutError, match="timed out after 0.01s"):
        asyncio.run(slow_task())
