import inspect

import pytest

from src.storage import (
    ScopedTaskStateRepository,
    UnscopedTaskStateAccessError,
    UnscopedTaskStateQueryError,
    assert_task_state_sql_scoped,
    postgres_workspace_scope_policy_sql,
)


def test_task_id_collisions_are_isolated_by_workspace():
    repository = ScopedTaskStateRepository()

    repository.put("workspace-a", "task-1", "running", {"owner": "a"})
    repository.put("workspace-b", "task-1", "failed", {"owner": "b"})

    first = repository.get("workspace-a", "task-1")
    second = repository.get("workspace-b", "task-1")

    assert first is not None
    assert second is not None
    assert first.state == "running"
    assert second.state == "failed"
    assert first.payload == {"owner": "a"}
    assert second.payload == {"owner": "b"}


def test_writes_to_same_workspace_and_task_increment_version_only_there():
    repository = ScopedTaskStateRepository()

    repository.put("workspace-a", "task-1", "pending")
    updated = repository.put("workspace-a", "task-1", "running")
    other = repository.put("workspace-b", "task-1", "pending")

    assert updated.version == 2
    assert other.version == 1
    assert repository.get("workspace-a", "task-1").state == "running"
    assert repository.get("workspace-b", "task-1").state == "pending"


def test_delete_requires_workspace_and_does_not_remove_colliding_task_ids():
    repository = ScopedTaskStateRepository()
    repository.put("workspace-a", "task-1", "running")
    repository.put("workspace-b", "task-1", "running")

    assert repository.delete("workspace-a", "task-1")

    assert repository.get("workspace-a", "task-1") is None
    assert repository.get("workspace-b", "task-1") is not None


def test_workspace_listing_only_returns_scoped_records():
    repository = ScopedTaskStateRepository()
    repository.put("workspace-a", "task-1", "pending")
    repository.put("workspace-a", "task-2", "running")
    repository.put("workspace-b", "task-1", "failed")

    listed = repository.list_for_workspace("workspace-a")

    assert [record.task_id for record in listed] == ["task-1", "task-2"]
    assert {record.workspace_id for record in listed} == {"workspace-a"}


def test_exists_and_count_are_workspace_scoped():
    repository = ScopedTaskStateRepository()
    repository.put("workspace-a", "task-1", "pending")
    repository.put("workspace-a", "task-2", "running")
    repository.put("workspace-b", "task-1", "failed")

    assert repository.exists("workspace-a", "task-1")
    assert not repository.exists("workspace-a", "missing")
    assert repository.count_for_workspace("workspace-a") == 2
    assert repository.count_for_workspace("workspace-b") == 1


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("get_by_task_id", ("task-1",)),
        ("delete_by_task_id", ("task-1",)),
        ("list_all", ()),
    ],
)
def test_direct_unscoped_helpers_are_blocked(method_name, args):
    repository = ScopedTaskStateRepository()

    with pytest.raises(UnscopedTaskStateAccessError):
        getattr(repository, method_name)(*args)


def test_static_contract_requires_workspace_scope_for_task_id_methods():
    blocked_legacy_methods = {"get_by_task_id", "delete_by_task_id"}

    methods = inspect.getmembers(
        ScopedTaskStateRepository, inspect.isfunction
    )
    for name, method in methods:
        if name.startswith("_") or name in blocked_legacy_methods:
            continue

        parameters = inspect.signature(method).parameters
        if "task_id" in parameters:
            assert "workspace_id" in parameters


def test_scope_and_task_ids_must_not_be_blank():
    repository = ScopedTaskStateRepository()

    with pytest.raises(ValueError, match="workspace_id"):
        repository.get(" ", "task-1")

    with pytest.raises(ValueError, match="task_id"):
        repository.get("workspace-a", "")


def test_records_are_copied_on_write_and_export():
    repository = ScopedTaskStateRepository()
    payload = {"nested": {"count": 1}}

    record = repository.put("workspace-a", "task-1", "running", payload)
    payload["nested"]["count"] = 2
    exported = record.to_dict()
    exported["payload"]["nested"]["count"] = 3

    stored = repository.get("workspace-a", "task-1")
    assert stored.payload == {"nested": {"count": 1}}


def test_postgres_rls_policy_uses_workspace_setting_for_read_and_write():
    sql = postgres_workspace_scope_policy_sql()

    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FORCE ROW LEVEL SECURITY" in sql
    assert "USING (" in sql
    assert "WITH CHECK (" in sql
    assert (
        "workspace_id = current_setting('app.current_workspace_id', true)"
        in sql
    )


def test_postgres_rls_policy_rejects_unsafe_identifiers():
    with pytest.raises(ValueError):
        postgres_workspace_scope_policy_sql(
            table_name="task_state; drop table users"
        )


@pytest.mark.parametrize(
    "sql",
    [
        "select * from task_state where workspace_id = %s and task_id = %s",
        (
            "update task_state set state = %s "
            "where task_id = %s and workspace_id = %s"
        ),
        "delete from task_state where workspace_id = %s and task_id = %s",
        (
            "insert into task_state "
            "(workspace_id, task_id, state) values (%s, %s, %s)"
        ),
    ],
)
def test_task_state_sql_guard_allows_workspace_scoped_dml(sql):
    assert assert_task_state_sql_scoped(sql) == sql


@pytest.mark.parametrize(
    "sql",
    [
        "select * from task_state where task_id = %s",
        "select workspace_id, task_id from task_state where task_id = %s",
        "update task_state set state = %s where task_id = %s",
        "delete from task_state where task_id = %s",
        "insert into task_state (task_id, state) values (%s, %s)",
    ],
)
def test_task_state_sql_guard_blocks_unscoped_dml(sql):
    with pytest.raises(UnscopedTaskStateQueryError):
        assert_task_state_sql_scoped(sql)


def test_task_state_sql_guard_ignores_unrelated_sql():
    sql = "select * from agents where task_id = %s"

    assert assert_task_state_sql_scoped(sql) == sql
