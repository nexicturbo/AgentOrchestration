from datetime import datetime, timedelta, timezone

from src.common.migration_preflight import (
    BackupVerification,
    MigrationMetadata,
    MigrationPreflight,
    PreflightStatus,
    RestoreCheckStatus,
)


NOW = datetime(2026, 5, 21, 10, 30, tzinfo=timezone.utc)


def test_destructive_migration_fails_without_backup():
    report = MigrationPreflight().check(
        [
            MigrationMetadata(
                "drop-users-email",
                "drop column",
                destructive=True,
            )
        ],
        latest_backup=None,
        now=NOW,
    )

    assert not report.allowed
    assert report.status == PreflightStatus.FAILED
    assert report.destructive_migrations == ["drop-users-email"]
    assert report.backup_timestamp is None
    assert report.restore_check_status == RestoreCheckStatus.NOT_RUN
    assert report.reasons == ["missing_recent_verified_backup"]


def test_destructive_migration_fails_with_stale_verified_backup():
    backup = BackupVerification(
        backup_id="backup-1",
        created_at=NOW - timedelta(hours=25),
        restore_check_status=RestoreCheckStatus.PASSED,
    )

    report = MigrationPreflight(max_backup_age=timedelta(hours=24)).check(
        [
            MigrationMetadata(
                "rewrite-ledger",
                "rewrite data",
                irreversible=True,
            )
        ],
        latest_backup=backup,
        now=NOW,
    )

    assert not report.allowed
    assert report.backup_timestamp == backup.created_at
    assert report.restore_check_status == RestoreCheckStatus.PASSED
    assert report.reasons == ["backup_too_old"]


def test_destructive_migration_fails_when_restore_check_failed():
    backup = BackupVerification(
        backup_id="backup-2",
        created_at=NOW - timedelta(minutes=10),
        restore_check_status=RestoreCheckStatus.FAILED,
    )

    report = MigrationPreflight().check(
        [
            MigrationMetadata(
                "truncate-events",
                "truncate table",
                destructive=True,
            )
        ],
        latest_backup=backup,
        now=NOW,
    )

    assert not report.allowed
    assert report.restore_check_status == RestoreCheckStatus.FAILED
    assert report.reasons == ["backup_restore_not_verified"]


def test_destructive_migration_passes_with_recent_restored_backup():
    backup = BackupVerification(
        backup_id="backup-3",
        created_at=NOW - timedelta(minutes=30),
        restore_check_status=RestoreCheckStatus.PASSED,
    )

    report = MigrationPreflight().check(
        [
            MigrationMetadata("add-index", "safe index"),
            MigrationMetadata(
                "drop-legacy",
                "drop legacy table",
                destructive=True,
            ),
        ],
        latest_backup=backup,
        now=NOW,
    )

    assert report.allowed
    assert report.status == PreflightStatus.PASSED
    assert report.destructive_migrations == ["drop-legacy"]
    assert report.backup_timestamp == backup.created_at
    assert report.restore_check_status == RestoreCheckStatus.PASSED
    assert report.reasons == []


def test_non_destructive_migration_reports_backup_status_without_gate():
    report = MigrationPreflight().check(
        [MigrationMetadata("add-column", "safe additive change")],
        latest_backup=None,
        now=NOW,
    )

    assert report.allowed
    assert report.destructive_migrations == []
    assert report.restore_check_status == RestoreCheckStatus.NOT_RUN
    assert report.to_dict() == {
        "status": "passed",
        "destructive_migrations": [],
        "backup_timestamp": None,
        "restore_check_status": "not_run",
        "reasons": [],
    }


def test_naive_backup_timestamp_fails_closed_for_destructive_migration():
    backup = BackupVerification(
        backup_id="backup-4",
        created_at=datetime(2026, 5, 21, 10, 0),
        restore_check_status=RestoreCheckStatus.PASSED,
    )

    report = MigrationPreflight().check(
        [
            MigrationMetadata(
                "drop-old-state",
                "drop old state",
                destructive=True,
            )
        ],
        latest_backup=backup,
        now=NOW,
    )

    assert not report.allowed
    assert report.reasons == ["backup_timestamp_must_be_timezone_aware"]
