"""Bounded trace aggregation for orchestration runtime transitions."""

import hashlib
import json
import threading
import time
from typing import Any, Dict, Iterable, List, Optional


class TraceAggregator:
    """Aggregates trace events without retaining unbounded payload data."""

    def __init__(self, max_bytes: int = 1_048_576, max_events: int = 10_000):
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if max_events <= 0:
            raise ValueError("max_events must be positive")

        self.max_bytes = max_bytes
        self.max_events = max_events
        self._lock = threading.RLock()
        self._terminal_outcomes: Dict[str, Dict[str, Any]] = {}
        self._traces: Dict[str, List[Dict[str, Any]]] = {}
        self.audit_records: List[Dict[str, Any]] = []

    def aggregate(
        self,
        run_id: str,
        transition_id: str,
        events: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Aggregate trace events once for a transition.

        Retries for the same transition return the first terminal outcome,
        which prevents duplicate accepted/rejected state under retry.
        """
        self._validate_identifier("run_id", run_id)
        self._validate_identifier("transition_id", transition_id)

        with self._lock:
            existing = self._terminal_outcomes.get(transition_id)
            if existing:
                self._audit(
                    run_id,
                    transition_id,
                    "idempotent",
                    existing["status"],
                    existing.get("reason"),
                )
                return dict(existing)

            outcome = self._aggregate_once(run_id, transition_id, events)
            self._terminal_outcomes[transition_id] = outcome
            self._audit(
                run_id,
                transition_id,
                "terminal",
                outcome["status"],
                outcome.get("reason"),
            )
            return dict(outcome)

    def get_outcome(self, transition_id: str) -> Optional[Dict[str, Any]]:
        outcome = self._terminal_outcomes.get(transition_id)
        return dict(outcome) if outcome else None

    def get_trace(self, transition_id: str) -> Optional[List[Dict[str, Any]]]:
        trace = self._traces.get(transition_id)
        return [dict(event) for event in trace] if trace is not None else None

    def _aggregate_once(
        self,
        run_id: str,
        transition_id: str,
        events: Iterable[Dict[str, Any]],
    ) -> Dict[str, Any]:
        retained: List[Dict[str, Any]] = []
        total_bytes = 0

        for index, event in enumerate(events, start=1):
            if index > self.max_events:
                return self._rejected_outcome(
                    run_id,
                    transition_id,
                    "trace_event_limit",
                    total_bytes,
                    index - 1,
                )

            encoded = self._encode_event(event)
            projected = total_bytes + len(encoded)
            if projected > self.max_bytes:
                return self._rejected_outcome(
                    run_id,
                    transition_id,
                    "trace_memory_limit",
                    total_bytes,
                    index - 1,
                )

            retained.append(dict(event))
            total_bytes = projected

        self._traces[transition_id] = retained
        return {
            "status": "accepted",
            "run_id": run_id,
            "transition_id": transition_id,
            "event_count": len(retained),
            "bytes": total_bytes,
            "timestamp": time.time(),
        }

    def _rejected_outcome(
        self,
        run_id: str,
        transition_id: str,
        reason: str,
        accepted_bytes: int,
        accepted_events: int,
    ) -> Dict[str, Any]:
        self._traces.pop(transition_id, None)
        return {
            "status": "rejected",
            "run_id": run_id,
            "transition_id": transition_id,
            "reason": reason,
            "event_count": accepted_events,
            "bytes": accepted_bytes,
            "timestamp": time.time(),
        }

    def _audit(
        self,
        run_id: str,
        transition_id: str,
        decision: str,
        status: str,
        reason: Optional[str],
    ) -> None:
        self.audit_records.append(
            {
                "decision": decision,
                "status": status,
                "reason": reason,
                "run_ref": self._digest(run_id),
                "transition_ref": self._digest(transition_id),
                "timestamp": time.time(),
            }
        )

    @staticmethod
    def _encode_event(event: Dict[str, Any]) -> bytes:
        try:
            return json.dumps(
                event,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except TypeError as exc:
            raise ValueError("trace events must be JSON serializable") from exc

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _validate_identifier(name: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")
