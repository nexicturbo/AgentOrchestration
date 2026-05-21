"""Task Scheduler — Priority-based task queuing and dispatch."""

import heapq
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


CANCELLED_LIFECYCLES = {"cancelled", "canceled", "cancelling", "canceling"}


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
        self._max_retries = 3
        self._cancelled_parents: Set[str] = set()
        self._task_state: Dict[str, Dict[str, Any]] = {}
        self.retry_audit_log: List[Dict[str, Any]] = []

    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task.setdefault("retries", 0)
        task.setdefault("attempt", 0)
        task.setdefault("revision", 0)
        task["lifecycle"] = task.get("lifecycle", "queued")
        task["lifecycle_state"] = task.get(
            "lifecycle_state",
            task["lifecycle"],
        )

        self._record_task_state(task_id, task)
        self._push_task(task, queue, priority)
        return task_id

    def _push_task(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> None:
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)

    def schedule(
        self,
        task: Dict,
        delay: float,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task.setdefault("retries", 0)
        task.setdefault("attempt", 0)
        task.setdefault("revision", 0)
        task["lifecycle"] = task.get("lifecycle", "queued")
        task["lifecycle_state"] = task.get(
            "lifecycle_state",
            task["lifecycle"],
        )
        self._record_task_state(task_id, task)
        self._scheduled[task_id] = {
            "task": task,
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
            for tid, scheduled in self._scheduled.items()
            if scheduled["run_at"] <= now and scheduled["queue"] == queue
        ]
        for tid in expired:
            scheduled = self._scheduled.pop(tid)
            self._push_task(
                scheduled["task"],
                queue,
                priority=scheduled["priority"],
            )

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task["lifecycle"] = "running"
                task["lifecycle_state"] = "running"
                self._record_task_state(task["id"], task)
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task is None:
            return False

        task["lifecycle"] = "completed"
        task["lifecycle_state"] = "completed"
        self._record_task_state(task_id, task)
        return True

    def cancel_parent(self, parent_id: str) -> None:
        self._cancelled_parents.add(parent_id)
        if parent_id in self._task_state:
            self._task_state[parent_id]["lifecycle"] = "cancelled"
            self._task_state[parent_id]["lifecycle_state"] = "cancelled"

    def cancel(self, task_id: str, reason: str = "cancelled") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task is None and task_id not in self._task_state:
            return False

        if task is not None:
            task["lifecycle"] = "cancelled"
            task["lifecycle_state"] = "cancelled"
            self._record_task_state(task_id, task)
        else:
            self._task_state[task_id]["lifecycle"] = "cancelled"
            self._task_state[task_id]["lifecycle_state"] = "cancelled"

        self._audit_retry({"id": task_id}, "cancelled", reason)
        return True

    def fail(
        self,
        task_id: str,
        queue: str = "default",
        expected_attempt: Optional[int] = None,
        expected_revision: Optional[int] = None,
        expected_parent_attempt: Optional[int] = None,
        expected_parent_revision: Optional[int] = None,
        parent_lifecycle: Optional[str] = None,
    ) -> bool:
        task = self._in_flight.get(task_id)
        if task and not self._can_retry(
            task,
            expected_attempt,
            expected_revision,
            expected_parent_attempt,
            expected_parent_revision,
            parent_lifecycle,
        ):
            return False

        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                task["attempt"] = task.get("attempt", 0) + 1
                task["revision"] = task.get("revision", 0) + 1
                task["lifecycle"] = "queued"
                task["lifecycle_state"] = "queued"
                task["enqueued_at"] = time.time()
                self._record_task_state(task_id, task)
                self._push_task(task, queue, priority=task.get("priority", 0))
                self._audit_retry(task, "accepted", "retry_enqueued")
                return True
            task["lifecycle"] = "failed"
            task["lifecycle_state"] = "failed"
            self._record_task_state(task_id, task)
        return False

    def _can_retry(
        self,
        task: Dict,
        expected_attempt: Optional[int],
        expected_revision: Optional[int],
        expected_parent_attempt: Optional[int],
        expected_parent_revision: Optional[int],
        parent_lifecycle: Optional[str],
    ) -> bool:
        reason = self._retry_rejection_reason(
            task,
            expected_attempt,
            expected_revision,
            expected_parent_attempt,
            expected_parent_revision,
            parent_lifecycle,
        )
        if not reason:
            return True

        task["retry_state"] = "rejected"
        task["retry_rejected_reason"] = reason
        if reason in {"parent_cancelled", "task_cancelled"}:
            task_id = task["id"]
            self._in_flight.pop(task_id, None)
            task["lifecycle"] = "cancelled"
            task["lifecycle_state"] = "cancelled"
            self._record_task_state(task_id, task)
        self._audit_retry(task, "rejected", reason)
        return False

    def _retry_rejection_reason(
        self,
        task: Dict,
        expected_attempt: Optional[int],
        expected_revision: Optional[int],
        expected_parent_attempt: Optional[int],
        expected_parent_revision: Optional[int],
        parent_lifecycle: Optional[str],
    ) -> Optional[str]:
        if (
            expected_attempt is not None
            and task.get("attempt") != expected_attempt
        ):
            return "stale_attempt"
        if (
            expected_revision is not None
            and task.get("revision") != expected_revision
        ):
            return "stale_revision"
        if self._is_cancelled(task.get("lifecycle")) or self._is_cancelled(
            task.get("lifecycle_state")
        ):
            return "task_cancelled"
        if self._is_cancelled(parent_lifecycle) or self._is_cancelled(
            task.get("parent_lifecycle")
        ) or self._is_cancelled(task.get("parent_lifecycle_state")):
            return "parent_cancelled"

        parent_id = task.get("parent_id") or task.get("parent_task_id")
        if parent_id in self._cancelled_parents:
            return "parent_cancelled"
        parent_state = self._task_state.get(parent_id)
        if parent_state and self._is_cancelled(parent_state.get("lifecycle")):
            return "parent_cancelled"
        if parent_state and self._is_cancelled(
            parent_state.get("lifecycle_state")
        ):
            return "parent_cancelled"

        expected_parent_attempt = self._first_not_none(
            expected_parent_attempt, task.get("parent_attempt")
        )
        expected_parent_revision = self._first_not_none(
            expected_parent_revision, task.get("parent_revision")
        )
        if expected_parent_attempt is not None:
            if parent_state is None:
                return "missing_parent_state"
            if parent_state.get("attempt") != expected_parent_attempt:
                return "stale_parent_attempt"
        if expected_parent_revision is not None:
            if parent_state is None:
                return "missing_parent_state"
            if parent_state.get("revision") != expected_parent_revision:
                return "stale_parent_revision"
        return None

    @staticmethod
    def _is_cancelled(lifecycle: Optional[str]) -> bool:
        return lifecycle in CANCELLED_LIFECYCLES

    @staticmethod
    def _first_not_none(
        left: Optional[int],
        right: Optional[int],
    ) -> Optional[int]:
        return left if left is not None else right

    def get_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        state = self._task_state.get(task_id)
        return dict(state) if state is not None else None

    def retry_audit(self) -> List[Dict[str, Any]]:
        return [dict(record) for record in self.retry_audit_log]

    def _record_task_state(self, task_id: str, task: Dict) -> None:
        self._task_state[task_id] = {
            "attempt": task.get("attempt"),
            "revision": task.get("revision"),
            "retries": task.get("retries"),
            "lifecycle": task.get("lifecycle"),
            "lifecycle_state": task.get("lifecycle_state"),
        }

    def _audit_retry(self, task: Dict, decision: str, reason: str) -> None:
        self.retry_audit_log.append({
            "decision": decision,
            "reason": reason,
            "task_id": task.get("id"),
            "parent_id": task.get("parent_id") or task.get("parent_task_id"),
            "attempt": task.get("attempt"),
            "revision": task.get("revision"),
            "lifecycle": task.get("lifecycle"),
            "parent_lifecycle": task.get("parent_lifecycle"),
        })
        self.retry_audit_log = self.retry_audit_log[-100:]

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
