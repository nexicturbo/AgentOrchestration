import asyncio

import pytest

from src.agent.executor import AgentExecutor


@pytest.mark.parametrize("max_concurrent", [0, -1, -5, True, False, 1.5, "2"])
def test_executor_rejects_invalid_max_concurrent(max_concurrent):
    with pytest.raises(ValueError, match="positive integer"):
        AgentExecutor(max_concurrent=max_concurrent)


@pytest.mark.parametrize("max_concurrent", [1, 2, 5])
def test_executor_accepts_positive_integer_max_concurrent(max_concurrent):
    executor = AgentExecutor(max_concurrent=max_concurrent)

    assert executor.max_concurrent == max_concurrent


def test_executor_uses_default_positive_concurrency():
    executor = AgentExecutor()

    assert executor.max_concurrent == 5


def test_executor_positive_concurrency_still_executes_task():
    async def handler(agent_id, task):
        return {"handled": agent_id, "task": task["id"]}

    async def run():
        executor = AgentExecutor(max_concurrent=1)

        execution_id = await executor.execute(
            "agent-1",
            {"id": "task-1"},
            handler,
        )

        assert executor.get_result(execution_id)["result"] == {
            "handled": "agent-1",
            "task": "task-1",
        }

    asyncio.run(run())
