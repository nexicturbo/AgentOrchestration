"""Authentication and project RBAC helpers for API routes."""

import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set

from fastapi import HTTPException, Request, status


SECRET_METADATA_READ_SCOPE = "secrets:metadata:read"
SECRET_METADATA_ROLES = frozenset({"owner", "admin", "developer"})


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace_id: str
    project_id: str
    role: str
    scopes: frozenset
    client_type: str
    active: bool = True
    revoked: bool = False
    expires_at: Optional[float] = None

    def is_current(self, now: Optional[float] = None) -> bool:
        if not self.active or self.revoked:
            return False
        if self.expires_at is None:
            return True
        return self.expires_at > (now if now is not None else time.time())


class AuthStore:
    """Small in-memory auth registry used by the API permission service."""

    def __init__(self):
        self._tokens: Dict[str, Principal] = {}
        self._sessions: Dict[str, Principal] = {}

    def reset(self) -> None:
        self._tokens.clear()
        self._sessions.clear()

    def register_token(
        self,
        token: str,
        *,
        subject: str,
        workspace_id: str,
        project_id: str,
        role: str,
        scopes: Iterable[str],
        active: bool = True,
        revoked: bool = False,
        expires_at: Optional[float] = None,
    ) -> None:
        self._tokens[token] = Principal(
            subject=subject,
            workspace_id=workspace_id,
            project_id=project_id,
            role=role,
            scopes=frozenset(scopes),
            client_type="token",
            active=active,
            revoked=revoked,
            expires_at=expires_at,
        )

    def register_session(
        self,
        session_id: str,
        *,
        subject: str,
        workspace_id: str,
        project_id: str,
        role: str,
        scopes: Iterable[str],
        active: bool = True,
        revoked: bool = False,
        expires_at: Optional[float] = None,
    ) -> None:
        self._sessions[session_id] = Principal(
            subject=subject,
            workspace_id=workspace_id,
            project_id=project_id,
            role=role,
            scopes=frozenset(scopes),
            client_type="session",
            active=active,
            revoked=revoked,
            expires_at=expires_at,
        )

    def authenticate(self, request: Request) -> Principal:
        authorization = request.headers.get("Authorization")
        if authorization is not None:
            scheme, _, credential = authorization.partition(" ")
            if scheme != "Bearer" or not credential:
                raise _unauthorized()
            principal = self._tokens.get(credential)
        else:
            session_id = request.cookies.get("ao_session")
            principal = self._sessions.get(session_id) if session_id else None

        if principal is None or not principal.is_current():
            raise _unauthorized()
        return principal


class PermissionService:
    def __init__(self, auth: AuthStore):
        self._auth = auth

    def require_secret_metadata_reader(
        self,
        request: Request,
        *,
        workspace_id: str,
        project_id: str,
    ) -> Principal:
        principal = self._auth.authenticate(request)
        if (
            principal.workspace_id != workspace_id
            or principal.project_id != project_id
        ):
            raise _forbidden()
        if principal.role not in SECRET_METADATA_ROLES:
            raise _forbidden()
        scopes = _normalized_scopes(principal.scopes)
        if SECRET_METADATA_READ_SCOPE not in scopes:
            raise _forbidden()
        return principal


def _normalized_scopes(scopes: Iterable[str]) -> Set[str]:
    return {
        scope.strip().lower()
        for scope in scopes
    }


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Forbidden",
    )


auth_store = AuthStore()
permission_service = PermissionService(auth_store)
