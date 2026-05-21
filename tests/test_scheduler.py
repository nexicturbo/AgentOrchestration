import asyncio

from src.orchestrator.scheduler import TaskScheduler


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_dequeue_defers_task_when_tenant_capacity_is_full(self):
        scheduler = TaskScheduler(max_concurrent_per_tenant=1)
        first_id = scheduler.enqueue({"type": "run", "tenant_id": "tenant-a"})
        second_id = scheduler.enqueue({"type": "run", "tenant_id": "tenant-a"})

        first_task = asyncio.run(scheduler.dequeue())
        blocked_task = asyncio.run(scheduler.dequeue())

        assert first_task["id"] == first_id
        assert blocked_task is None
        assert second_id not in scheduler._in_flight
        assert scheduler.audit_log[-1] == {
            "decision": "deferred",
            "reason": "tenant_concurrency_limit",
            "source": "queued_dispatch",
            "task_id": second_id,
            "tenant_id": "tenant-a",
            "tenant_in_flight": 1,
            "tenant_limit": 1,
            "queue": "default",
        }

        assert scheduler.complete(first_id)
        second_task = asyncio.run(scheduler.dequeue())
        assert second_task["id"] == second_id

    def test_dequeue_skips_blocked_tenant_and_dispatches_available_work(self):
        scheduler = TaskScheduler(max_concurrent_per_tenant=1)
        scheduler._in_flight["active-a"] = {
            "id": "active-a",
            "type": "run",
            "tenant_id": "tenant-a",
        }
        blocked_id = scheduler.enqueue(
            {"type": "run", "tenant_id": "tenant-a"}
        )
        available_id = scheduler.enqueue(
            {"type": "run", "tenant_id": "tenant-b"}
        )

        available_task = asyncio.run(scheduler.dequeue())

        assert available_task["id"] == available_id
        assert blocked_id not in scheduler._in_flight
        assert scheduler.audit_log[-2]["decision"] == "deferred"
        assert scheduler.audit_log[-2]["source"] == "queued_dispatch"
        assert scheduler.audit_log[-2]["task_id"] == blocked_id
        assert scheduler.audit_log[-1]["decision"] == "dispatched"
        assert scheduler.audit_log[-1]["task_id"] == available_id

        assert scheduler.complete("active-a")
        blocked_task = asyncio.run(scheduler.dequeue())
        assert blocked_task["id"] == blocked_id

    def test_recovery_defers_over_capacity_tenant_tasks(self):
        scheduler = TaskScheduler(max_concurrent_per_tenant=1)
        recovered = [
            {
                "id": "run-1",
                "type": "run",
                "tenant_id": "tenant-a",
                "state": "running",
            },
            {
                "id": "run-2",
                "type": "run",
                "tenant_id": "tenant-a",
                "state": "running",
            },
        ]

        result = scheduler.recover_in_flight(recovered)

        assert result == {
            "accepted": ["run-1"],
            "deferred": ["run-2"],
            "skipped": [],
        }
        assert scheduler._in_flight["run-1"] is recovered[0]
        assert scheduler._recovery_deferred["run-2"] is recovered[1]
        assert recovered[1]["state"] == "running"
        assert recovered[1]["recovery_state"] == "deferred"
        assert recovered[1]["deferred_reason"] == "tenant_concurrency_limit"
        assert "payload" not in scheduler.audit_log[-1]
        assert scheduler.audit_log[-1] == {
            "decision": "deferred",
            "reason": "tenant_concurrency_limit",
            "source": "restart_recovery",
            "task_id": "run-2",
            "tenant_id": "tenant-a",
            "tenant_in_flight": 1,
            "tenant_limit": 1,
            "queue": "default",
        }

    def test_recovery_counts_existing_in_flight_tenant_capacity(self):
        scheduler = TaskScheduler(max_concurrent_per_tenant=2)
        scheduler._in_flight["active-1"] = {
            "id": "active-1",
            "type": "run",
            "tenant_id": "tenant-a",
            "state": "running",
        }
        recovered = [
            {"id": "run-1", "type": "run", "tenant_id": "tenant-a"},
            {"id": "run-2", "type": "run", "tenant_id": "tenant-a"},
        ]

        result = scheduler.recover_in_flight(recovered)

        assert result == {
            "accepted": ["run-1"],
            "deferred": ["run-2"],
            "skipped": [],
        }
        assert set(scheduler._in_flight) == {"active-1", "run-1"}
        assert scheduler._recovery_deferred["run-2"] is recovered[1]
        assert scheduler.audit_log[-1]["tenant_in_flight"] == 2

    def test_recovery_skips_duplicate_in_flight_task_id(self):
        scheduler = TaskScheduler(max_concurrent_per_tenant=2)
        active = {
            "id": "active-1",
            "type": "run",
            "tenant_id": "tenant-a",
            "payload": {"secret": "do-not-copy"},
        }
        scheduler._in_flight["active-1"] = active

        result = scheduler.recover_in_flight([dict(active)])

        assert result == {
            "accepted": [],
            "deferred": [],
            "skipped": ["active-1"],
        }
        assert scheduler._in_flight["active-1"] is active
        assert scheduler._recovery_deferred == {}
        assert scheduler.audit_log[-1] == {
            "decision": "skipped",
            "reason": "duplicate_recovery_task",
            "source": "restart_recovery",
            "task_id": "active-1",
            "tenant_id": "tenant-a",
            "tenant_in_flight": 1,
            "tenant_limit": 2,
            "queue": "default",
        }

