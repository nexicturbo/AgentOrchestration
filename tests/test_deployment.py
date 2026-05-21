import pytest

from src.orchestrator.deployment import (
    DeploymentMigrationGate,
    MigrationCheck,
    MigrationFailed,
    MigrationStatus,
    ReleasePlan,
)


def test_migrations_complete_before_new_version_receives_traffic():
    gate = DeploymentMigrationGate()
    plan = ReleasePlan(
        previous_version="v1",
        target_version="v2",
        migrations=(MigrationCheck("add_task_state_index"),),
    )
    events = []

    def run_migrations(release):
        events.append(("migration", release.target_version))

    decision = gate.evaluate_rollout(plan, run_migrations)

    assert events == [("migration", "v2")]
    assert decision.allowed
    assert decision.migration_status is MigrationStatus.SUCCEEDED
    assert decision.traffic_version == "v2"


def test_migration_failure_stops_rollout_and_keeps_prior_version_serving():
    gate = DeploymentMigrationGate()
    plan = ReleasePlan(
        previous_version="v1",
        target_version="v2",
        migrations=(MigrationCheck("backfill_task_state"),),
    )

    def run_migrations(_release):
        raise MigrationFailed("backfill_task_state failed")

    decision = gate.evaluate_rollout(plan, run_migrations)

    assert not decision.allowed
    assert decision.migration_status is MigrationStatus.FAILED
    assert decision.serving_version == "v1"
    assert decision.traffic_version == "v1"
    assert "backfill_task_state failed" in decision.migration_error


def test_reversible_release_blocks_forward_only_migrations_before_rollout():
    gate = DeploymentMigrationGate()
    plan = ReleasePlan(
        previous_version="v1",
        target_version="v2",
        migrations=(
            MigrationCheck(
                "drop_legacy_task_state",
                backward_compatible=False,
            ),
        ),
        reversible=True,
    )

    def run_migrations(_release):
        pytest.fail("migration job should not run for incompatible releases")

    decision = gate.evaluate_rollout(plan, run_migrations)

    assert not decision.allowed
    assert decision.migration_status is MigrationStatus.INCOMPATIBLE
    assert decision.serving_version == "v1"
    assert decision.traffic_version == "v1"
    assert decision.compatibility.issues == [
        "drop_legacy_task_state is not backward compatible"
    ]
