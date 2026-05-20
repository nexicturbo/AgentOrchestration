import asyncio

from src.agent.executor import AgentExecutor


async def _wait_for_execution_id(executor):
    for _ in range(100):
        if executor._active_tasks:
            return next(iter(executor._active_tasks))
        await asyncio.sleep(0.001)
    raise AssertionError("execution did not start")


def test_cancel_records_terminal_failure_before_task_finishes():
    async def scenario():
        executor = AgentExecutor()
        started = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await asyncio.sleep(30)

        execute_task = asyncio.create_task(
            executor.execute("agent-1", {"id": "task-1"}, handler)
        )
        await started.wait()
        execution_id = await _wait_for_execution_id(executor)

        assert executor.cancel(execution_id, reason="user_cancelled")
        returned_execution_id = await execute_task

        assert returned_execution_id == execution_id
        assert executor._active_tasks == {}
        assert executor.get_result(execution_id)["status"] == "cancelled"
        assert executor.get_result(execution_id)["error"] == "user_cancelled"
        assert executor.get_result(execution_id)["agent_id"] == "agent-1"
        assert executor.get_result(execution_id)["task_id"] == "task-1"

    asyncio.run(scenario())


def test_shutdown_records_failure_reason_once_for_active_worker():
    async def scenario():
        executor = AgentExecutor()
        started = asyncio.Event()

        async def handler(agent_id, task):
            started.set()
            await asyncio.sleep(30)

        execute_task = asyncio.create_task(
            executor.execute("agent-2", {"id": "task-2"}, handler)
        )
        await started.wait()
        execution_id = await _wait_for_execution_id(executor)

        await executor.shutdown()
        returned_execution_id = await execute_task

        result = executor.get_result(execution_id)
        assert returned_execution_id == execution_id
        assert executor._active_tasks == {}
        assert result["status"] == "cancelled"
        assert result["error"] == "worker_shutdown"
        assert result["agent_id"] == "agent-2"
        assert result["task_id"] == "task-2"

        executor._record_cancelled(execution_id, "late_retry")
        assert executor.get_result(execution_id) == result

    asyncio.run(scenario())
