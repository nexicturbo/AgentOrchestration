"""Authentication and authorization helpers for protected API routes."""

import os
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set

from starlette.requests import Request


ADMIN_ROLES = {"admin", "owner", "workspace-admin"}
READ_SCOPE = "agents:read"
WRITE_SCOPE = "agents:write"
TOKEN_ENV_VARS = ("AO_AUTH_TOKENS", "AO_SESSION_TOKENS")


@dataclass(frozen=True)
class Principal:
    token: str
    subject: str
    role: str
    scopes: Set[str]
    expires_at: float
    workspaces: Set[str]
    revoked: bool = False

    def is_expired(self, now: Optional[float] = None) -> bool:
        return self.expires_at <= (time.time() if now is None else now)


@dataclass(frozen=True)
class AuthDecision:
    allowed: bool
    reason: str
    principal: Optional[Principal] = None


class CredentialValidator:
    """Validates bearer tokens and browser session cookies fail-closed."""

    def __init__(self, principals: Optional[Dict[str, Principal]] = None):
        self._principals = principals or load_principals_from_env()

    def authenticate(self, request: Request) -> AuthDecision:
        token, malformed = self._extract_token(request)
        if malformed:
            return AuthDecision(False, "malformed_credentials")
        if not token:
            return AuthDecision(False, "missing_credentials")

        principal = self._principals.get(token)
        if principal is None:
            return AuthDecision(False, "unknown_credentials")
        if principal.revoked:
            return AuthDecision(False, "revoked_credentials", principal)
        if principal.is_expired():
            return AuthDecision(False, "stale_credentials", principal)
        if principal.role not in ADMIN_ROLES:
            return AuthDecision(False, "insufficient_role", principal)

        workspace_id = request.headers.get("X-AO-Workspace", "default")
        if workspace_id not in principal.workspaces:
            return AuthDecision(False, "wrong_workspace", principal)

        required_scope = scope_for_method(request.method)
        if required_scope and required_scope not in principal.scopes:
            return AuthDecision(False, "insufficient_scope", principal)

        return AuthDecision(True, "authorized", principal)

    def _extract_token(self, request: Request) -> tuple[Optional[str], bool]:
        authorization = request.headers.get("Authorization", "")
        if authorization.startswith("Bearer "):
            token = authorization.removeprefix("Bearer ").strip()
            return token, not bool(token)
        session_token = request.cookies.get("ao_session")
        if session_token is not None:
            token = session_token.strip()
            return token, not bool(token)
        return None, False


def scope_for_method(method: str) -> Optional[str]:
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return READ_SCOPE
    return WRITE_SCOPE


def load_principals_from_env() -> Dict[str, Principal]:
    principals: Dict[str, Principal] = {}
    for env_var in TOKEN_ENV_VARS:
        principals.update(parse_principal_specs(os.getenv(env_var, "")))
    return principals


def parse_principal_specs(value: str) -> Dict[str, Principal]:
    principals: Dict[str, Principal] = {}
    for spec in filter(None, (item.strip() for item in value.split(";"))):
        principal = parse_principal_spec(spec)
        principals[principal.token] = principal
    return principals


def parse_principal_spec(spec: str) -> Principal:
    parts = spec.split(":")
    if len(parts) not in {5, 6, 7}:
        raise ValueError(
            "credential specs must be token:subject:role:scopes:expires_at"
            "[:workspaces][:revoked]"
        )
    token, subject, role, scopes, expires_at = parts[:5]
    workspaces = {"default"}
    revoked = False
    if len(parts) >= 6:
        if parts[5].lower() == "revoked":
            revoked = True
        else:
            workspaces = parse_csv_set(parts[5])
    if len(parts) == 7:
        revoked = parts[6].lower() == "revoked"
    return Principal(
        token=token,
        subject=subject,
        role=role,
        scopes=parse_scopes(scopes),
        expires_at=float(expires_at),
        workspaces=workspaces,
        revoked=revoked,
    )


def parse_scopes(scopes: str) -> Set[str]:
    return parse_csv_set(scopes)


def parse_csv_set(value: str) -> Set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def build_principal(
    token: str,
    subject: str = "user",
    role: str = "workspace-admin",
    scopes: Iterable[str] = (READ_SCOPE, WRITE_SCOPE),
    expires_at: Optional[float] = None,
    workspaces: Iterable[str] = ("default",),
    revoked: bool = False,
) -> Principal:
    return Principal(
        token=token,
        subject=subject,
        role=role,
        scopes=set(scopes),
        expires_at=expires_at or (time.time() + 3600),
        workspaces=set(workspaces),
        revoked=revoked,
    )
