"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import time
from typing import Any, Dict, List, Optional
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


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, Dict[str, Any]] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._tasks: Dict[str, Dict] = {}
        self._audit: List[Dict[str, Any]] = []
        self._max_retries = 3

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task_record = dict(task)
        task_record.update({
            "id": task_id,
            "attempt": 1,
            "revision": 1,
            "state": "queued",
            "queue": queue,
            "priority": priority,
            "enqueued_at": time.time(),
            "retries": 0,
        })
        self._tasks[task_id] = task_record
        self._queue_task(task_record, queue, priority)
        return task_id

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task_record = dict(task)
        task_record.update({
            "id": task_id,
            "attempt": 1,
            "revision": 1,
            "state": "scheduled",
            "queue": queue,
            "priority": priority,
            "scheduled_at": time.time(),
            "retries": 0,
        })
        self._tasks[task_id] = task_record
        self._scheduled[task_id] = {
            "task": task_record,
            "run_at": time.time() + delay,
            "queue": queue,
            "priority": priority,
        }
        return task_id

    async def dequeue(
        self,
        queue: str = "default",
        timeout: float = 1.0,
    ) -> Optional[Dict]:
        now = time.time()
        expired = [
            tid
            for tid, item in self._scheduled.items()
            if item["run_at"] <= now
        ]
        for tid in expired:
            item = self._scheduled.pop(tid)
            task = item["task"]
            task["state"] = "queued"
            self._queue_task(task, item["queue"], item["priority"])

        if queue in self._queues and len(self._queues[queue]) > 0:
            while len(self._queues[queue]) > 0:
                entry = self._queues[queue].pop()
                task = self._tasks.get(entry["task_id"])
                if self._reject_stale_queue_entry(entry, task):
                    continue

                task["state"] = "in_flight"
                task["dispatched_at"] = time.time()
                self._in_flight[task["id"]] = task
                return dict(task)
        return None

    def complete(
        self,
        task_id: str,
        *,
        attempt: Optional[int] = None,
        revision: Optional[int] = None,
    ) -> bool:
        task = self._in_flight.get(task_id)
        if not self._can_commit_transition(
            task,
            attempt,
            revision,
            "complete",
        ):
            return False

        self._in_flight.pop(task_id, None)
        task["state"] = "completed"
        task["completed_at"] = time.time()
        self._record_audit("complete", task)
        return True

    def fail(
        self,
        task_id: str,
        queue: str = "default",
        *,
        attempt: Optional[int] = None,
        revision: Optional[int] = None,
    ) -> bool:
        task = self._in_flight.get(task_id)
        if not self._can_commit_transition(task, attempt, revision, "fail"):
            return False

        self._in_flight.pop(task_id, None)
        task["retries"] += 1
        if task["retries"] < self._max_retries:
            task["attempt"] += 1
            task["revision"] += 1
            task["state"] = "queued"
            self._queue_task(task, queue, task.get("priority", 0))
            self._record_audit("retry_queued", task)
            return True

        task["state"] = "failed"
        self._record_audit("failed", task)
        return False

    def audit_records(self) -> List[Dict[str, Any]]:
        return list(self._audit)

    def _queue_task(self, task: Dict, queue: str, priority: int) -> None:
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        task["queue"] = queue
        task["priority"] = priority
        self._queues[queue].push(
            {
                "task_id": task["id"],
                "attempt": task["attempt"],
                "revision": task["revision"],
            },
            priority,
        )

    def _reject_stale_queue_entry(
        self,
        entry: Dict,
        task: Optional[Dict],
    ) -> bool:
        if not task:
            self._record_audit("reject", None, reason="missing_task")
            return True
        if task["state"] != "queued":
            self._record_audit(
                "reject",
                task,
                reason="invalid_lifecycle",
                entry=entry,
            )
            return True
        if task["attempt"] != entry["attempt"]:
            self._record_audit(
                "reject",
                task,
                reason="stale_attempt",
                entry=entry,
            )
            return True
        if task["revision"] != entry["revision"]:
            self._record_audit(
                "reject",
                task,
                reason="stale_revision",
                entry=entry,
            )
            return True
        return False

    def _can_commit_transition(
        self,
        task: Optional[Dict],
        attempt: Optional[int],
        revision: Optional[int],
        action: str,
    ) -> bool:
        if not task:
            self._record_audit("reject", None, reason=f"{action}_missing_task")
            return False
        if task["state"] != "in_flight":
            self._record_audit(
                "reject",
                task,
                reason=f"{action}_invalid_lifecycle",
            )
            return False
        if attempt is not None and task["attempt"] != attempt:
            self._record_audit(
                "reject",
                task,
                reason=f"{action}_stale_attempt",
                entry={"attempt": attempt},
            )
            return False
        if revision is not None and task["revision"] != revision:
            self._record_audit(
                "reject",
                task,
                reason=f"{action}_stale_revision",
                entry={"revision": revision},
            )
            return False
        return True

    def _record_audit(
        self,
        action: str,
        task: Optional[Dict],
        *,
        reason: Optional[str] = None,
        entry: Optional[Dict] = None,
    ) -> None:
        record: Dict[str, Any] = {
            "action": action,
            "reason": reason,
            "task_id": task.get("id") if task else None,
            "state": task.get("state") if task else None,
            "attempt": task.get("attempt") if task else None,
            "revision": task.get("revision") if task else None,
        }
        if entry:
            record["entry_attempt"] = entry.get("attempt")
            record["entry_revision"] = entry.get("revision")
        self._audit.append(record)

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
