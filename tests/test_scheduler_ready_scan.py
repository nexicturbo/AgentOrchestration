import asyncio

from src.orchestrator.scheduler import TaskScheduler


class MutableClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def test_delayed_high_priority_job_does_not_preempt_ready_scan():
    clock = MutableClock()
    scheduler = TaskScheduler(clock=clock)
    delayed_id = scheduler.schedule(
        {"type": "delayed", "payload": {"token": "private"}},
        delay=30,
        priority=100,
    )
    scheduler.enqueue({"type": "ready"}, priority=1)

    task = asyncio.run(scheduler.dequeue())

    assert task["type"] == "ready"
    assert task["id"] != delayed_id


def test_delayed_job_promotes_after_ready_at_with_original_metadata():
    clock = MutableClock()
    scheduler = TaskScheduler(clock=clock)
    delayed_id = scheduler.schedule(
        {"type": "delayed", "payload": {"data": 42}},
        delay=5,
        queue="critical",
        priority=7,
    )

    assert asyncio.run(scheduler.dequeue("critical")) is None

    clock.advance(5)
    task = asyncio.run(scheduler.dequeue("critical"))

    assert task is not None
    assert task["id"] == delayed_id
    assert task["type"] == "delayed"
    assert task["payload"] == {"data": 42}
    assert task["queue"] == "critical"
    assert task["priority"] == 7
    assert task["retries"] == 0


def test_due_delayed_job_is_delivered_once_across_repeated_ready_scans():
    clock = MutableClock()
    scheduler = TaskScheduler(clock=clock)
    scheduler.schedule({"type": "delayed"}, delay=1)
    clock.advance(1)

    first = asyncio.run(scheduler.dequeue())
    second = asyncio.run(scheduler.dequeue())

    assert first is not None
    assert first["type"] == "delayed"
    assert second is None


def test_scheduler_audit_records_are_sanitized():
    clock = MutableClock()
    scheduler = TaskScheduler(clock=clock)
    delayed_id = scheduler.schedule(
        {
            "type": "delayed",
            "payload": {"secret": "do-not-log"},
            "credentials": {"api_key": "also-private"},
        },
        delay=1,
        queue="critical",
        priority=9,
    )
    clock.advance(1)

    assert asyncio.run(scheduler.dequeue("critical")) is not None

    assert scheduler.audit_records == [
        {
            "event": "scheduled_deferred",
            "task_id": delayed_id,
            "queue": "critical",
            "priority": 9,
            "reason": "ready_at_in_future",
            "timestamp": 1000.0,
        },
        {
            "event": "scheduled_promoted",
            "task_id": delayed_id,
            "queue": "critical",
            "priority": 9,
            "reason": "ready_at_reached",
            "timestamp": 1001.0,
        },
    ]
    assert "do-not-log" not in str(scheduler.audit_records)
    assert "also-private" not in str(scheduler.audit_records)
