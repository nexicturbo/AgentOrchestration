import asyncio
import math

from src.agent.executor import AgentExecutor


def test_executor_stores_json_serializable_results():
    async def scenario():
        executor = AgentExecutor()

        async def handler(agent_id, task):
            return {"ok": True, "items": [1, 2, 3]}

        execution_id = await executor.execute(
            "agent-1",
            {"id": "task-1"},
            handler,
        )

        result = executor.get_result(execution_id)
        assert result["agent_id"] == "agent-1"
        assert result["task_id"] == "task-1"
        assert result["result"] == {"ok": True, "items": [1, 2, 3]}

    asyncio.run(scenario())


def test_executor_rejects_non_json_serializable_results():
    async def scenario():
        executor = AgentExecutor()

        async def handler(agent_id, task):
            return {"bad": {1, 2, 3}}

        execution_id = await executor.execute(
            "agent-1",
            {"id": "task-2"},
            handler,
        )

        result = executor.get_result(execution_id)
        assert result["execution_id"] == execution_id
        assert result["agent_id"] == "agent-1"
        assert result["task_id"] == "task-2"
        assert result["status"] == "failed"
        assert result["error"] == "result_not_json_serializable"
        assert "bad" not in result
        assert execution_id not in executor._active_tasks

    asyncio.run(scenario())


def test_executor_rejects_non_finite_json_results():
    async def scenario():
        executor = AgentExecutor()

        async def handler(agent_id, task):
            return {"metric": math.nan}

        execution_id = await executor.execute(
            "agent-1",
            {"id": "task-3"},
            handler,
        )

        result = executor.get_result(execution_id)
        assert result["status"] == "failed"
        assert result["error"] == "result_not_json_serializable"
        assert result["agent_id"] == "agent-1"
        assert result["task_id"] == "task-3"

    asyncio.run(scenario())


def test_terminal_result_storage_is_idempotent():
    executor = AgentExecutor()
    first = {
        "execution_id": "exec-1",
        "agent_id": "agent-1",
        "task_id": "task-4",
        "result": {"value": "first"},
    }
    second = {
        "execution_id": "exec-1",
        "agent_id": "agent-1",
        "task_id": "task-4",
        "result": {"value": "second"},
    }

    executor._store_terminal_result("exec-1", first)
    executor._store_terminal_result("exec-1", second)

    assert executor.get_result("exec-1") == first
