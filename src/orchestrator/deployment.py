"""Deployment rollout safety gates."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, List, Optional, Sequence


class MigrationStatus(str, Enum):
    PENDING = "pending"
    SKIPPED = "skipped"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True)
class MigrationCheck:
    name: str
    backward_compatible: bool = True
    reversible: bool = True


@dataclass(frozen=True)
class ReleasePlan:
    previous_version: str
    target_version: str
    migrations: Sequence[MigrationCheck] = field(default_factory=tuple)
    reversible: bool = True


@dataclass(frozen=True)
class CompatibilityReport:
    compatible: bool
    issues: List[str]


@dataclass(frozen=True)
class RolloutAuditEvent:
    event: str
    decision: str
    serving_version: str
    target_version: str
    reason: Optional[str] = None
    migration_count: int = 0


@dataclass(frozen=True)
class RolloutDecision:
    allowed: bool
    serving_version: str
    traffic_version: str
    migration_status: MigrationStatus
    compatibility: CompatibilityReport
    audit_events: Sequence[RolloutAuditEvent] = field(default_factory=tuple)
    migration_error: Optional[str] = None


class MigrationFailed(RuntimeError):
    """Raised when a migration job fails."""


MigrationRunner = Callable[[ReleasePlan], None]


class DeploymentMigrationGate:
    """Runs release migrations before allowing traffic onto a new version."""

    def check_compatibility(self, plan: ReleasePlan) -> CompatibilityReport:
        issues: List[str] = []
        for migration in plan.migrations:
            if not migration.backward_compatible:
                issues.append(f"{migration.name} is not backward compatible")
            if plan.reversible and not migration.reversible:
                issues.append(f"{migration.name} is not reversible")
        return CompatibilityReport(compatible=not issues, issues=issues)

    def evaluate_rollout(
        self,
        plan: ReleasePlan,
        run_migrations: MigrationRunner,
    ) -> RolloutDecision:
        compatibility = self.check_compatibility(plan)
        compatibility_reason = (
            None if compatibility.compatible else "incompatible_migration"
        )
        audit_events: List[RolloutAuditEvent] = [
            RolloutAuditEvent(
                event="compatibility_checked",
                decision="passed" if compatibility.compatible else "blocked",
                serving_version=plan.previous_version,
                target_version=plan.target_version,
                reason=compatibility_reason,
                migration_count=len(plan.migrations),
            )
        ]
        if not compatibility.compatible:
            audit_events.append(
                RolloutAuditEvent(
                    event="rollout_blocked",
                    decision="keep_prior_version",
                    serving_version=plan.previous_version,
                    target_version=plan.target_version,
                    reason="incompatible_migration",
                    migration_count=len(plan.migrations),
                )
            )
            return RolloutDecision(
                allowed=False,
                serving_version=plan.previous_version,
                traffic_version=plan.previous_version,
                migration_status=MigrationStatus.INCOMPATIBLE,
                compatibility=compatibility,
                audit_events=tuple(audit_events),
            )

        if not plan.migrations:
            audit_events.append(
                RolloutAuditEvent(
                    event="traffic_shifted",
                    decision="release_without_migrations",
                    serving_version=plan.target_version,
                    target_version=plan.target_version,
                    reason="no_migrations",
                    migration_count=0,
                )
            )
            return RolloutDecision(
                allowed=True,
                serving_version=plan.target_version,
                traffic_version=plan.target_version,
                migration_status=MigrationStatus.SKIPPED,
                compatibility=compatibility,
                audit_events=tuple(audit_events),
            )

        try:
            audit_events.append(
                RolloutAuditEvent(
                    event="migration_job_started",
                    decision="hold_new_traffic",
                    serving_version=plan.previous_version,
                    target_version=plan.target_version,
                    reason="run_migrations_before_rollout",
                    migration_count=len(plan.migrations),
                )
            )
            run_migrations(plan)
        except Exception as exc:
            audit_events.append(
                RolloutAuditEvent(
                    event="rollout_blocked",
                    decision="keep_prior_version",
                    serving_version=plan.previous_version,
                    target_version=plan.target_version,
                    reason="migration_failed",
                    migration_count=len(plan.migrations),
                )
            )
            return RolloutDecision(
                allowed=False,
                serving_version=plan.previous_version,
                traffic_version=plan.previous_version,
                migration_status=MigrationStatus.FAILED,
                compatibility=compatibility,
                audit_events=tuple(audit_events),
                migration_error=str(exc),
            )

        audit_events.append(
            RolloutAuditEvent(
                event="traffic_shifted",
                decision="migrations_succeeded",
                serving_version=plan.target_version,
                target_version=plan.target_version,
                reason="migration_gate_passed",
                migration_count=len(plan.migrations),
            )
        )
        return RolloutDecision(
            allowed=True,
            serving_version=plan.target_version,
            traffic_version=plan.target_version,
            migration_status=MigrationStatus.SUCCEEDED,
            compatibility=compatibility,
            audit_events=tuple(audit_events),
        )
