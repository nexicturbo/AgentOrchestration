import asyncio

import pytest

from src.orchestrator.scheduler import (
    ReconciliationScheduler,
    TaskScheduler,
)


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def advance(self, seconds):
        self.now += seconds

    def __call__(self):
        return self.now


def test_startup_stagger_defers_reconcile_without_queue_mutation():
    clock = Clock()
    scheduler = TaskScheduler()
    guard = ReconciliationScheduler(
        scheduler,
        node_id="worker-a",
        startup_stagger_window=30,
        now_fn=clock,
    )

    decision = guard.request_reconcile({"payload": "private"})

    assert decision["accepted"] is False
    assert decision["reason"] == "startup_stagger_active"
    assert asyncio.run(scheduler.dequeue("maintenance")) is None
    assert "payload" not in guard.audit_records()[0]


def test_reconcile_is_enqueued_after_node_specific_stagger():
    clock = Clock()
    scheduler = TaskScheduler()
    guard = ReconciliationScheduler(
        scheduler,
        node_id="worker-a",
        startup_stagger_window=30,
        now_fn=clock,
    )

    clock.now = guard.startup_at + guard.stagger_offset
    decision = guard.request_reconcile({"scope": "runs"}, priority=9)
    task = asyncio.run(scheduler.dequeue("maintenance"))

    assert decision["accepted"] is True
    assert decision["reason"] == "accepted"
    assert task["type"] == "periodic_reconciliation"
    assert task["node_id"] == "worker-a"
    assert task["generation"] == 1
    assert task["scope"] == "runs"


def test_duplicate_reconcile_is_rejected_until_interval_elapses():
    clock = Clock()
    scheduler = TaskScheduler()
    guard = ReconciliationScheduler(
        scheduler,
        node_id="worker-a",
        base_interval=60,
        startup_stagger_window=0,
        now_fn=clock,
    )

    first = guard.request_reconcile()
    duplicate = guard.request_reconcile()

    assert first["accepted"] is True
    assert duplicate["accepted"] is False
    assert duplicate["reason"] == "reconcile_interval_active"
    assert len(scheduler._queues["maintenance"]) == 1


def test_next_reconcile_advances_generation_after_interval():
    clock = Clock()
    scheduler = TaskScheduler()
    guard = ReconciliationScheduler(
        scheduler,
        node_id="worker-a",
        base_interval=60,
        startup_stagger_window=0,
        now_fn=clock,
    )

    guard.request_reconcile()
    clock.advance(60)
    second = guard.request_reconcile()

    assert second["accepted"] is True
    assert second["generation"] == 2
    first_task = asyncio.run(scheduler.dequeue("maintenance"))
    second_task = asyncio.run(scheduler.dequeue("maintenance"))
    assert first_task["generation"] == 1
    assert second_task["generation"] == 2


def test_stagger_offset_is_deterministic_per_node():
    first = ReconciliationScheduler(
        TaskScheduler(),
        node_id="worker-a",
        startup_stagger_window=30,
    )
    second = ReconciliationScheduler(
        TaskScheduler(),
        node_id="worker-a",
        startup_stagger_window=30,
    )
    other = ReconciliationScheduler(
        TaskScheduler(),
        node_id="worker-b",
        startup_stagger_window=30,
    )

    assert first.stagger_offset == second.stagger_offset
    assert first.stagger_offset != other.stagger_offset
    assert 0 <= first.stagger_offset <= 30


def test_audit_records_are_bounded_and_sanitized():
    clock = Clock()
    guard = ReconciliationScheduler(
        TaskScheduler(),
        node_id="worker-a",
        startup_stagger_window=30,
        now_fn=clock,
        max_audit_records=2,
    )

    guard.request_reconcile({"secret": "do-not-record"})
    guard.request_reconcile({"secret": "do-not-record"})
    guard.request_reconcile({"secret": "do-not-record"})

    records = guard.audit_records()
    assert len(records) == 2
    assert all("secret" not in record for record in records)


def test_invalid_reconciliation_settings_fail_fast():
    with pytest.raises(ValueError, match="base_interval"):
        ReconciliationScheduler(TaskScheduler(), "worker-a", base_interval=0)
    with pytest.raises(ValueError, match="startup_stagger_window"):
        ReconciliationScheduler(
            TaskScheduler(),
            "worker-a",
            startup_stagger_window=-1,
        )
    with pytest.raises(ValueError, match="max_audit_records"):
        ReconciliationScheduler(
            TaskScheduler(),
            "worker-a",
            max_audit_records=0,
        )
