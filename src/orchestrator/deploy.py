"""Deployment sequencing helpers."""

import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class MigrationStep:
    name: str
    run: Callable[[], bool]
    backward_compatible: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReleasePlan:
    previous_version: str
    next_version: str
    migrations: List[MigrationStep]
    rollout: Callable[[], bool]
    require_backward_compatible: bool = True


@dataclass
class DeploymentOutcome:
    status: str
    serving_version: str
    traffic_shifted: bool
    reason: str
    compatibility: Dict[str, bool]


class DeploymentOrchestrator:
    def __init__(self):
        self._audit: List[Dict[str, Any]] = []

    def compatibility_report(self, plan: ReleasePlan) -> Dict[str, bool]:
        return {
            migration.name: migration.backward_compatible
            for migration in plan.migrations
        }

    def deploy(self, plan: ReleasePlan) -> DeploymentOutcome:
        compatibility = self.compatibility_report(plan)
        has_incompatible_migration = not all(compatibility.values())
        if plan.require_backward_compatible and has_incompatible_migration:
            self._record(
                action="migration_compatibility_rejected",
                version=plan.previous_version,
                reason="migration is not backward compatible",
            )
            return DeploymentOutcome(
                status="blocked",
                serving_version=plan.previous_version,
                traffic_shifted=False,
                reason="migration is not backward compatible",
                compatibility=compatibility,
            )

        for migration in plan.migrations:
            self._record(
                action="migration_started",
                version=plan.previous_version,
                reason=migration.name,
            )
            if not migration.run():
                self._record(
                    action="migration_failed",
                    version=plan.previous_version,
                    reason=migration.name,
                )
                return DeploymentOutcome(
                    status="migration_failed",
                    serving_version=plan.previous_version,
                    traffic_shifted=False,
                    reason=migration.name,
                    compatibility=compatibility,
                )
            self._record(
                action="migration_completed",
                version=plan.previous_version,
                reason=migration.name,
            )

        if not plan.rollout():
            self._record(
                action="rollout_failed",
                version=plan.previous_version,
                reason="application rollout failed",
            )
            return DeploymentOutcome(
                status="rollout_failed",
                serving_version=plan.previous_version,
                traffic_shifted=False,
                reason="application rollout failed",
                compatibility=compatibility,
            )

        self._record(
            action="traffic_shifted",
            version=plan.next_version,
            reason="migrations completed",
        )
        return DeploymentOutcome(
            status="rolled_out",
            serving_version=plan.next_version,
            traffic_shifted=True,
            reason="migrations completed",
            compatibility=compatibility,
        )

    def audit_records(self) -> List[Dict[str, Any]]:
        return deepcopy(self._audit)

    def _record(self, *, action: str, version: str, reason: str) -> None:
        self._audit.append(
            {
                "action": action,
                "version": version,
                "reason": reason,
                "recorded_at": time.time(),
            }
        )
