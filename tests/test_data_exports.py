import pytest

from src.data import (
    ExportFilterValidationError,
    ExportJobService,
    normalize_export_filters,
)


class RecordingQueue:
    def __init__(self):
        self.tasks = []

    def enqueue(self, task, queue="default", priority=0):
        self.tasks.append(
            {
                "task": task,
                "queue": queue,
                "priority": priority,
            }
        )
        return f"queued-{len(self.tasks)}"


def test_export_job_persists_normalized_filters_before_enqueue():
    queue = RecordingQueue()
    service = ExportJobService(queue)

    job = service.create_job(
        {
            "date_from": " 2026-05-01 ",
            "date_to": "2026-05-24",
            "workspace_id": " workspace-a ",
            "statuses": ["Completed", "failed"],
        },
        priority=7,
    )

    assert job.queue_task_id == "queued-1"
    assert queue.tasks == [
        {
            "task": {
                "type": "bulk_export",
                "job_id": job.job_id,
                "filters": {
                    "date_from": "2026-05-01",
                    "date_to": "2026-05-24",
                    "workspace_id": "workspace-a",
                    "statuses": ["completed", "failed"],
                },
                "created_at": job.created_at,
            },
            "queue": "exports",
            "priority": 7,
        }
    ]


def test_boundary_dates_are_valid_when_range_is_inclusive():
    filters = normalize_export_filters(
        {
            "date_from": "2026-05-24",
            "date_to": "2026-05-24",
            "status": "PENDING",
        }
    )

    assert filters.to_dict() == {
        "date_from": "2026-05-24",
        "date_to": "2026-05-24",
        "statuses": ["pending"],
    }


def test_empty_date_range_is_rejected_before_enqueue():
    queue = RecordingQueue()
    service = ExportJobService(queue)

    with pytest.raises(
        ExportFilterValidationError,
        match="date_from must be on or before date_to",
    ):
        service.create_job(
            {
                "date_from": "2026-05-25",
                "date_to": "2026-05-24",
            }
        )

    assert queue.tasks == []


def test_unsupported_status_is_rejected_before_enqueue():
    queue = RecordingQueue()
    service = ExportJobService(queue)

    with pytest.raises(
        ExportFilterValidationError,
        match="unsupported export status",
    ):
        service.create_job({"status": "archived"})

    assert queue.tasks == []


def test_blank_workspace_is_rejected_before_enqueue():
    queue = RecordingQueue()
    service = ExportJobService(queue)

    with pytest.raises(
        ExportFilterValidationError,
        match="workspace_id cannot be empty",
    ):
        service.create_job({"workspace_id": "   "})

    assert queue.tasks == []
