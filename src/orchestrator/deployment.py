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
class RolloutDecision:
    allowed: bool
    serving_version: str
    traffic_version: str
    migration_status: MigrationStatus
    compatibility: CompatibilityReport
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
        if not compatibility.compatible:
            return RolloutDecision(
                allowed=False,
                serving_version=plan.previous_version,
                traffic_version=plan.previous_version,
                migration_status=MigrationStatus.INCOMPATIBLE,
                compatibility=compatibility,
            )

        if not plan.migrations:
            return RolloutDecision(
                allowed=True,
                serving_version=plan.target_version,
                traffic_version=plan.target_version,
                migration_status=MigrationStatus.SKIPPED,
                compatibility=compatibility,
            )

        try:
            run_migrations(plan)
        except Exception as exc:
            return RolloutDecision(
                allowed=False,
                serving_version=plan.previous_version,
                traffic_version=plan.previous_version,
                migration_status=MigrationStatus.FAILED,
                compatibility=compatibility,
                migration_error=str(exc),
            )

        return RolloutDecision(
            allowed=True,
            serving_version=plan.target_version,
            traffic_version=plan.target_version,
            migration_status=MigrationStatus.SUCCEEDED,
            compatibility=compatibility,
        )
