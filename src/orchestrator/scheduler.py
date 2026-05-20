"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

from src.common.errors import ResourceExhaustedError

logger = logging.getLogger(__name__)


class QueueCapacityError(ResourceExhaustedError):
    def __init__(self, queue: str, max_size: int):
        super().__init__(f"queue '{queue}' capacity {max_size}")
        self.queue = queue
        self.max_size = max_size


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self, max_queue_size: Optional[int] = None):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._capacity_used: Dict[str, int] = {}
        self._audit_events: List[Dict[str, Any]] = []
        self._metrics: Dict[str, int] = {
            "enqueue_rollbacks": 0,
            "capacity_rejections": 0,
            "retry_rollbacks": 0,
        }
        self._max_queue_size = max_queue_size
        self._max_retries = 3

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = task.get("id") or str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task.setdefault("retries", 0)
        task["priority"] = priority

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()

        self._reserve_capacity(queue, task_id)
        task["_capacity_queue"] = queue
        try:
            self._queues[queue].push(task, priority)
        except Exception as exc:
            self._release_capacity(queue)
            task.pop("_capacity_queue", None)
            self._metrics["enqueue_rollbacks"] += 1
            self._record_audit_event("enqueue_rollback", queue, task_id, exc)
            logger.warning(
                "queue enqueue rolled back",
                extra={
                    "queue": queue,
                    "task_id": task_id,
                    "capacity_used": self._capacity_used.get(queue, 0),
                    "reason": exc.__class__.__name__,
                },
            )
            raise

        return task_id

    def queued_count(self, queue: str = "default") -> int:
        return self._capacity_used.get(queue, 0)

    def metrics_snapshot(self) -> Dict[str, int]:
        return dict(self._metrics)

    def audit_events(self) -> List[Dict[str, Any]]:
        return list(self._audit_events)

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task is None:
            return False
        self._release_task_capacity(task)
        return True

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            original_retries = task.get("retries", 0)
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                try:
                    self._retry_enqueue(task, queue)
                    return True
                except Exception:
                    task["retries"] = original_retries
                    self._in_flight[task_id] = task
                    raise
            self._release_task_capacity(task)
        return False

    def _retry_enqueue(self, task: Dict, queue: str) -> None:
        task_id = task["id"]
        source_queue = task.get("_capacity_queue")
        priority = task.get("priority", 0)

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()

        if source_queue == queue:
            try:
                self._queues[queue].push(task, priority)
            except Exception as exc:
                self._metrics["retry_rollbacks"] += 1
                self._record_audit_event("retry_rollback", queue, task_id, exc)
                raise
            return

        self._reserve_capacity(queue, task_id)
        try:
            self._queues[queue].push(task, priority)
        except Exception as exc:
            self._release_capacity(queue)
            self._metrics["retry_rollbacks"] += 1
            self._record_audit_event("retry_rollback", queue, task_id, exc)
            raise

        if source_queue:
            self._release_capacity(source_queue)
        task["_capacity_queue"] = queue

    def _reserve_capacity(self, queue: str, task_id: str) -> None:
        if self._max_queue_size is None:
            return

        used = self._capacity_used.get(queue, 0)
        if used >= self._max_queue_size:
            self._metrics["capacity_rejections"] += 1
            self._record_audit_event("capacity_rejected", queue, task_id)
            logger.warning(
                "queue capacity exhausted",
                extra={
                    "queue": queue,
                    "task_id": task_id,
                    "capacity_used": used,
                    "capacity_limit": self._max_queue_size,
                },
            )
            raise QueueCapacityError(queue, self._max_queue_size)

        self._capacity_used[queue] = used + 1

    def _release_capacity(self, queue: str) -> None:
        if self._max_queue_size is None:
            return

        used = self._capacity_used.get(queue, 0)
        if used <= 1:
            self._capacity_used.pop(queue, None)
        else:
            self._capacity_used[queue] = used - 1

    def _release_task_capacity(self, task: Dict) -> None:
        capacity_queue = task.pop("_capacity_queue", None)
        if capacity_queue:
            self._release_capacity(capacity_queue)

    def _record_audit_event(
        self,
        event: str,
        queue: str,
        task_id: str,
        exc: Optional[Exception] = None,
    ) -> None:
        audit_event: Dict[str, Any] = {
            "event": event,
            "queue": queue,
            "task_id": task_id,
            "capacity_used": self._capacity_used.get(queue, 0),
        }
        if exc is not None:
            audit_event["reason"] = exc.__class__.__name__
        self._audit_events.append(audit_event)

# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update
