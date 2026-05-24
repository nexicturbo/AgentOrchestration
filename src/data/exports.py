"""Bulk export filter validation before queue persistence."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, Iterable, List, Mapping, Optional, Protocol
from uuid import uuid4


SUPPORTED_EXPORT_STATUSES = frozenset(
    {"pending", "running", "completed", "failed", "cancelled"}
)


class ExportFilterValidationError(ValueError):
    """Raised when an export filter cannot be safely queued."""


class ExportQueue(Protocol):
    def enqueue(
        self,
        task: Dict,
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        """Persist a task and return the queue id."""


@dataclass(frozen=True)
class NormalizedExportFilters:
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    workspace_id: Optional[str] = None
    statuses: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        data: Dict[str, object] = {}
        if self.date_from is not None:
            data["date_from"] = self.date_from
        if self.date_to is not None:
            data["date_to"] = self.date_to
        if self.workspace_id is not None:
            data["workspace_id"] = self.workspace_id
        if self.statuses:
            data["statuses"] = list(self.statuses)
        return data


@dataclass(frozen=True)
class ExportJob:
    job_id: str
    queue_task_id: str
    filters: NormalizedExportFilters
    created_at: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "job_id": self.job_id,
            "queue_task_id": self.queue_task_id,
            "filters": self.filters.to_dict(),
            "created_at": self.created_at,
        }


class ExportJobService:
    """Validate export filters synchronously before enqueueing jobs."""

    def __init__(self, queue: ExportQueue, queue_name: str = "exports"):
        self.queue = queue
        self.queue_name = queue_name

    def create_job(
        self,
        raw_filters: Mapping[str, object],
        priority: int = 0,
    ) -> ExportJob:
        filters = normalize_export_filters(raw_filters)
        job_id = str(uuid4())
        created_at = _utc_now_iso()
        task = {
            "type": "bulk_export",
            "job_id": job_id,
            "filters": filters.to_dict(),
            "created_at": created_at,
        }
        queue_task_id = self.queue.enqueue(
            task,
            queue=self.queue_name,
            priority=priority,
        )
        return ExportJob(
            job_id=job_id,
            queue_task_id=queue_task_id,
            filters=filters,
            created_at=created_at,
        )


def normalize_export_filters(
    raw_filters: Mapping[str, object],
) -> NormalizedExportFilters:
    date_from = _normalize_date(raw_filters.get("date_from"), "date_from")
    date_to = _normalize_date(raw_filters.get("date_to"), "date_to")
    if date_from and date_to and date_from > date_to:
        raise ExportFilterValidationError(
            "date_from must be on or before date_to"
        )

    workspace_id = _normalize_workspace_id(raw_filters.get("workspace_id"))
    statuses = _normalize_statuses(raw_filters)
    return NormalizedExportFilters(
        date_from=date_from,
        date_to=date_to,
        workspace_id=workspace_id,
        statuses=statuses,
    )


def _normalize_date(value: object, field_name: str) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return date.fromisoformat(normalized).isoformat()
        except ValueError as exc:
            raise ExportFilterValidationError(
                f"{field_name} must be an ISO date"
            ) from exc
    raise ExportFilterValidationError(f"{field_name} must be an ISO date")


def _normalize_workspace_id(value: object) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ExportFilterValidationError("workspace_id must be a string")
    workspace_id = value.strip()
    if not workspace_id:
        raise ExportFilterValidationError("workspace_id cannot be empty")
    return workspace_id


def _normalize_statuses(raw_filters: Mapping[str, object]) -> List[str]:
    if "statuses" in raw_filters:
        raw_statuses = raw_filters.get("statuses")
    else:
        raw_statuses = raw_filters.get("status")

    if raw_statuses is None:
        return []
    if isinstance(raw_statuses, str):
        return [_normalize_status(raw_statuses)]
    if not isinstance(raw_statuses, Iterable):
        raise ExportFilterValidationError("statuses must be strings")

    statuses = [_normalize_status(status) for status in raw_statuses]
    if not statuses:
        raise ExportFilterValidationError("statuses cannot be empty")
    return statuses


def _normalize_status(value: object) -> str:
    if not isinstance(value, str):
        raise ExportFilterValidationError("statuses must be strings")
    status = value.strip().lower()
    if not status:
        raise ExportFilterValidationError("statuses cannot contain blanks")
    if status not in SUPPORTED_EXPORT_STATUSES:
        raise ExportFilterValidationError(
            f"unsupported export status: {value}"
        )
    return status


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
