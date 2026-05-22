import asyncio
import time

from src.agent.executor import AgentExecutor


def test_execute_returns_execution_id_before_long_handler_finishes():
    asyncio.run(_exercise_immediate_execution_id())


async def _exercise_immediate_execution_id():
    executor = AgentExecutor()
    started = asyncio.Event()
    release = asyncio.Event()
    finished = False

    async def handler(agent_id, task):
        nonlocal finished
        started.set()
        await release.wait()
        finished = True
        return {"ok": True}

    start = time.perf_counter()
    execution_id = await executor.execute(
        "agent-1",
        {"id": "task-1"},
        handler,
    )
    elapsed = time.perf_counter() - start

    await asyncio.wait_for(started.wait(), timeout=0.2)
    assert execution_id in executor._active_tasks
    assert elapsed < 0.05
    assert finished is False
    assert executor.get_result(execution_id) is None

    release.set()
    await asyncio.wait_for(_result_ready(executor, execution_id), timeout=0.5)

    result = executor.get_result(execution_id)
    assert result["execution_id"] == execution_id
    assert result["result"] == {"ok": True}
    assert execution_id not in executor._active_tasks


def test_background_execution_still_respects_concurrency_limit():
    asyncio.run(_exercise_background_concurrency_limit())


async def _exercise_background_concurrency_limit():
    executor = AgentExecutor(max_concurrent=1)
    first_release = asyncio.Event()
    second_started = asyncio.Event()

    async def first_handler(agent_id, task):
        await first_release.wait()
        return "first"

    async def second_handler(agent_id, task):
        second_started.set()
        return "second"

    first_id = await executor.execute(
        "agent-1",
        {"id": "first"},
        first_handler,
    )
    second_id = await executor.execute(
        "agent-1",
        {"id": "second"},
        second_handler,
    )

    await asyncio.sleep(0.05)
    assert second_started.is_set() is False
    assert executor.get_result(first_id) is None
    assert executor.get_result(second_id) is None

    first_release.set()
    await asyncio.wait_for(_result_ready(executor, first_id), timeout=0.5)
    await asyncio.wait_for(_result_ready(executor, second_id), timeout=0.5)

    assert executor.get_result(first_id)["result"] == "first"
    assert executor.get_result(second_id)["result"] == "second"


def test_cancel_active_background_execution_records_cancelled_result():
    asyncio.run(_exercise_background_cancel())


async def _exercise_background_cancel():
    executor = AgentExecutor()
    started = asyncio.Event()

    async def handler(agent_id, task):
        started.set()
        await asyncio.Event().wait()

    execution_id = await executor.execute("agent-1", {"id": "task-1"}, handler)
    await asyncio.wait_for(started.wait(), timeout=0.2)

    assert executor.cancel(execution_id) is True
    await asyncio.wait_for(_result_ready(executor, execution_id), timeout=0.5)

    assert executor.get_result(execution_id) == {"error": "cancelled"}
    assert execution_id not in executor._active_tasks


async def _result_ready(executor, execution_id):
    while executor.get_result(execution_id) is None:
        await asyncio.sleep(0.001)
