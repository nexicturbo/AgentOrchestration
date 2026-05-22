import asyncio

import pytest

from src.agent.executor import AgentExecutor


async def successful_handler(agent_id, task):
    return {"agent_id": agent_id, "task_id": task["id"]}


async def failing_handler(agent_id, task):
    raise RuntimeError(f"failed {task['id']}")


class TestAgentExecutor:
    def test_completed_results_are_bounded_by_max_results(self):
        executor = AgentExecutor(max_results=2)

        first = asyncio.run(
            executor.execute("agent-1", {"id": "task-1"}, successful_handler)
        )
        second = asyncio.run(
            executor.execute("agent-1", {"id": "task-2"}, successful_handler)
        )
        third = asyncio.run(
            executor.execute("agent-1", {"id": "task-3"}, successful_handler)
        )

        assert executor.get_result(first) is None
        assert executor.get_result(second)["task_id"] == "task-2"
        assert executor.get_result(third)["task_id"] == "task-3"
        assert len(executor._results) == 2

    def test_failed_results_are_also_bounded(self):
        executor = AgentExecutor(max_results=1)

        successful = asyncio.run(
            executor.execute("agent-1", {"id": "task-1"}, successful_handler)
        )
        failed = asyncio.run(
            executor.execute("agent-1", {"id": "task-2"}, failing_handler)
        )

        assert executor.get_result(successful) is None
        assert executor.get_result(failed) == {"error": "failed task-2"}
        assert len(executor._results) == 1

    def test_result_ttl_expires_stored_results_on_lookup(self):
        executor = AgentExecutor(max_results=10, result_ttl_seconds=0)

        execution_id = asyncio.run(
            executor.execute("agent-1", {"id": "task-1"}, successful_handler)
        )

        assert executor.get_result(execution_id) is None
        assert executor._results == {}
        assert executor._result_stored_at == {}

    def test_invalid_result_retention_limits_are_rejected(self):
        with pytest.raises(ValueError, match="max_results"):
            AgentExecutor(max_results=0)

        with pytest.raises(ValueError, match="result_ttl_seconds"):
            AgentExecutor(result_ttl_seconds=-1)
