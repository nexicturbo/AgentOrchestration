"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
from threading import RLock
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4


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


class ScheduledJobRegistry:
    """Shared cron-job leadership and execution registry."""

    def __init__(self):
        self._lock = RLock()
        self._leases: Dict[str, Dict[str, Any]] = {}
        self._executions: set[Tuple[str, str]] = set()
        self._events: List[Dict[str, Any]] = []

    def register(
        self,
        job_key: str,
        release_id: str,
        task_id: str,
        run_at: float,
        now: float,
        lease_ttl: float,
    ) -> Tuple[bool, str, Dict[str, Any]]:
        with self._lock:
            lease = self._leases.get(job_key)
            if lease and lease["expires_at"] > now:
                event = {
                    "decision": "duplicate_scheduled_job_deferred",
                    "job_key": job_key,
                    "release_id": release_id,
                    "leader_release_id": lease["release_id"],
                    "task_id": lease["task_id"],
                }
                self._events.append(event)
                return False, lease["task_id"], event

            event = {
                "decision": "scheduler_leadership_acquired",
                "job_key": job_key,
                "release_id": release_id,
                "task_id": task_id,
            }
            if lease:
                event["decision"] = "scheduler_leadership_changed"
                event["previous_release_id"] = lease["release_id"]

            self._leases[job_key] = {
                "release_id": release_id,
                "task_id": task_id,
                "run_at": run_at,
                "expires_at": now + lease_ttl,
            }
            self._events.append(event)
            return True, task_id, event

    def claim_execution(
        self,
        job_key: str,
        release_id: str,
        task_id: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        with self._lock:
            lease = self._leases.get(job_key)
            if not lease or lease["task_id"] != task_id:
                event = {
                    "decision": "scheduled_job_execution_deferred",
                    "job_key": job_key,
                    "release_id": release_id,
                    "task_id": task_id,
                }
                if lease:
                    event["leader_release_id"] = lease["release_id"]
                    event["leader_task_id"] = lease["task_id"]
                self._events.append(event)
                return False, event

            execution_key = (job_key, task_id)
            if execution_key in self._executions:
                event = {
                    "decision": "duplicate_scheduled_execution_deferred",
                    "job_key": job_key,
                    "release_id": release_id,
                    "task_id": task_id,
                }
                self._events.append(event)
                return False, event

            self._executions.add(execution_key)
            event = {
                "decision": "scheduled_job_execution_claimed",
                "job_key": job_key,
                "release_id": release_id,
                "task_id": task_id,
            }
            self._events.append(event)
            return True, event

    def leadership_events(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(event) for event in self._events]


class TaskScheduler:
    def __init__(
        self,
        release_id: str = "local",
        scheduled_job_registry: Optional[ScheduledJobRegistry] = None,
        leadership_ttl: float = 30.0,
        clock: Callable[[], float] = time.time,
    ):
        self.release_id = release_id
        self._scheduled_job_registry = scheduled_job_registry
        self._leadership_ttl = leadership_ttl
        self._clock = clock
        self._leadership_events: List[Dict[str, Any]] = []
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, Dict[str, Any]] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
        job_key: Optional[str] = None,
    ) -> str:
        task_id = str(uuid4())
        run_at = self._clock() + delay
        scheduled_task = dict(task)
        scheduled_task["id"] = task_id
        scheduled_task["scheduled_at"] = self._clock()
        scheduled_task["retries"] = scheduled_task.get("retries", 0)

        if job_key and self._scheduled_job_registry:
            (
                accepted,
                existing_id,
                event,
            ) = self._scheduled_job_registry.register(
                job_key,
                self.release_id,
                task_id,
                run_at,
                self._clock(),
                self._leadership_ttl,
            )
            self._leadership_events.append(event)
            if not accepted:
                return existing_id
            scheduled_task["scheduled_job_key"] = job_key
            scheduled_task["release_id"] = self.release_id

        self._scheduled[task_id] = {
            "task": scheduled_task,
            "run_at": run_at,
            "queue": queue,
            "priority": priority,
            "job_key": job_key,
        }
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        now = self._clock()
        expired = [
            tid
            for tid, record in self._scheduled.items()
            if record["run_at"] <= now and record["queue"] == queue
        ]
        for tid in expired:
            record = self._scheduled.pop(tid)
            if not self._can_execute_scheduled_record(tid, record):
                continue
            task = record["task"]
            if queue not in self._queues:
                self._queues[queue] = PriorityQueue()
            self._queues[queue].push(task, record["priority"])

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def leadership_events(self) -> List[Dict[str, Any]]:
        return [dict(event) for event in self._leadership_events]

    def _can_execute_scheduled_record(
        self,
        task_id: str,
        record: Dict[str, Any],
    ) -> bool:
        job_key = record.get("job_key")
        if not job_key or not self._scheduled_job_registry:
            return True

        accepted, event = self._scheduled_job_registry.claim_execution(
            job_key,
            self.release_id,
            task_id,
        )
        self._leadership_events.append(event)
        return accepted

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
