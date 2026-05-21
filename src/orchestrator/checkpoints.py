"""Checkpoint persistence for resumable worker executions."""

import copy
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


class CheckpointConflictError(ValueError):
    """Raised when a checkpoint key is reused with different data."""


def _require_key_part(name: str, value: Any) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} must be provided")
    if "/" in text or "\x00" in text:
        raise ValueError(
            f"{name} contains unsupported checkpoint key characters"
        )
    return text


def checkpoint_key(task_id: Any, step_id: Any, attempt: Any) -> str:
    """Build the stable logical key for a task/step/attempt checkpoint."""

    task = _require_key_part("task_id", task_id)
    step = _require_key_part("step_id", step_id)
    try:
        attempt_number = int(attempt)
    except (TypeError, ValueError) as exc:
        raise ValueError("attempt must be an integer") from exc
    if attempt_number < 0:
        raise ValueError("attempt must be non-negative")
    return f"{task}/{step}/{attempt_number}"


def _payload_bytes(payload: Any) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def checkpoint_digest(payload: Any) -> str:
    return hashlib.sha256(_payload_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class CheckpointRecord:
    key: str
    task_id: str
    step_id: str
    attempt: int
    digest: str
    payload: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class CheckpointStore:
    """Digest-checked checkpoint store with idempotent retry writes."""

    def __init__(self):
        self._records: Dict[str, CheckpointRecord] = {}

    def write(
        self,
        task_id: Any,
        step_id: Any,
        attempt: Any,
        payload: Any,
        *,
        digest: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CheckpointRecord:
        key, task, step, attempt_number = self._normalize_key(
            task_id,
            step_id,
            attempt,
        )
        expected_digest = digest or checkpoint_digest(payload)
        actual_digest = checkpoint_digest(payload)
        if expected_digest != actual_digest:
            raise ValueError(
                "checkpoint payload does not match provided digest"
            )

        existing = self._records.get(key)
        if existing is not None:
            if existing.digest != expected_digest:
                raise CheckpointConflictError(
                    f"checkpoint {key} already exists with a different digest"
                )
            return existing

        record = CheckpointRecord(
            key=key,
            task_id=task,
            step_id=step,
            attempt=attempt_number,
            digest=expected_digest,
            payload=copy.deepcopy(payload),
            metadata=copy.deepcopy(metadata or {}),
        )
        self._records[key] = record
        return record

    def get(
        self,
        task_id: Any,
        step_id: Any,
        attempt: Any,
    ) -> Optional[CheckpointRecord]:
        key = checkpoint_key(task_id, step_id, attempt)
        return self._records.get(key)

    def latest_for_task(
        self,
        task_id: Any,
        step_id: Optional[Any] = None,
    ) -> Optional[CheckpointRecord]:
        task = _require_key_part("task_id", task_id)
        step = (
            _require_key_part("step_id", step_id)
            if step_id is not None
            else None
        )
        matches = [
            record
            for record in self._records.values()
            if record.task_id == task
            and (step is None or record.step_id == step)
        ]
        if not matches:
            return None
        return max(
            matches,
            key=lambda record: (record.attempt, record.created_at),
        )

    def list_for_task(self, task_id: Any) -> List[CheckpointRecord]:
        task = _require_key_part("task_id", task_id)
        return sorted(
            (
                record
                for record in self._records.values()
                if record.task_id == task
            ),
            key=lambda record: (record.step_id, record.attempt),
        )

    def keys(self) -> Iterable[str]:
        return tuple(sorted(self._records))

    def __len__(self) -> int:
        return len(self._records)

    @staticmethod
    def _normalize_key(
        task_id: Any,
        step_id: Any,
        attempt: Any,
    ) -> Tuple[str, str, str, int]:
        key = checkpoint_key(task_id, step_id, attempt)
        task, step, attempt_text = key.split("/", 2)
        return key, task, step, int(attempt_text)
