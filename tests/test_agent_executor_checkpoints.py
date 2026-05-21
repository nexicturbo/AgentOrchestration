import asyncio

import pytest

from src.agent.executor import AgentExecutor
from src.orchestrator.checkpoints import CheckpointConflictError


def test_executor_checkpoint_retry_uses_one_logical_record():
    executor = AgentExecutor()
    task = {"id": "task-1", "attempt": 2}
    payload = {"cursor": "batch-7", "offset": 42}

    first = executor.save_checkpoint(task, "extract", payload)
    retry = executor.save_checkpoint(task, "extract", payload)

    assert first is retry
    assert first.key == "task-1/extract/2"


def test_executor_checkpoint_conflict_rejects_same_key_mismatch():
    executor = AgentExecutor()
    task = {"id": "task-1", "attempt": 0}
    executor.save_checkpoint(task, "extract", {"offset": 10})

    with pytest.raises(CheckpointConflictError):
        executor.save_checkpoint(task, "extract", {"offset": 11})


def test_executor_resume_returns_latest_step_checkpoint():
    executor = AgentExecutor()
    task = {"id": "task-1"}
    executor.save_checkpoint(task, "extract", {"offset": 10}, attempt=0)
    executor.save_checkpoint(task, "extract", {"offset": 20}, attempt=1)

    latest = executor.resume_checkpoint(task, "extract")

    assert latest is not None
    assert latest.payload == {"offset": 20}


def test_worker_handler_can_record_checkpoint_during_execution():
    executor = AgentExecutor()
    task = {"id": "task-1", "attempt": 1}

    async def handler(agent_id, task_payload):
        record = executor.save_checkpoint(
            task_payload,
            "download",
            {"bytes": 512},
        )
        return {"checkpoint": record.key, "agent": agent_id}

    execution_id = asyncio.run(executor.execute("agent-1", task, handler))
    result = executor.get_result(execution_id)

    assert result["result"]["checkpoint"] == "task-1/download/1"
    checkpoint = executor.resume_checkpoint(task, "download")

    assert checkpoint.payload == {"bytes": 512}
