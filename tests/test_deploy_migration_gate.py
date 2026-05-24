from src.orchestrator.deploy import (
    DeploymentOrchestrator,
    MigrationStep,
    ReleasePlan,
)


def test_migrations_complete_before_rollout_receives_traffic():
    events = []
    orchestrator = DeploymentOrchestrator()

    def migrate():
        events.append("migration")
        return True

    def rollout():
        assert events == ["migration"]
        events.append("rollout")
        return True

    outcome = orchestrator.deploy(
        ReleasePlan(
            previous_version="v1",
            next_version="v2",
            migrations=[MigrationStep("add-column", migrate)],
            rollout=rollout,
        )
    )

    assert outcome.status == "rolled_out"
    assert outcome.serving_version == "v2"
    assert outcome.traffic_shifted
    assert events == ["migration", "rollout"]


def test_migration_failure_stops_rollout_and_keeps_prior_version():
    events = []
    orchestrator = DeploymentOrchestrator()

    def fail_migration():
        events.append("migration")
        return False

    def rollout():
        events.append("rollout")
        return True

    outcome = orchestrator.deploy(
        ReleasePlan(
            previous_version="v1",
            next_version="v2",
            migrations=[MigrationStep("bad-ddl", fail_migration)],
            rollout=rollout,
        )
    )

    assert outcome.status == "migration_failed"
    assert outcome.serving_version == "v1"
    assert not outcome.traffic_shifted
    assert events == ["migration"]


def test_backward_incompatible_migration_blocks_reversible_rollout():
    events = []
    orchestrator = DeploymentOrchestrator()

    outcome = orchestrator.deploy(
        ReleasePlan(
            previous_version="v1",
            next_version="v2",
            migrations=[
                MigrationStep(
                    "drop-column",
                    lambda: events.append("migration") or True,
                    backward_compatible=False,
                )
            ],
            rollout=lambda: events.append("rollout") or True,
        )
    )

    assert outcome.status == "blocked"
    assert outcome.compatibility == {"drop-column": False}
    assert outcome.serving_version == "v1"
    assert not outcome.traffic_shifted
    assert events == []


def test_audit_records_do_not_copy_private_migration_metadata():
    orchestrator = DeploymentOrchestrator()
    migration = MigrationStep(
        "safe-ddl",
        lambda: True,
        metadata={"token": "do-not-copy"},
    )

    orchestrator.deploy(
        ReleasePlan(
            previous_version="v1",
            next_version="v2",
            migrations=[migration],
            rollout=lambda: True,
        )
    )

    audit = orchestrator.audit_records()
    assert audit[-1]["action"] == "traffic_shifted"
    assert "do-not-copy" not in str(audit)
