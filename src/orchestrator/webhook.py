"""Webhook delivery helpers with public payload shaping."""

import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse


class WebhookDeliveryError(ValueError):
    """Raised when a webhook delivery cannot be safely attempted."""


@dataclass(frozen=True)
class WebhookEndpoint:
    endpoint_id: str
    workspace_id: str
    url: str
    secret_version: int = 1
    enabled: bool = True


@dataclass
class WebhookDeliveryRecord:
    delivery_id: str
    endpoint_id: str
    workspace_id: str
    idempotency_key: str
    payload: Dict[str, Any]
    status: str
    attempts: int
    error: Optional[str] = None


class WebhookDeliveryService:
    """Validate endpoints and deliver already-shaped public webhook events."""

    _Transport = Callable[[WebhookEndpoint, Dict[str, Any]], None]

    _INTERNAL_FIELDS = {
        "debug",
        "internal",
        "internal_metadata",
        "operator_token",
        "raw_task",
        "retry_cursor",
        "run_metadata",
        "secret",
        "stacktrace",
        "trace_id",
        "worker_id",
    }

    def __init__(
        self,
        transport: Optional[_Transport] = None,
    ):
        self._transport = transport or self._noop_transport
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[str, WebhookDeliveryRecord] = {}
        self._delivery_ids: Dict[str, WebhookDeliveryRecord] = {}

    def register_endpoint(self, endpoint: WebhookEndpoint) -> WebhookEndpoint:
        self._validate_endpoint(endpoint)
        self._endpoints[endpoint.endpoint_id] = endpoint
        return endpoint

    def deliver_event(
        self,
        endpoint_id: str,
        workspace_id: str,
        event: Dict[str, Any],
        *,
        idempotency_key: Optional[str] = None,
        secret_version: Optional[int] = None,
    ) -> WebhookDeliveryRecord:
        endpoint = self._resolve_endpoint(
            endpoint_id,
            workspace_id,
            secret_version,
        )
        key = idempotency_key or self._default_idempotency_key(endpoint, event)
        if key in self._deliveries:
            return self._deliveries[key]

        record = WebhookDeliveryRecord(
            delivery_id=str(uuid.uuid4()),
            endpoint_id=endpoint.endpoint_id,
            workspace_id=workspace_id,
            idempotency_key=key,
            payload=self.shape_public_event(event),
            status="pending",
            attempts=0,
        )
        self._deliveries[key] = record
        self._delivery_ids[record.delivery_id] = record
        self._send(endpoint, record)
        return record

    def retry_delivery(self, delivery_id: str) -> WebhookDeliveryRecord:
        if delivery_id not in self._delivery_ids:
            raise WebhookDeliveryError("delivery record not found")

        record = self._delivery_ids[delivery_id]
        endpoint = self._resolve_endpoint(
            record.endpoint_id,
            record.workspace_id,
            None,
        )
        self._send(endpoint, record)
        return record

    @classmethod
    def shape_public_event(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(event, dict):
            raise WebhookDeliveryError("webhook event must be an object")
        return cls._strip_internal_fields(event)

    @classmethod
    def _strip_internal_fields(cls, value: Any) -> Any:
        if isinstance(value, dict):
            shaped = {}
            for key, nested in value.items():
                if cls._is_internal_key(key):
                    continue
                shaped[key] = cls._strip_internal_fields(nested)
            return shaped
        if isinstance(value, list):
            return [cls._strip_internal_fields(item) for item in value]
        return value

    @classmethod
    def _is_internal_key(cls, key: Any) -> bool:
        if not isinstance(key, str):
            return True
        normalized = key.lower()
        return (
            normalized.startswith("_")
            or normalized in cls._INTERNAL_FIELDS
            or normalized.endswith("_secret")
            or normalized.endswith("_token")
        )

    def _resolve_endpoint(
        self,
        endpoint_id: str,
        workspace_id: str,
        secret_version: Optional[int],
    ) -> WebhookEndpoint:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            raise WebhookDeliveryError("webhook endpoint not found")
        self._validate_endpoint(endpoint)
        if endpoint.workspace_id != workspace_id:
            raise WebhookDeliveryError(
                "webhook endpoint belongs to another workspace"
            )
        if not endpoint.enabled:
            raise WebhookDeliveryError("webhook endpoint is disabled")
        if (
            secret_version is not None
            and endpoint.secret_version != secret_version
        ):
            raise WebhookDeliveryError(
                "webhook endpoint secret has been rotated"
            )
        return endpoint

    def _send(
        self,
        endpoint: WebhookEndpoint,
        record: WebhookDeliveryRecord,
    ) -> None:
        record.attempts += 1
        try:
            self._transport(endpoint, record.payload)
        except Exception as exc:
            record.status = "failed"
            record.error = str(exc)
            return
        record.status = "delivered"
        record.error = None

    @staticmethod
    def _validate_endpoint(endpoint: WebhookEndpoint) -> None:
        parsed = urlparse(endpoint.url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise WebhookDeliveryError("webhook endpoint must use HTTPS")
        if not endpoint.endpoint_id:
            raise WebhookDeliveryError("webhook endpoint id is required")
        if not endpoint.workspace_id:
            raise WebhookDeliveryError("webhook workspace id is required")

    @staticmethod
    def _default_idempotency_key(
        endpoint: WebhookEndpoint,
        event: Dict[str, Any],
    ) -> str:
        event_id = (
            event.get("event_id")
            or event.get("id")
            or str(uuid.uuid4())
        )
        return f"{endpoint.endpoint_id}:{event_id}"

    @staticmethod
    def _noop_transport(
        endpoint: WebhookEndpoint,
        payload: Dict[str, Any],
    ) -> None:
        return None
