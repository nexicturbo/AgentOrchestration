from concurrent.futures import ThreadPoolExecutor

from src.orchestrator.engine import OrchestrationEngine


async def noop_hook(*args, **kwargs):
    return None


def test_valid_plugin_manifest_registers_hooks_after_validation():
    engine = OrchestrationEngine()

    record = engine.load_plugin_manifest(
        {
            "name": "audit-hooks",
            "version": "1.0.0",
            "hooks": {"pre_execute": [noop_hook], "on_error": [noop_hook]},
        }
    )

    assert record.status == "loaded"
    assert record.hooks_registered == 2
    assert len(engine._hooks["pre_execute"]) == 1
    assert len(engine._hooks["on_error"]) == 1


def test_invalid_plugin_manifest_fails_before_loading_hooks():
    engine = OrchestrationEngine()

    record = engine.load_plugin_manifest(
        {
            "name": "broken-hooks",
            "version": "1.0.0",
            "hooks": {
                "pre_execute": ["not-callable"],
                "on_error": [noop_hook],
            },
        }
    )

    assert record.status == "rejected"
    assert "non-callable" in record.reason
    assert record.hooks_registered == 0
    assert engine._hooks["pre_execute"] == []
    assert engine._hooks["on_error"] == []


def test_duplicate_plugin_manifest_load_is_idempotent():
    engine = OrchestrationEngine()
    manifest = {
        "name": "audit-hooks",
        "version": "1.0.0",
        "hooks": {"pre_execute": [noop_hook]},
    }

    first = engine.load_plugin_manifest(manifest)
    second = engine.load_plugin_manifest(manifest)

    assert first == second
    assert len(engine._hooks["pre_execute"]) == 1


def test_concurrent_invalid_plugin_manifest_does_not_leave_stale_hooks():
    engine = OrchestrationEngine()
    manifest = {
        "name": "broken-hooks",
        "version": "1.0.0",
        "hooks": {"post_execute": [object()]},
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(
            executor.map(
                lambda _: engine.load_plugin_manifest(manifest),
                range(8),
            )
        )

    assert {record.status for record in records} == {"rejected"}
    assert engine._hooks["post_execute"] == []
    records_by_plugin = engine.plugin_load_records()
    assert records_by_plugin["broken-hooks@1.0.0"].status == "rejected"


def test_concurrent_valid_plugin_manifest_records_one_terminal_load():
    engine = OrchestrationEngine()
    manifest = {
        "name": "audit-hooks",
        "version": "1.0.0",
        "hooks": {"on_complete": [noop_hook]},
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        records = list(
            executor.map(
                lambda _: engine.load_plugin_manifest(manifest),
                range(8),
            )
        )

    assert {record.status for record in records} == {"loaded"}
    assert len(engine._hooks["on_complete"]) == 1
    assert engine.plugin_load_records()["audit-hooks@1.0.0"].status == "loaded"
