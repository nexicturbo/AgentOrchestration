import pytest

from src.orchestrator.checkpoints import (
    CheckpointConflictError,
    CheckpointStore,
    checkpoint_digest,
    checkpoint_key,
)


def test_retry_checkpoint_write_is_idempotent():
    store = CheckpointStore()
    payload = {"cursor": "batch-7", "offset": 42}

    first = store.write("task-1", "extract", 2, payload)
    retry_after_timeout = store.write("task-1", "extract", 2, payload)

    assert first is retry_after_timeout
    assert first.key == "task-1/extract/2"
    assert list(store.keys()) == ["task-1/extract/2"]
    assert len(store) == 1


def test_digest_mismatch_for_same_checkpoint_key_fails_loudly():
    store = CheckpointStore()
    store.write("task-1", "extract", 0, {"offset": 10})

    with pytest.raises(CheckpointConflictError):
        store.write("task-1", "extract", 0, {"offset": 11})


def test_provided_digest_must_match_checkpoint_payload():
    store = CheckpointStore()

    with pytest.raises(ValueError, match="does not match"):
        store.write(
            "task-1",
            "extract",
            0,
            {"offset": 10},
            digest="bad-digest",
        )


def test_resume_uses_latest_checkpoint_for_task_step():
    store = CheckpointStore()
    store.write("task-1", "extract", 0, {"offset": 10})
    store.write("task-1", "extract", 1, {"offset": 20})
    store.write("task-1", "load", 0, {"rows": 5})

    latest = store.latest_for_task("task-1", "extract")

    assert latest is not None
    assert latest.attempt == 1
    assert latest.payload == {"offset": 20}


def test_deterministic_key_and_digest_are_stable_for_equivalent_payloads():
    left = {"z": 1, "a": ["same", 2]}
    right = {"a": ["same", 2], "z": 1}

    assert checkpoint_key("task-1", "step-a", "3") == "task-1/step-a/3"
    assert checkpoint_digest(left) == checkpoint_digest(right)
