"""Shared task export redaction policy."""

import csv
import io
import json
from copy import deepcopy
from typing import Any, Dict, Iterable, Mapping


class UnclassifiedExportField(ValueError):
    """Raised when an export field has no explicit policy classification."""


PUBLIC_FIELDS = {
    "task_id",
    "workspace_id",
    "status",
    "created_at",
    "updated_at",
    "metadata",
    "result",
}

OMITTED_FIELDS = {
    "raw_payload",
    "internal_notes",
    "debug_context",
}

SENSITIVE_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "session",
    "token",
}

CSV_COLUMNS = [
    "task_id",
    "workspace_id",
    "status",
    "created_at",
    "updated_at",
    "metadata",
    "result",
]


def serialize_task_for_export(record: Mapping[str, Any]) -> Dict[str, Any]:
    unknown = set(record) - PUBLIC_FIELDS - OMITTED_FIELDS
    if unknown:
        raise UnclassifiedExportField(
            "unclassified export field: " + sorted(unknown)[0]
        )

    serialized: Dict[str, Any] = {}
    for field in CSV_COLUMNS:
        if field in record:
            serialized[field] = _redact_sensitive_values(record[field])
    return serialized


def export_tasks_json(records: Iterable[Mapping[str, Any]]) -> str:
    payload = [serialize_task_for_export(record) for record in records]
    return json.dumps(payload, sort_keys=True)


def export_tasks_csv(records: Iterable[Mapping[str, Any]]) -> str:
    rows = [serialize_task_for_export(record) for record in records]
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=CSV_COLUMNS,
        extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                column: _format_csv_value(row.get(column, ""))
                for column in CSV_COLUMNS
            }
        )
    return buffer.getvalue()


def render_task_ui_view(record: Mapping[str, Any]) -> Dict[str, Any]:
    return serialize_task_for_export(record)


def _redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: Dict[str, Any] = {}
        for key, nested in value.items():
            if _is_sensitive_key(str(key)):
                redacted[key] = "[REDACTED]"
            else:
                redacted[key] = _redact_sensitive_values(nested)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value]
    return deepcopy(value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(part in normalized for part in SENSITIVE_KEYS)


def _format_csv_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)
