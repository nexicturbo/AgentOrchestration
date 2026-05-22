import csv
import io
import json

import pytest

from src.common.export_policy import (
    UnclassifiedExportField,
    export_tasks_csv,
    export_tasks_json,
    render_task_ui_view,
    serialize_task_for_export,
)


def task_record():
    return {
        "task_id": "task-1",
        "workspace_id": "workspace-a",
        "status": "completed",
        "created_at": "2026-05-22T09:00:00Z",
        "updated_at": "2026-05-22T09:01:00Z",
        "metadata": {
            "owner": "automation",
            "api_key": "api-key-do-not-export",
            "nested": {
                "refresh_token": "refresh-do-not-export",
                "safe": "visible",
            },
        },
        "result": {
            "summary": "finished",
            "credentials": {
                "password": "do-not-export",
                "note": "hidden sibling only",
            },
            "details": {
                "password": "nested-do-not-export",
                "note": "visible sibling",
            },
        },
        "raw_payload": {"secret": "raw-do-not-export"},
        "internal_notes": "operator-only",
        "debug_context": {"authorization": "Bearer hidden"},
    }


def test_json_export_uses_shared_redaction_policy():
    exported = json.loads(export_tasks_json([task_record()]))

    assert exported == [serialize_task_for_export(task_record())]
    assert "raw_payload" not in exported[0]
    assert "internal_notes" not in exported[0]
    assert "debug_context" not in exported[0]
    assert exported[0]["metadata"]["api_key"] == "[REDACTED]"
    assert exported[0]["metadata"]["nested"]["refresh_token"] == "[REDACTED]"
    assert exported[0]["result"]["credentials"] == "[REDACTED]"
    assert exported[0]["result"]["details"]["password"] == "[REDACTED]"
    assert exported[0]["result"]["details"]["note"] == "visible sibling"


def test_csv_export_uses_shared_redaction_policy():
    exported = export_tasks_csv([task_record()])
    rows = list(csv.DictReader(io.StringIO(exported)))

    assert rows[0]["task_id"] == "task-1"
    assert "raw-do-not-export" not in exported
    assert "operator-only" not in exported
    assert "api-key-do-not-export" not in exported
    assert "refresh-do-not-export" not in exported
    assert "do-not-export" not in exported
    assert "[REDACTED]" in rows[0]["metadata"]
    assert "[REDACTED]" in rows[0]["result"]


def test_ui_view_uses_shared_redaction_policy():
    rendered = render_task_ui_view(task_record())

    assert rendered == serialize_task_for_export(task_record())
    assert "raw_payload" not in rendered
    assert rendered["metadata"]["api_key"] == "[REDACTED]"
    assert rendered["result"]["credentials"] == "[REDACTED]"
    assert rendered["result"]["details"]["password"] == "[REDACTED]"


def test_all_formats_have_matching_public_fields():
    record = task_record()
    json_row = json.loads(export_tasks_json([record]))[0]
    csv_row = list(csv.DictReader(io.StringIO(export_tasks_csv([record]))))[0]
    ui_row = render_task_ui_view(record)

    assert set(json_row) == set(ui_row)
    assert set(csv_row) == {
        "task_id",
        "workspace_id",
        "status",
        "created_at",
        "updated_at",
        "metadata",
        "result",
    }


def test_unknown_export_field_requires_policy_classification():
    record = task_record()
    record["customer_email"] = "sensitive@example.com"

    with pytest.raises(UnclassifiedExportField, match="customer_email"):
        export_tasks_json([record])

    with pytest.raises(UnclassifiedExportField, match="customer_email"):
        export_tasks_csv([record])

    with pytest.raises(UnclassifiedExportField, match="customer_email"):
        render_task_ui_view(record)


def test_redaction_does_not_mutate_original_record():
    record = task_record()

    serialize_task_for_export(record)

    assert record["metadata"]["api_key"] == "api-key-do-not-export"
    assert record["result"]["credentials"]["password"] == "do-not-export"
    assert record["result"]["details"]["password"] == "nested-do-not-export"
