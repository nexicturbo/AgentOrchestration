import pytest

from src.orchestrator.workflow import (
    WorkflowDefinitionError,
    WorkflowManager,
    WorkflowStep,
)


def test_yaml_import_registration_rejects_duplicate_node_ids():
    manager = WorkflowManager()
    root = """
name: duplicate-import
imports:
  - shared
steps:
  - id: build
    handler: build
"""

    def resolver(name):
        assert name == "shared"
        return {
            "steps": [
                {"id": "build", "handler": "shared_build"},
            ]
        }

    with pytest.raises(WorkflowDefinitionError) as exc_info:
        manager.create_workflow_from_yaml(root, import_resolver=resolver)

    assert "Duplicate workflow node id: build" in str(exc_info.value)
    assert exc_info.value.audit_record == {
        "event": "workflow_registration_rejected",
        "decision": "duplicate_node_id",
        "node_id": "build",
        "first_source": "shared",
        "duplicate_source": "root",
    }
    assert manager.audit_records() == [exc_info.value.audit_record]
    assert manager.list_workflows() == []


def test_file_based_yaml_import_rejects_duplicate_before_storage(tmp_path):
    imported = tmp_path / "imported.yml"
    imported.write_text(
        """
steps:
  - id: transform
    handler: imported_transform
"""
    )
    root = tmp_path / "workflow.yml"
    root.write_text(
        """
name: file-import
imports:
  - imported.yml
nodes:
  - id: transform
    handler: local_transform
"""
    )

    manager = WorkflowManager()

    with pytest.raises(WorkflowDefinitionError) as exc_info:
        manager.load_workflow_from_yaml(str(root))

    assert exc_info.value.audit_record["decision"] == "duplicate_node_id"
    assert exc_info.value.audit_record["node_id"] == "transform"
    assert "imported.yml" in exc_info.value.audit_record["first_source"]
    assert exc_info.value.audit_record["duplicate_source"] == "root"
    assert manager.list_workflows() == []


def test_unique_yaml_imports_register_workflow_with_explicit_ids():
    manager = WorkflowManager()
    calls = []

    workflow = manager.create_workflow_from_definition(
        {
            "name": "safe-import",
            "imports": ["shared"],
            "steps": [{"id": "deploy", "handler": "deploy"}],
        },
        handlers={
            "prepare": lambda: calls.append("prepare"),
            "deploy": lambda: calls.append("deploy"),
        },
        import_resolver=lambda name: {
            "steps": [{"id": "prepare", "handler": "prepare"}],
        },
    )

    assert [step.id for step in workflow.steps] == ["prepare", "deploy"]
    assert manager.execute_workflow(workflow.id)
    assert calls == ["prepare", "deploy"]


def test_manual_add_step_rejects_duplicate_id():
    workflow = WorkflowManager().create_workflow("manual")
    workflow.add_step(WorkflowStep("first", lambda: None, step_id="same"))

    with pytest.raises(WorkflowDefinitionError) as exc_info:
        workflow.add_step(WorkflowStep("second", lambda: None, step_id="same"))

    assert exc_info.value.audit_record["decision"] == "duplicate_node_id"
