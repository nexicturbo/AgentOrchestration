import pytest
from src.orchestrator.scheduler import PriorityQueue, QueueCapacityError, TaskScheduler


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_enqueue_rejects_when_queue_capacity_is_full(self):
        scheduler = TaskScheduler(max_queue_size=1)
        scheduler.enqueue({"type": "first"})

        with pytest.raises(QueueCapacityError):
            scheduler.enqueue({"type": "second"})

        assert scheduler.queued_count() == 1

    def test_capacity_is_released_after_complete(self):
        scheduler = TaskScheduler(max_queue_size=1)
        scheduler.enqueue({"type": "first"})

        import asyncio
        task = asyncio.run(scheduler.dequeue())

        assert task["type"] == "first"
        assert scheduler.queued_count() == 1
        assert scheduler.complete(task["id"])
        assert scheduler.queued_count() == 0
        scheduler.enqueue({"type": "second"})
        assert scheduler.queued_count() == 1

    def test_enqueue_rollback_releases_reserved_capacity(self, caplog):
        class FailingQueue(PriorityQueue):
            def push(self, item, priority=0):
                raise RuntimeError("simulated durable enqueue failure")

        scheduler = TaskScheduler(max_queue_size=1)
        scheduler._queues["default"] = FailingQueue()

        with pytest.raises(RuntimeError):
            scheduler.enqueue({"type": "will-rollback"})

        assert scheduler.queued_count() == 0
        assert scheduler.metrics_snapshot()["enqueue_rollbacks"] == 1
        assert scheduler.audit_events()[-1]["event"] == "enqueue_rollback"
        assert "queue enqueue rolled back" in caplog.text

        scheduler._queues["default"] = PriorityQueue()
        task_id = scheduler.enqueue({"type": "after-rollback"})

        assert task_id is not None
        assert scheduler.queued_count() == 1

    def test_retry_preserves_task_id_and_counts_retries(self):
        scheduler = TaskScheduler(max_queue_size=1)
        task_id = scheduler.enqueue({"type": "retry-me"})

        import asyncio
        task = asyncio.run(scheduler.dequeue())

        assert scheduler.fail(task["id"])
        retried = asyncio.run(scheduler.dequeue())
        assert retried["id"] == task_id
        assert retried["retries"] == 1

    def test_retry_rollback_restores_in_flight_task_and_capacity(self):
        class FailingQueue(PriorityQueue):
            def push(self, item, priority=0):
                raise RuntimeError("simulated retry enqueue failure")

        scheduler = TaskScheduler(max_queue_size=1)
        task_id = scheduler.enqueue({"type": "retry-me"})

        import asyncio
        task = asyncio.run(scheduler.dequeue())
        scheduler._queues["default"] = FailingQueue()

        with pytest.raises(RuntimeError):
            scheduler.fail(task["id"])

        assert scheduler.queued_count() == 1
        assert scheduler.metrics_snapshot()["retry_rollbacks"] == 1
        assert scheduler.audit_events()[-1]["event"] == "retry_rollback"
        assert scheduler.complete(task_id)
        assert scheduler.queued_count() == 0

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
