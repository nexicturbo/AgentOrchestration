import pytest

from src.orchestrator.deployment import MigrationRolloutGate


def test_pending_required_migration_blocks_candidate_traffic():
    decision = MigrationRolloutGate().evaluate({
        "migrations": [{
            "id": "20260521_add_agent_runs",
            "status": "pending",
            "required": True,
            "backward_compatible": True,
        }],
    })

    assert not decision.allowed
    assert not decision.candidate_receives_traffic
    assert decision.prior_version_serving
    assert decision.reason == (
        "migration has not completed: 20260521_add_agent_runs"
    )


def test_failed_required_migration_keeps_prior_version_serving():
    decision = MigrationRolloutGate().evaluate({
        "migrations": [{
            "id": "20260521_backfill_runs",
            "status": "failed",
            "backward_compatible": True,
        }],
    })

    assert not decision.allowed
    assert decision.prior_version_serving
    assert decision.reason == "migration failed: 20260521_backfill_runs"


@pytest.mark.parametrize("compatibility", [None, False])
def test_incompatible_migration_blocks_before_running_commands(compatibility):
    called = False

    def runner(migration):
        nonlocal called
        called = True
        return True

    decision = MigrationRolloutGate().evaluate(
        {
            "migrations": [{
                "id": "20260521_drop_legacy_status",
                "status": "pending",
                "backward_compatible": compatibility,
                "command": "python manage.py migrate --database prod",
            }],
        },
        migration_runner=runner,
    )

    assert not decision.allowed
    assert decision.reason.startswith(
        "migration is not marked backward compatible"
    )
    assert not called


def test_runner_completes_migrations_before_traffic_release():
    completed = []

    def runner(migration):
        completed.append(migration["id"])
        migration["status"] = "completed"
        return True

    decision = MigrationRolloutGate().evaluate(
        {
            "migrations": [{
                "id": "20260521_add_safe_index",
                "status": "pending",
                "backward_compatible": True,
            }],
        },
        migration_runner=runner,
    )

    assert decision.allowed
    assert decision.candidate_receives_traffic
    assert not decision.prior_version_serving
    assert completed == ["20260521_add_safe_index"]


def test_successful_rollout_requires_completed_compatible_migrations():
    decision = MigrationRolloutGate().evaluate({
        "migrations": [{
            "id": "20260521_create_agent_events",
            "status": "completed",
            "backward_compatible": True,
            "command": "contains secret",
        }],
    })

    assert decision.allowed
    assert decision.reason == "required migrations complete"
    assert decision.migrations_checked == [{
        "id": "20260521_create_agent_events",
        "status": "completed",
        "backward_compatible": True,
    }]