# 2019-01-09T19:07:03 update

# 2019-02-18T12:30:02 update

# 2019-04-11T16:04:51 update

# 2019-04-17T16:25:46 update

# 2019-05-24T19:32:13 update

# 2019-07-02T12:54:25 update

# 2019-07-03T20:37:00 update

# 2019-08-21T19:37:17 update

# 2019-10-18T10:30:31 update

# 2019-10-25T09:01:38 update

# 2019-10-29T12:59:34 update

# 2019-11-05T10:07:06 update

# 2019-11-11T10:43:52 update

# 2020-01-17T13:40:02 update

# 2020-02-07T14:06:34 update

# 2020-04-03T08:53:40 update

# 2020-04-06T19:36:29 update

# 2020-05-12T11:51:05 update

# 2020-08-17T08:37:15 update

# 2020-09-15T10:39:38 update

# 2020-10-06T11:26:19 update

# 2020-10-21T13:32:43 update

# 2020-12-14T18:18:36 update

# 2020-12-23T17:15:03 update

# 2021-01-25T16:29:00 update

# 2021-02-23T11:23:50 update

# 2021-03-19T12:21:19 update

# 2021-07-29T18:48:25 update

# 2021-08-25T12:46:58 update

# 2021-09-09T16:27:13 update

# 2021-12-16T12:05:30 update

# 2022-05-07T14:05:12 update

# 2022-07-18T20:52:29 update

# 2022-07-31T18:42:26 update

# 2022-09-09T13:10:08 update

# 2023-01-04T15:16:57 update

# 2023-01-17T14:49:04 update

# 2023-02-15T13:51:30 update

# 2023-03-08T09:15:53 update

# 2023-03-23T16:32:20 update

# 2023-03-28T09:32:01 update

# 2023-05-05T17:28:22 update

# 2023-06-01T08:13:52 update

# 2023-06-20T09:58:10 update

# 2023-07-04T16:14:34 update

# 2023-07-17T20:49:40 update

# 2023-12-26T11:49:18 update

# 2024-05-27T11:00:06 update

# 2024-07-04T08:53:03 update

# 2024-07-18T16:19:02 update

# 2024-08-07T09:35:35 update

# 2024-08-22T14:32:14 update

# 2025-05-20T14:19:23 update

# 2025-07-17T17:54:48 update

# 2025-07-28T13:06:30 update

# 2025-12-22T19:05:25 update

# 2026-01-08T18:43:02 update

# 2026-01-12T16:53:28 update

# 2026-04-16T16:58:23 update
