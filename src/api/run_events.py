"""Run event stream service with bounded pagination."""

from typing import Dict, List, Optional

from fastapi import HTTPException

MAX_RUN_EVENT_LIMIT = 100
MAX_RUN_EVENT_WINDOW = 1000


class RunEventStore:
    def __init__(self):
        self._events: Dict[tuple, List[Dict]] = {}

    def set_events(
        self, workspace_id: str, run_id: str, events: List[Dict]
    ) -> None:
        self._events[(workspace_id, run_id)] = list(events)

    def list_events(
        self, workspace_id: str, run_id: str, offset: int, limit: int
    ) -> List[Dict]:
        events = self._events.get((workspace_id, run_id), [])
        return events[offset:offset + limit]


run_event_store = RunEventStore()


def validate_run_events_request(
    workspace_id: str,
    run_id: str,
    authorization: Optional[str],
    offset: int,
    limit: int,
) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise HTTPException(status_code=400, detail="workspace_id is required")
    if not isinstance(run_id, str) or not run_id.strip():
        raise HTTPException(status_code=400, detail="run_id is required")
    if offset < 0:
        raise HTTPException(
            status_code=400, detail="offset must be non-negative"
        )
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be positive")
    if limit > MAX_RUN_EVENT_LIMIT:
        raise HTTPException(status_code=400, detail="limit exceeds maximum")
    if offset + limit > MAX_RUN_EVENT_WINDOW:
        raise HTTPException(
            status_code=400, detail="pagination window exceeds maximum"
        )


def list_run_events(
    workspace_id: str,
    run_id: str,
    authorization: Optional[str],
    offset: int = 0,
    limit: int = 100,
) -> Dict[str, object]:
    validate_run_events_request(
        workspace_id, run_id, authorization, offset, limit
    )
    workspace_id = workspace_id.strip()
    run_id = run_id.strip()
    events = run_event_store.list_events(workspace_id, run_id, offset, limit)
    return {
        "workspace_id": workspace_id,
        "run_id": run_id,
        "offset": offset,
        "limit": limit,
        "events": events,
    }
