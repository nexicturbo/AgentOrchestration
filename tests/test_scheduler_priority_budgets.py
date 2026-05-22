import asyncio
import logging

from src.common.metrics import metrics
from src.orchestrator.scheduler import TaskScheduler


def test_priority_budget_defers_exhausted_urgent_lane_without_popping(caplog):
    scheduler = TaskScheduler(priority_class_limits={"urgent": 1})
    first_id = scheduler.enqueue({"type": "first"}, priority=10)
    second_id = scheduler.enqueue({"type": "second"}, priority=10)

    first = asyncio.run(scheduler.dequeue())
    assert first["id"] == first_id

    caplog.set_level(logging.WARNING, logger="src.orchestrator.scheduler")
    metric_before = metrics.snapshot()["counters"].get(
        "scheduler.priority_budget.deferred",
        0,
    )
    blocked = asyncio.run(scheduler.dequeue())
    metric_after = metrics.snapshot()["counters"].get(
        "scheduler.priority_budget.deferred",
        0,
    )

    assert blocked is None
    assert second_id not in scheduler._in_flight
    assert len(scheduler._queues["default"]) == 1
    assert scheduler.audit_records == [{
        "decision": "priority_class_budget_deferred",
        "reason": "all_ready_tasks_over_budget",
        "queue": "default",
        "in_flight_count": 1,
    }]
    assert metric_after == metric_before + 1
    assert "first" not in caplog.text
    assert "second" not in caplog.text


def test_blocked_urgent_lane_does_not_consume_standard_budget():
    scheduler = TaskScheduler(
        priority_class_limits={
            "urgent": 1,
            "standard": 1,
        }
    )
    urgent_id = scheduler.enqueue({"type": "urgent-one"}, priority=10)
    blocked_urgent_id = scheduler.enqueue({"type": "urgent-two"}, priority=10)
    standard_id = scheduler.enqueue({"type": "standard"}, priority=1)

    urgent = asyncio.run(scheduler.dequeue())
    assert urgent["id"] == urgent_id

    standard = asyncio.run(scheduler.dequeue())

    assert standard["id"] == standard_id
    assert blocked_urgent_id not in scheduler._in_flight
    assert len(scheduler._queues["default"]) == 1


def test_completion_releases_priority_class_budget():
    scheduler = TaskScheduler(priority_class_limits={"urgent": 1})
    first_id = scheduler.enqueue({"type": "first"}, priority=10)
    second_id = scheduler.enqueue({"type": "second"}, priority=10)

    first = asyncio.run(scheduler.dequeue())
    assert first["id"] == first_id
    assert asyncio.run(scheduler.dequeue()) is None

    assert scheduler.complete(first_id)
    second = asyncio.run(scheduler.dequeue())

    assert second["id"] == second_id


def test_priority_budgets_are_disabled_by_default():
    scheduler = TaskScheduler()
    first_id = scheduler.enqueue({"type": "first"}, priority=10)
    second_id = scheduler.enqueue({"type": "second"}, priority=10)

    first = asyncio.run(scheduler.dequeue())
    second = asyncio.run(scheduler.dequeue())

    assert first["id"] == first_id
    assert second["id"] == second_id
