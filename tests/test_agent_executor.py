import asyncio

import pytest

from src.agent.executor import AgentExecutor


def test_cancel_stores_terminal_result_for_polling_clients():
    async def scenario():
        executor = AgentExecutor()
        started = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await asyncio.Event().wait()

        execute_task = asyncio.create_task(
            executor.execute("agent-1", {"id": "task-1"}, handler)
        )
        await started.wait()
        execution_id = next(iter(executor._active_tasks))

        assert executor.cancel(execution_id)
        assert_cancelled_result(
            executor.get_result(execution_id),
            execution_id,
            "agent-1",
            "task-1",
        )

        with pytest.raises(asyncio.CancelledError):
            await execute_task
        assert execution_id not in executor._active_tasks

    asyncio.run(scenario())


def test_outer_execute_cancellation_stores_terminal_result():
    async def scenario():
        executor = AgentExecutor()
        started = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await asyncio.Event().wait()

        execute_task = asyncio.create_task(
            executor.execute("agent-1", {"id": "task-2"}, handler)
        )
        await started.wait()
        execution_id = next(iter(executor._active_tasks))

        execute_task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await execute_task
        assert_cancelled_result(
            executor.get_result(execution_id),
            execution_id,
            "agent-1",
            "task-2",
        )
        assert execution_id not in executor._active_tasks

    asyncio.run(scenario())


def test_shutdown_stores_cancelled_results_for_active_tasks():
    async def scenario():
        executor = AgentExecutor()
        started = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await asyncio.Event().wait()

        execute_task = asyncio.create_task(
            executor.execute("agent-1", {"id": "task-3"}, handler)
        )
        await started.wait()
        execution_id = next(iter(executor._active_tasks))

        await executor.shutdown()

        with pytest.raises(asyncio.CancelledError):
            await execute_task
        assert_cancelled_result(
            executor.get_result(execution_id),
            execution_id,
            "agent-1",
            "task-3",
        )

    asyncio.run(scenario())


def test_cancel_unknown_execution_returns_false():
    executor = AgentExecutor()

    assert executor.cancel("missing") is False
    assert executor.get_result("missing") is None


def assert_cancelled_result(result, execution_id, agent_id, task_id):
    assert result["execution_id"] == execution_id
    assert result["agent_id"] == agent_id
    assert result["task_id"] == task_id
    assert result["status"] == "cancelled"
    assert result["result"] is None
    assert result["cancelled"] is True
    assert isinstance(result["timestamp"], float)
