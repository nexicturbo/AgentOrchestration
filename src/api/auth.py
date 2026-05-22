"""Authentication and authorization helpers for protected API actions."""

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional, Set
import time


class AuthorizationError(PermissionError):
    """Raised when a request cannot continue as an authorized principal."""


@dataclass
class Principal:
    id: str
    workspace_roles: Dict[str, str]
    scopes: Set[str] = field(default_factory=set)
    disabled: bool = False


@dataclass
class Credential:
    value: str
    principal_id: str
    scopes: Set[str]
    expires_at: Optional[float] = None
    revoked: bool = False


class PermissionService:
    def __init__(self):
        self._principals: Dict[str, Principal] = {}
        self._api_keys: Dict[str, Credential] = {}
        self._sessions: Dict[str, Credential] = {}

    def add_principal(
        self,
        principal_id: str,
        workspace_roles: Mapping[str, str],
        *,
        scopes: Optional[Iterable[str]] = None,
        disabled: bool = False,
    ) -> Principal:
        principal = Principal(
            id=principal_id,
            workspace_roles=dict(workspace_roles),
            scopes=set(scopes or ()),
            disabled=disabled,
        )
        self._principals[principal_id] = principal
        return principal

    def issue_api_key(
        self,
        value: str,
        principal_id: str,
        *,
        scopes: Optional[Iterable[str]] = None,
        expires_at: Optional[float] = None,
    ) -> Credential:
        return self._issue(
            self._api_keys,
            value,
            principal_id,
            scopes=scopes,
            expires_at=expires_at,
        )

    def issue_session(
        self,
        value: str,
        principal_id: str,
        *,
        scopes: Optional[Iterable[str]] = None,
        expires_at: Optional[float] = None,
    ) -> Credential:
        return self._issue(
            self._sessions,
            value,
            principal_id,
            scopes=scopes,
            expires_at=expires_at,
        )

    def revoke_api_key(self, value: str) -> None:
        if value in self._api_keys:
            self._api_keys[value].revoked = True

    def revoke_session(self, value: str) -> None:
        if value in self._sessions:
            self._sessions[value].revoked = True

    def disable_principal(self, principal_id: str) -> None:
        if principal_id in self._principals:
            self._principals[principal_id].disabled = True

    def authorize_request(
        self,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
        *,
        workspace_id: str,
        required_scope: str,
        allowed_roles: Optional[Iterable[str]] = None,
    ) -> Principal:
        credential = self._credential_from_request(headers, cookies)
        return self.authorize_credential(
            credential,
            workspace_id=workspace_id,
            required_scope=required_scope,
            allowed_roles=allowed_roles,
        )

    def authorize_credential(
        self,
        credential: Credential,
        *,
        workspace_id: str,
        required_scope: str,
        allowed_roles: Optional[Iterable[str]] = None,
    ) -> Principal:
        if credential.revoked:
            raise AuthorizationError("credential has been revoked")
        if (
            credential.expires_at is not None
            and credential.expires_at <= time.time()
        ):
            raise AuthorizationError("credential has expired")
        if required_scope not in credential.scopes:
            raise AuthorizationError("credential is missing required scope")

        principal = self._principals.get(credential.principal_id)
        if principal is None:
            raise AuthorizationError("principal is unknown")
        if principal.disabled:
            raise AuthorizationError("principal is disabled")
        if required_scope not in principal.scopes:
            raise AuthorizationError("principal is missing required scope")

        role = principal.workspace_roles.get(workspace_id)
        if role is None:
            raise AuthorizationError("principal has no workspace role")
        if allowed_roles is not None and role not in set(allowed_roles):
            raise AuthorizationError("principal role is insufficient")
        return principal

    def _credential_from_request(
        self,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
    ) -> Credential:
        authorization = (
            headers.get("Authorization") or headers.get("authorization")
        )
        if authorization and authorization.startswith("Bearer "):
            value = authorization.removeprefix("Bearer ").strip()
            credential = self._api_keys.get(value)
            if credential is None:
                raise AuthorizationError("api key is unknown")
            return credential

        session_id = cookies.get("ao_session")
        if session_id:
            credential = self._sessions.get(session_id)
            if credential is None:
                raise AuthorizationError("session is unknown")
            return credential

        raise AuthorizationError("credentials are required")

    def _issue(
        self,
        store: Dict[str, Credential],
        value: str,
        principal_id: str,
        *,
        scopes: Optional[Iterable[str]],
        expires_at: Optional[float],
    ) -> Credential:
        if principal_id not in self._principals:
            raise AuthorizationError("principal is unknown")
        credential = Credential(
            value=value,
            principal_id=principal_id,
            scopes=set(scopes or ()),
            expires_at=expires_at,
        )
        store[value] = credential
        return credential
