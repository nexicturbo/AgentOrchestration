"""Saved-view collaboration authorization helpers."""

from dataclasses import dataclass, field
from hashlib import sha256
import time
from typing import Dict, Iterable, List, Mapping, Optional, Set, Tuple


class CollaborationAuthorizationError(PermissionError):
    """Raised when saved-view sharing is not authorized."""


@dataclass
class Principal:
    id: str
    workspace_roles: Dict[str, str]
    scopes: Set[str] = field(default_factory=set)
    membership_version: int = 1
    disabled: bool = False


@dataclass
class Credential:
    value: str
    principal_id: str
    scopes: Set[str]
    membership_version: int
    expires_at: Optional[float] = None
    revoked: bool = False


@dataclass
class SavedView:
    id: str
    workspace_id: str
    owner_id: str


@dataclass
class ShareRecord:
    view_id: str
    source_workspace_id: str
    target_workspace_id: str
    shared_by: str


class CollaborationPermissionService:
    def __init__(self):
        self._principals: Dict[str, Principal] = {}
        self._api_tokens: Dict[str, Credential] = {}
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

    def update_workspace_role(
        self,
        principal_id: str,
        workspace_id: str,
        role: Optional[str],
    ) -> None:
        principal = self._principals[principal_id]
        if role is None:
            principal.workspace_roles.pop(workspace_id, None)
        else:
            principal.workspace_roles[workspace_id] = role
        principal.membership_version += 1

    def issue_api_token(
        self,
        value: str,
        principal_id: str,
        *,
        scopes: Optional[Iterable[str]] = None,
        expires_at: Optional[float] = None,
    ) -> Credential:
        return self._issue(
            self._api_tokens,
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

    def revoke_api_token(self, value: str) -> None:
        if value in self._api_tokens:
            self._api_tokens[value].revoked = True

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
            raise CollaborationAuthorizationError(
                "credential has been revoked"
            )
        if (
            credential.expires_at is not None
            and credential.expires_at <= time.time()
        ):
            raise CollaborationAuthorizationError("credential has expired")
        if required_scope not in credential.scopes:
            raise CollaborationAuthorizationError(
                "credential is missing required scope"
            )

        principal = self._principals.get(credential.principal_id)
        if principal is None:
            raise CollaborationAuthorizationError("principal is unknown")
        if principal.disabled:
            raise CollaborationAuthorizationError("principal is disabled")
        if principal.membership_version != credential.membership_version:
            raise CollaborationAuthorizationError("credential is stale")
        if required_scope not in principal.scopes:
            raise CollaborationAuthorizationError(
                "principal is missing required scope"
            )

        self.require_workspace_role(
            principal,
            workspace_id,
            allowed_roles=allowed_roles,
        )
        return principal

    def require_workspace_role(
        self,
        principal: Principal,
        workspace_id: str,
        *,
        allowed_roles: Optional[Iterable[str]] = None,
    ) -> None:
        role = principal.workspace_roles.get(workspace_id)
        if role is None:
            raise CollaborationAuthorizationError(
                "principal is not a workspace member"
            )
        if allowed_roles is not None and role not in set(allowed_roles):
            raise CollaborationAuthorizationError(
                "principal role is insufficient"
            )

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
            credential = self._api_tokens.get(value)
            if credential is None:
                raise CollaborationAuthorizationError("api token is unknown")
            return credential

        session_id = cookies.get("ao_session")
        if session_id:
            credential = self._sessions.get(session_id)
            if credential is None:
                raise CollaborationAuthorizationError("session is unknown")
            return credential

        raise CollaborationAuthorizationError("credentials are required")

    def _issue(
        self,
        store: Dict[str, Credential],
        value: str,
        principal_id: str,
        *,
        scopes: Optional[Iterable[str]],
        expires_at: Optional[float],
    ) -> Credential:
        principal = self._principals.get(principal_id)
        if principal is None:
            raise CollaborationAuthorizationError("principal is unknown")
        credential = Credential(
            value=value,
            principal_id=principal_id,
            scopes=set(scopes or ()),
            membership_version=principal.membership_version,
            expires_at=expires_at,
        )
        store[value] = credential
        return credential


class SavedViewSharingService:
    def __init__(self, permissions: CollaborationPermissionService):
        self.permissions = permissions
        self._saved_views: Dict[Tuple[str, str], SavedView] = {}
        self._shares: List[ShareRecord] = []
        self.audit_log: List[Dict[str, str]] = []

    def add_saved_view(
        self,
        view_id: str,
        workspace_id: str,
        owner_id: str,
    ) -> SavedView:
        view = SavedView(
            id=view_id,
            workspace_id=workspace_id,
            owner_id=owner_id,
        )
        self._saved_views[(workspace_id, view_id)] = view
        return view

    def share_view(
        self,
        view_id: str,
        workspace_id: str,
        target_workspace_id: str,
        headers: Mapping[str, str],
        cookies: Mapping[str, str],
    ) -> ShareRecord:
        principal = self.permissions.authorize_request(
            headers,
            cookies,
            workspace_id=workspace_id,
            required_scope="saved_views:share",
            allowed_roles={"owner", "admin"},
        )

        view = self._saved_views.get((workspace_id, view_id))
        if view is None:
            raise CollaborationAuthorizationError("saved view is unknown")

        self.permissions.require_workspace_role(
            principal,
            target_workspace_id,
        )

        record = ShareRecord(
            view_id=view.id,
            source_workspace_id=view.workspace_id,
            target_workspace_id=target_workspace_id,
            shared_by=principal.id,
        )
        self._shares.append(record)
        self._audit("shared", record)
        return record

    def list_shares(self) -> List[ShareRecord]:
        return list(self._shares)

    def _audit(self, action: str, record: ShareRecord) -> None:
        self.audit_log.append(
            {
                "action": action,
                "view": self._digest(record.view_id),
                "source_workspace": self._digest(
                    record.source_workspace_id
                ),
                "target_workspace": self._digest(
                    record.target_workspace_id
                ),
                "principal": self._digest(record.shared_by),
            }
        )

    def _digest(self, value: str) -> str:
        return sha256(value.encode("utf-8")).hexdigest()[:12]
