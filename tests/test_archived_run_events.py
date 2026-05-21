import asyncio

from src.agent.registry import AgentStatus
from src.orchestrator.engine import OrchestrationEngine


def _task(agent_id):
    return {
        "id": "task-private-123",
        "target_agent": agent_id,
        "run_id": "run-private-123",
        "run_attempt": 1,
        "run_revision": 7,
    }


def test_archived_run_event_rejected_before_hooks_or_execution():
    engine = OrchestrationEngine()
    agent_id = engine.registry.register("worker", "worker.processor")
    called = []

    async def pre_execute(task):
        called.append(task["id"])

    engine.register_hook("pre_execute", pre_execute)
    engine.register_run("run-private-123", attempt=1, revision=7)
    engine.archive_run("run-private-123")

    asyncio.run(engine._execute_task(_task(agent_id)))

    assert called == []
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PENDING.value
    audit = engine.run_event_audit()
    assert audit[0]["reason"] == "archived_run"
    assert audit[0]["task"] != "task-private-123"
    assert audit[0]["run"] != "run-private-123"


def test_stale_attempt_rejected_before_agent_state_mutation():
    engine = OrchestrationEngine()
    agent_id = engine.registry.register("worker", "worker.processor")
    engine.register_run("run-private-123", attempt=2, revision=7)

    asyncio.run(engine._execute_task(_task(agent_id)))

    assert engine.registry.get(agent_id)["status"] == AgentStatus.PENDING.value
    assert engine.run_event_audit()[0]["reason"] == "stale_attempt"


def test_matching_active_run_event_executes_normally():
    engine = OrchestrationEngine()
    agent_id = engine.registry.register("worker", "worker.processor")
    engine.register_run("run-private-123", attempt=1, revision=7)
    observed = []

    async def post_execute(task, result):
        observed.append((task["id"], result["status"]))

    engine.register_hook("post_execute", post_execute)

    asyncio.run(engine._execute_task(_task(agent_id)))

    assert observed == [("task-private-123", "completed")]
    assert engine.registry.get(agent_id)["status"] == AgentStatus.PAUSED.value
    assert engine.run_event_audit() == []
