"""Authentication helpers for API routes."""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Set


class AuthenticationError(ValueError):
    pass


ROLE_LEVELS = {
    "reader": 1,
    "operator": 2,
    "admin": 3,
    "owner": 4,
}


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace_id: str
    scopes: Set[str]
    role: str
    token_id: Optional[str] = None


class AuthService:
    def __init__(
        self,
        secret: str,
        audience: str = "agent-workers",
        issuer: str = "agent-orchestrator",
        max_token_age: int = 3600,
        revoked_token_ids: Optional[Iterable[str]] = None,
    ):
        self.secret = secret.encode("utf-8")
        self.audience = audience
        self.issuer = issuer
        self.max_token_age = max_token_age
        self.revoked_token_ids = set(revoked_token_ids or [])

    def create_token(self, claims: Dict[str, Any]) -> str:
        header = {"alg": "HS256", "typ": "JWT"}
        payload = dict(claims)
        payload.setdefault("aud", self.audience)
        payload.setdefault("iss", self.issuer)
        signing_input = ".".join([
            self._encode_json(header),
            self._encode_json(payload),
        ])
        signature = hmac.new(
            self.secret,
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{signing_input}.{self._b64encode(signature)}"

    def authenticate(
        self,
        token: str,
        workspace_id: str,
        required_scope: str,
        minimum_role: str,
    ) -> Principal:
        claims = self._decode_and_verify(token)
        self._validate_registered_claims(claims)

        token_id = claims.get("jti")
        if token_id and token_id in self.revoked_token_ids:
            raise AuthenticationError("token has been revoked")

        scopes = set(claims.get("scope", "").split())
        scopes.update(claims.get("scopes", []))
        if required_scope not in scopes:
            raise AuthenticationError("insufficient token scope")

        token_workspace = claims.get("workspace_id")
        if token_workspace != workspace_id:
            raise AuthenticationError("workspace mismatch")

        role = str(claims.get("role", ""))
        if ROLE_LEVELS.get(role, 0) < ROLE_LEVELS[minimum_role]:
            raise AuthenticationError("insufficient workspace role")

        return Principal(
            subject=str(claims.get("sub", "")),
            workspace_id=workspace_id,
            scopes=scopes,
            role=role,
            token_id=token_id,
        )

    def _decode_and_verify(self, token: str) -> Dict[str, Any]:
        parts = token.split(".")
        if len(parts) != 3:
            raise AuthenticationError("malformed token")

        signing_input = ".".join(parts[:2]).encode("ascii")
        expected = hmac.new(
            self.secret,
            signing_input,
            hashlib.sha256,
        ).digest()
        supplied = self._b64decode(parts[2])
        if not hmac.compare_digest(expected, supplied):
            raise AuthenticationError("invalid token signature")

        try:
            claims = json.loads(self._b64decode(parts[1]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise AuthenticationError("invalid token claims") from exc

        if not isinstance(claims, dict):
            raise AuthenticationError("invalid token claims")
        return claims

    def _validate_registered_claims(self, claims: Dict[str, Any]) -> None:
        now = int(time.time())
        if claims.get("aud") != self.audience:
            raise AuthenticationError("invalid token audience")
        if claims.get("iss") != self.issuer:
            raise AuthenticationError("invalid token issuer")
        if not claims.get("sub"):
            raise AuthenticationError("missing subject")
        if int(claims.get("exp", 0)) <= now:
            raise AuthenticationError("token has expired")
        if int(claims.get("nbf", 0)) > now:
            raise AuthenticationError("token is not active yet")
        issued_at = int(claims.get("iat", now))
        if issued_at > now or now - issued_at > self.max_token_age:
            raise AuthenticationError("token is stale")

    def _encode_json(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        return self._b64encode(raw.encode("utf-8"))

    def _b64encode(self, data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")

    def _b64decode(self, data: str) -> bytes:
        padding = "=" * (-len(data) % 4)
        try:
            return base64.urlsafe_b64decode(data + padding)
        except ValueError as exc:
            raise AuthenticationError("invalid token encoding") from exc
