"""Authentication helpers for API boundary checks."""

import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Set

from starlette.requests import Request


class AuthError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass(frozen=True)
class Principal:
    token: str
    subject: str
    workspace_id: str
    scopes: Set[str]
    roles: Mapping[str, str]


class AuthService:
    """Validates principals before protected data is returned."""

    PUBLIC_PATHS = {"/health", "/api/v2/auth/token"}
    DOC_PATHS = {
        "/api/docs",
        "/api/redoc",
        "/api/openapi.json",
        "/docs",
        "/redoc",
        "/openapi.json",
    }
    ROLE_RANK = {"reader": 1, "admin": 2, "owner": 3}

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        auth_config = (config or {}).get("auth", {})
        self._tokens = auth_config.get("tokens", {})
        self._revoked_tokens = set(auth_config.get("revoked_tokens", ()))
        self._clock = auth_config.get("clock", time.time)
        self._allow_legacy_bearer = auth_config.get(
            "allow_legacy_bearer",
            False,
        )

    def is_public_path(self, path: str) -> bool:
        return path in self.PUBLIC_PATHS

    def requires_auth(self, path: str) -> bool:
        return path.startswith("/api/v2") or path in self.DOC_PATHS

    def requires_docs_access(self, path: str) -> bool:
        return path in self.DOC_PATHS

    def authenticate_request(self, request: Request) -> Principal:
        token = self._extract_token(request)
        principal_data = self._resolve_token(token)
        principal = self._principal_from_data(token, principal_data)
        request.state.principal = principal
        return principal

    def require_docs_access(self, principal: Principal) -> None:
        if "docs:read" not in principal.scopes and "*" not in principal.scopes:
            raise AuthError(403, "Missing docs:read scope")

        role = principal.roles.get(principal.workspace_id)
        if self.ROLE_RANK.get(role, 0) < self.ROLE_RANK["reader"]:
            raise AuthError(403, "Missing workspace reader role")

    def _extract_token(self, request: Request) -> str:
        auth_header = request.headers.get("Authorization", "")
        if auth_header:
            if not auth_header.startswith("Bearer "):
                raise AuthError(401, "Malformed authorization header")
            token = auth_header[len("Bearer "):].strip()
            if not token or " " in token:
                raise AuthError(401, "Malformed bearer token")
            return token

        session_token = request.cookies.get("ao_session", "").strip()
        if session_token:
            return session_token

        raise AuthError(401, "Unauthorized")

    def _resolve_token(self, token: str) -> Mapping[str, Any]:
        if token in self._revoked_tokens:
            raise AuthError(401, "Token revoked")

        if not self._tokens and self._allow_legacy_bearer:
            return {
                "subject": "legacy-api-client",
                "workspace_id": "default",
                "scopes": {"*"},
                "roles": {"default": "owner"},
            }

        principal_data = self._tokens.get(token)
        if principal_data is None:
            raise AuthError(401, "Unknown token")

        if principal_data.get("revoked"):
            raise AuthError(401, "Token revoked")

        expires_at = principal_data.get("expires_at")
        if (
            expires_at is not None
            and float(expires_at) <= float(self._clock())
        ):
            raise AuthError(401, "Token expired")

        return principal_data

    def _principal_from_data(
        self,
        token: str,
        data: Mapping[str, Any],
    ) -> Principal:
        subject = str(data.get("subject") or data.get("user_id") or "")
        workspace_id = str(data.get("workspace_id") or "")
        scopes = set(self._iter_strings(data.get("scopes", ())))
        roles = data.get("roles") or {}

        if not subject or not workspace_id:
            raise AuthError(401, "Invalid principal")
        if not isinstance(roles, Mapping):
            raise AuthError(401, "Invalid principal roles")

        return Principal(
            token=token,
            subject=subject,
            workspace_id=workspace_id,
            scopes=scopes,
            roles={
                str(workspace): str(role)
                for workspace, role in roles.items()
            },
        )

    @staticmethod
    def _iter_strings(values: Iterable[Any]) -> Iterable[str]:
        for value in values:
            yield str(value)
