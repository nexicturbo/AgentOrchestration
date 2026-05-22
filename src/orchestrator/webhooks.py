"""Webhook endpoint validation and delivery bookkeeping."""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Tuple
from urllib.parse import urlparse
from uuid import uuid4


INTERNAL_PAYLOAD_FIELDS = {
    "authorization",
    "credentials",
    "debug",
    "internal",
    "raw",
    "secret",
    "stack",
    "token",
    "trace",
    "worker",
}


class WebhookValidationError(ValueError):
    """Raised when a webhook endpoint is not safe to persist or deliver to."""


@dataclass
class WebhookEndpoint:
    id: str
    workspace_id: str
    url: str
    enabled: bool = True
    allow_localhost: bool = False
    secret: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookDelivery:
    id: str
    workspace_id: str
    endpoint_id: str
    event_id: str
    status: str
    attempts: int
    payload: Dict[str, Any]
    response: Optional[Any] = None
    error: Optional[str] = None


def validate_endpoint_url(url: str, *, allow_localhost: bool = False) -> str:
    """Validate a webhook target before persistence or delivery."""

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise WebhookValidationError("webhook endpoint must use http or https")
    if not parsed.hostname:
        raise WebhookValidationError(
            "webhook endpoint must include a hostname"
        )
    if parsed.username or parsed.password:
        raise WebhookValidationError(
            "webhook endpoint must not embed credentials"
        )

    host = parsed.hostname.rstrip(".").lower()
    if _is_local_target(host) and not allow_localhost:
        raise WebhookValidationError(
            "webhook endpoint targets localhost or a private address"
        )
    return url


def public_webhook_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Return callback-safe payload data with internal-only fields removed."""

    return {
        key: _public_value(value)
        for key, value in payload.items()
        if not _is_internal_key(str(key))
    }


class WebhookManager:
    """In-memory endpoint registry with idempotent delivery records."""

    def __init__(
        self,
        dispatcher: Optional[
            Callable[[WebhookEndpoint, Mapping[str, Any]], Any]
        ] = None,
    ):
        self._dispatcher = dispatcher or self._default_dispatcher
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[Tuple[str, str, str], WebhookDelivery] = {}

    def register_endpoint(
        self,
        workspace_id: str,
        url: str,
        *,
        allow_localhost: bool = False,
        enabled: bool = True,
        secret: Optional[str] = None,
        metadata: Optional[Mapping[str, Any]] = None,
    ) -> WebhookEndpoint:
        validate_endpoint_url(url, allow_localhost=allow_localhost)
        endpoint = WebhookEndpoint(
            id=str(uuid4()),
            workspace_id=workspace_id,
            url=url,
            enabled=enabled,
            allow_localhost=allow_localhost,
            secret=secret,
            metadata=dict(metadata or {}),
        )
        self._endpoints[endpoint.id] = endpoint
        return endpoint

    def get_endpoint(self, endpoint_id: str) -> Optional[WebhookEndpoint]:
        return self._endpoints.get(endpoint_id)

    def update_endpoint_url(
        self,
        endpoint_id: str,
        url: str,
        *,
        allow_localhost: Optional[bool] = None,
    ) -> WebhookEndpoint:
        endpoint = self._require_endpoint(endpoint_id)
        effective_allow = (
            endpoint.allow_localhost
            if allow_localhost is None
            else allow_localhost
        )
        validate_endpoint_url(url, allow_localhost=effective_allow)
        endpoint.url = url
        endpoint.allow_localhost = effective_allow
        return endpoint

    def set_endpoint_enabled(self, endpoint_id: str, enabled: bool) -> None:
        self._require_endpoint(endpoint_id).enabled = enabled

    def deliver(
        self,
        workspace_id: str,
        endpoint_id: str,
        event_id: str,
        payload: Mapping[str, Any],
    ) -> WebhookDelivery:
        endpoint = self._require_endpoint(endpoint_id)
        self._ensure_deliverable(endpoint, workspace_id)
        key = (workspace_id, endpoint_id, event_id)

        if key in self._deliveries:
            return self._deliveries[key]

        callback_payload = public_webhook_payload(payload)
        delivery = WebhookDelivery(
            id=str(uuid4()),
            workspace_id=workspace_id,
            endpoint_id=endpoint_id,
            event_id=event_id,
            status="pending",
            attempts=0,
            payload=callback_payload,
        )
        self._deliveries[key] = delivery

        try:
            delivery.attempts += 1
            delivery.response = self._dispatcher(endpoint, callback_payload)
            delivery.status = "delivered"
        except Exception as exc:  # pragma: no cover - defensive status path
            delivery.status = "failed"
            delivery.error = str(exc)
        return delivery

    def _ensure_deliverable(
        self,
        endpoint: WebhookEndpoint,
        workspace_id: str,
    ) -> None:
        if endpoint.workspace_id != workspace_id:
            raise WebhookValidationError(
                "webhook endpoint belongs to a different workspace"
            )
        if not endpoint.enabled:
            raise WebhookValidationError("webhook endpoint is disabled")
        validate_endpoint_url(
            endpoint.url,
            allow_localhost=endpoint.allow_localhost,
        )

    def _require_endpoint(self, endpoint_id: str) -> WebhookEndpoint:
        endpoint = self._endpoints.get(endpoint_id)
        if endpoint is None:
            raise WebhookValidationError("webhook endpoint not found")
        return endpoint

    @staticmethod
    def _default_dispatcher(
        endpoint: WebhookEndpoint,
        payload: Mapping[str, Any],
    ) -> Dict[str, Any]:
        return {
            "url": endpoint.url,
            "accepted": True,
            "payload": dict(payload),
        }


def _is_internal_key(key: str) -> bool:
    normalized = key.lower()
    return normalized.startswith("_") or normalized in INTERNAL_PAYLOAD_FIELDS


def _public_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return public_webhook_payload(value)
    if isinstance(value, list):
        return [_public_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_public_value(item) for item in value)
    return value


def _is_local_target(host: str) -> bool:
    if host in {"localhost", "localdomain"} or host.endswith(".localhost"):
        return True

    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False

    return any(
        (
            address.is_loopback,
            address.is_private,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )
