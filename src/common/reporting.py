"""Authorization-aware report result caching."""

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict
from typing import FrozenSet, List, Mapping, Optional, Tuple

from src.common.errors import AuthenticationError


ROLE_ORDER = {"viewer": 1, "editor": 2, "admin": 3, "owner": 4}


@dataclass(frozen=True)
class AuthorizationContext:
    user_id: str
    workspace_id: str
    role: str
    scopes: FrozenSet[str]
    version: int

    @property
    def fingerprint(self) -> Tuple[str, str, str, Tuple[str, ...], int]:
        return (
            self.workspace_id,
            self.user_id,
            self.role,
            tuple(sorted(self.scopes)),
            self.version,
        )


@dataclass(frozen=True)
class _Membership:
    role: str
    scopes: FrozenSet[str]
    version: int
    active: bool = True


@dataclass(frozen=True)
class _CacheEntry:
    value: Any
    context: AuthorizationContext
    created_at: float


class ReportingAuthorizationService:
    """Tracks report access and produces fresh authorization contexts."""

    def __init__(self):
        self._memberships: Dict[Tuple[str, str], _Membership] = {}
        self._versions: Dict[Tuple[str, str], int] = {}

    def grant(
        self,
        user_id: str,
        workspace_id: str,
        role: str,
        scopes: Optional[FrozenSet[str]] = None,
    ) -> AuthorizationContext:
        normalized_role = self._normalize_role(role)
        key = (workspace_id, user_id)
        version = self._versions.get(key, 0) + 1
        self._versions[key] = version
        membership = _Membership(
            role=normalized_role,
            scopes=frozenset(scopes or {"reports:read"}),
            version=version,
            active=True,
        )
        self._memberships[key] = membership
        return AuthorizationContext(
            user_id,
            workspace_id,
            membership.role,
            membership.scopes,
            version,
        )

    def revoke(self, user_id: str, workspace_id: str) -> None:
        key = (workspace_id, user_id)
        version = self._versions.get(key, 0) + 1
        self._versions[key] = version
        current = self._memberships.get(key)
        role = current.role if current else "viewer"
        scopes = current.scopes if current else frozenset()
        self._memberships[key] = _Membership(
            role=role,
            scopes=scopes,
            version=version,
            active=False,
        )

    def context_for(
        self,
        user_id: str,
        workspace_id: str,
    ) -> AuthorizationContext:
        membership = self._memberships.get((workspace_id, user_id))
        if not membership or not membership.active:
            raise AuthenticationError("report access denied")
        return AuthorizationContext(
            user_id,
            workspace_id,
            membership.role,
            membership.scopes,
            membership.version,
        )

    def ensure_allowed(
        self,
        context: AuthorizationContext,
        *,
        minimum_role: str = "viewer",
        required_scope: str = "reports:read",
    ) -> None:
        fresh = self.context_for(context.user_id, context.workspace_id)
        if fresh != context:
            raise AuthenticationError("report authorization context changed")
        if required_scope not in fresh.scopes:
            raise AuthenticationError("report scope denied")
        minimum_rank = ROLE_ORDER[self._normalize_role(minimum_role)]
        if ROLE_ORDER[fresh.role] < minimum_rank:
            raise AuthenticationError("report role denied")

    @staticmethod
    def _normalize_role(role: str) -> str:
        normalized = role.strip().lower()
        if normalized not in ROLE_ORDER:
            raise ValueError(f"unknown workspace role: {role}")
        return normalized


class ReportingResultCache:
    """Caches report results only after fresh access checks succeed."""

    def __init__(
        self,
        authorizer: ReportingAuthorizationService,
        ttl_seconds: int = 300,
    ):
        self.authorizer = authorizer
        self.ttl_seconds = ttl_seconds
        self._entries: Dict[
            Tuple[str, Tuple[str, str, str, Tuple[str, ...], int]],
            _CacheEntry,
        ] = {}
        self.audit_records: List[Dict[str, Any]] = []

    def get_or_compute(
        self,
        *,
        user_id: str,
        workspace_id: str,
        report_name: str,
        query_params: Optional[Mapping[str, Any]],
        producer: Callable[[], Any],
        minimum_role: str = "viewer",
        required_scope: str = "reports:read",
    ) -> Any:
        context = self.authorizer.context_for(user_id, workspace_id)
        self.authorizer.ensure_allowed(
            context,
            minimum_role=minimum_role,
            required_scope=required_scope,
        )
        cache_key = self.cache_key(report_name, query_params or {}, context)
        entry = self._entries.get(cache_key)

        if entry and not self._is_expired(entry):
            self.authorizer.ensure_allowed(
                entry.context,
                minimum_role=minimum_role,
                required_scope=required_scope,
            )
            self._audit("cache_hit", context, report_name)
            return entry.value

        value = producer()
        self._entries[cache_key] = _CacheEntry(
            value=value,
            context=context,
            created_at=time.time(),
        )
        self._audit("cache_store", context, report_name)
        return value

    def cache_key(
        self,
        report_name: str,
        query_params: Mapping[str, Any],
        context: AuthorizationContext,
    ) -> Tuple[str, Tuple[str, str, str, Tuple[str, ...], int]]:
        normalized_query = json.dumps(
            {"report": report_name, "params": query_params},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        query_hash = hashlib.sha256(
            normalized_query.encode("utf-8")
        ).hexdigest()
        return query_hash, context.fingerprint

    def _is_expired(self, entry: _CacheEntry) -> bool:
        return time.time() - entry.created_at > self.ttl_seconds

    def _audit(
        self,
        event: str,
        context: AuthorizationContext,
        report_name: str,
    ) -> None:
        self.audit_records.append(
            {
                "event": event,
                "report": report_name,
                "workspace_id": context.workspace_id,
                "user_id": context.user_id,
                "role": context.role,
                "auth_version": context.version,
            }
        )
