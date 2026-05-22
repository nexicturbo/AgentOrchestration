import asyncio

import pytest

from src.agent.executor import AgentExecutor


@pytest.mark.parametrize("max_concurrent", [0, -1, -5, True, 1.5, "3"])
def test_executor_rejects_invalid_max_concurrent(max_concurrent):
    with pytest.raises(
        ValueError,
        match="max_concurrent must be a positive integer",
    ):
        AgentExecutor(max_concurrent=max_concurrent)


def test_executor_accepts_positive_max_concurrent_and_runs_task():
    executor = AgentExecutor(max_concurrent=1)

    async def handler(agent_id, task):
        return {
            "agent": agent_id,
            "task": task["id"],
        }

    execution_id = asyncio.run(
        executor.execute(
            "agent-1",
            {"id": "task-1"},
            handler,
        )
    )

    result = executor.get_result(execution_id)
    assert result["agent_id"] == "agent-1"
    assert result["task_id"] == "task-1"
    assert result["result"] == {
        "agent": "agent-1",
        "task": "task-1",
    }
