"""Deployment preflight checks for database migrations."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Dict, Iterable, List, Optional


class RestoreCheckStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class PreflightStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True)
class MigrationMetadata:
    migration_id: str
    description: str
    destructive: bool = False
    irreversible: bool = False

    @property
    def requires_backup(self) -> bool:
        return self.destructive or self.irreversible


@dataclass(frozen=True)
class BackupVerification:
    backup_id: str
    created_at: datetime
    restore_check_status: RestoreCheckStatus

    @property
    def restore_verified(self) -> bool:
        return self.restore_check_status == RestoreCheckStatus.PASSED


@dataclass(frozen=True)
class MigrationPreflightReport:
    status: PreflightStatus
    destructive_migrations: List[str]
    backup_timestamp: Optional[datetime]
    restore_check_status: RestoreCheckStatus
    reasons: List[str]

    @property
    def allowed(self) -> bool:
        return self.status == PreflightStatus.PASSED

    def to_dict(self) -> Dict[str, object]:
        return {
            "status": self.status.value,
            "destructive_migrations": list(self.destructive_migrations),
            "backup_timestamp": (
                self.backup_timestamp.isoformat()
                if self.backup_timestamp
                else None
            ),
            "restore_check_status": self.restore_check_status.value,
            "reasons": list(self.reasons),
        }


class MigrationPreflight:
    def __init__(self, max_backup_age: timedelta = timedelta(hours=24)):
        self.max_backup_age = max_backup_age

    def check(
        self,
        migrations: Iterable[MigrationMetadata],
        latest_backup: Optional[BackupVerification],
        *,
        now: Optional[datetime] = None,
    ) -> MigrationPreflightReport:
        checked_at = now or datetime.now(timezone.utc)
        destructive_ids = [
            migration.migration_id
            for migration in migrations
            if migration.requires_backup
        ]

        if not destructive_ids:
            return MigrationPreflightReport(
                status=PreflightStatus.PASSED,
                destructive_migrations=[],
                backup_timestamp=latest_backup.created_at
                if latest_backup
                else None,
                restore_check_status=latest_backup.restore_check_status
                if latest_backup
                else RestoreCheckStatus.NOT_RUN,
                reasons=[],
            )

        reasons: List[str] = []
        if latest_backup is None:
            reasons.append("missing_recent_verified_backup")
            return self._failed_report(
                destructive_ids,
                None,
                RestoreCheckStatus.NOT_RUN,
                reasons,
            )

        if latest_backup.created_at.tzinfo is None:
            reasons.append("backup_timestamp_must_be_timezone_aware")
        elif checked_at - latest_backup.created_at > self.max_backup_age:
            reasons.append("backup_too_old")

        if not latest_backup.restore_verified:
            reasons.append("backup_restore_not_verified")

        if reasons:
            return self._failed_report(
                destructive_ids,
                latest_backup.created_at,
                latest_backup.restore_check_status,
                reasons,
            )

        return MigrationPreflightReport(
            status=PreflightStatus.PASSED,
            destructive_migrations=destructive_ids,
            backup_timestamp=latest_backup.created_at,
            restore_check_status=latest_backup.restore_check_status,
            reasons=[],
        )

    @staticmethod
    def _failed_report(
        destructive_ids: List[str],
        backup_timestamp: Optional[datetime],
        restore_check_status: RestoreCheckStatus,
        reasons: List[str],
    ) -> MigrationPreflightReport:
        return MigrationPreflightReport(
            status=PreflightStatus.FAILED,
            destructive_migrations=destructive_ids,
            backup_timestamp=backup_timestamp,
            restore_check_status=restore_check_status,
            reasons=reasons,
        )
