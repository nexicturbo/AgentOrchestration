"""Deployment release gates."""

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional


MigrationRunner = Callable[[Dict[str, Any]], bool]


@dataclass(frozen=True)
class RolloutDecision:
    allowed: bool
    reason: str
    candidate_receives_traffic: bool
    prior_version_serving: bool
    migrations_checked: List[Dict[str, Any]]


class MigrationRolloutGate:
    """Holds application rollout until database migrations are safe."""

    def evaluate(
        self,
        manifest: Dict[str, Any],
        migration_runner: Optional[MigrationRunner] = None,
    ) -> RolloutDecision:
        migrations = list(self._required_migrations(manifest))
        release = manifest.get("release", {})
        reversible_release = bool(release.get("reversible", False))

        for migration in migrations:
            check = self._safe_migration_record(migration)
            if not self._is_backward_compatible(migration):
                return self._blocked(
                    "migration is not marked backward compatible",
                    check,
                )

            status = str(migration.get("status", "pending")).lower()
            if status == "completed":
                continue
            if status == "failed":
                return self._blocked("migration failed", check)
            if reversible_release and status == "skipped":
                return self._blocked(
                    "reversible release requires migration to run first",
                    check,
                )
            if migration_runner is None:
                return self._blocked("migration has not completed", check)

            if not migration_runner(migration):
                failed_check = dict(check)
                failed_check["status"] = "failed"
                return self._blocked("migration runner failed", failed_check)

        checked = [
            self._safe_migration_record(migration)
            for migration in migrations
        ]
        return RolloutDecision(
            allowed=True,
            reason="required migrations complete",
            candidate_receives_traffic=True,
            prior_version_serving=False,
            migrations_checked=checked,
        )

    def _required_migrations(
        self,
        manifest: Dict[str, Any],
    ) -> Iterable[Dict[str, Any]]:
        for migration in manifest.get("migrations", []):
            if not isinstance(migration, dict):
                continue
            if migration.get("required", True):
                yield migration

    def _is_backward_compatible(self, migration: Dict[str, Any]) -> bool:
        return migration.get("backward_compatible") is True

    def _blocked(
        self,
        reason: str,
        migration: Dict[str, Any],
    ) -> RolloutDecision:
        return RolloutDecision(
            allowed=False,
            reason=f"{reason}: {migration.get('id', 'unknown')}",
            candidate_receives_traffic=False,
            prior_version_serving=True,
            migrations_checked=[migration],
        )

    def _safe_migration_record(
        self,
        migration: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "id": migration.get("id", "unknown"),
            "status": migration.get("status", "pending"),
            "backward_compatible": migration.get("backward_compatible"),
        }
