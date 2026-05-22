"""Webhook management authorization helpers."""

import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Set

from fastapi import HTTPException, status


MANAGE_WEBHOOKS_SCOPE = "webhook:manage"
MANAGE_WEBHOOKS_ROLES = {"admin", "owner"}


@dataclass(frozen=True)
class WebhookPrincipal:
    subject: str
    workspaces: Set[str]
    scopes: Set[str]
    role: str
    disabled: bool = False
    revoked: bool = False
    expires_at: Optional[float] = None


class WebhookAuthGuard:
    def __init__(self):
        self._tokens: Dict[str, WebhookPrincipal] = {}
        self._sessions: Dict[str, WebhookPrincipal] = {}

    def clear(self) -> None:
        self._tokens.clear()
        self._sessions.clear()

    def add_token(
        self,
        token: str,
        *,
        subject: str = "api-client",
        workspaces: Iterable[str] = (),
        scopes: Iterable[str] = (),
        role: str = "viewer",
        disabled: bool = False,
        revoked: bool = False,
        expires_at: Optional[float] = None,
    ) -> None:
        self._tokens[token] = WebhookPrincipal(
            subject=subject,
            workspaces=set(workspaces),
            scopes=set(scopes),
            role=role,
            disabled=disabled,
            revoked=revoked,
            expires_at=expires_at,
        )

    def add_session(
        self,
        session_id: str,
        *,
        subject: str = "browser-user",
        workspaces: Iterable[str] = (),
        scopes: Iterable[str] = (),
        role: str = "viewer",
        disabled: bool = False,
        revoked: bool = False,
        expires_at: Optional[float] = None,
    ) -> None:
        self._sessions[session_id] = WebhookPrincipal(
            subject=subject,
            workspaces=set(workspaces),
            scopes=set(scopes),
            role=role,
            disabled=disabled,
            revoked=revoked,
            expires_at=expires_at,
        )

    def require_manage_webhooks(
        self,
        *,
        workspace_id: str,
        authorization: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> WebhookPrincipal:
        principal = self._resolve_principal(authorization, session_id)
        self._validate_principal(principal, workspace_id)
        return principal

    def _resolve_principal(
        self,
        authorization: Optional[str],
        session_id: Optional[str],
    ) -> WebhookPrincipal:
        if authorization:
            parts = authorization.split(" ", 1)
            if len(parts) != 2 or parts[0] != "Bearer" or not parts[1].strip():
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid webhook credentials",
                )
            principal = self._tokens.get(parts[1].strip())
            if principal is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid webhook credentials",
                )
            return principal

        if session_id:
            principal = self._sessions.get(session_id)
            if principal is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="invalid webhook credentials",
                )
            return principal

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="webhook management authentication required",
        )

    def _validate_principal(
        self,
        principal: WebhookPrincipal,
        workspace_id: str,
    ) -> None:
        if principal.disabled or principal.revoked:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="webhook management access denied",
            )
        if (
            principal.expires_at is not None
            and principal.expires_at <= time.time()
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="webhook credentials expired",
            )
        if workspace_id not in principal.workspaces:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="workspace access denied",
            )
        if MANAGE_WEBHOOKS_SCOPE not in principal.scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="webhook management scope required",
            )
        if principal.role not in MANAGE_WEBHOOKS_ROLES:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="webhook management role required",
            )


webhook_auth_guard = WebhookAuthGuard()
