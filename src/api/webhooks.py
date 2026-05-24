"""Webhook delivery helpers with idempotency and endpoint scope guards."""

import time
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class WebhookEndpoint:
    id: str
    workspace_id: str
    url: str
    enabled: bool = True
    secret_version: int = 1


@dataclass
class DeliveryRecord:
    idempotency_key: str
    endpoint_id: str
    workspace_id: str
    status: str
    payload: Dict[str, Any]
    delivered_at: float
    reason: str = ""


class WebhookDispatcher:
    def __init__(self):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._deliveries: Dict[Tuple[str, str, str], DeliveryRecord] = {}

    def register_endpoint(
        self,
        endpoint_id: str,
        workspace_id: str,
        url: str,
    ) -> WebhookEndpoint:
        endpoint = WebhookEndpoint(endpoint_id, workspace_id, url)
        self._endpoints[endpoint_id] = endpoint
        return deepcopy(endpoint)

    def disable_endpoint(self, endpoint_id: str) -> bool:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return False
        endpoint.enabled = False
        return True

    def rotate_endpoint_secret(self, endpoint_id: str) -> bool:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return False
        endpoint.secret_version += 1
        return True

    def deliver(
        self,
        *,
        endpoint_id: str,
        workspace_id: str,
        event_id: str,
        payload: Dict[str, Any],
        callback: Callable[[Dict[str, Any]], bool],
        idempotency_key: Optional[str] = None,
        secret_version: Optional[int] = None,
    ) -> DeliveryRecord:
        key = idempotency_key or event_id
        delivery_key = (endpoint_id, workspace_id, key)
        existing = self._deliveries.get(delivery_key)
        if existing:
            return deepcopy(existing)

        endpoint = self._endpoints.get(endpoint_id)
        sanitized = self._sanitize_payload(payload)
        rejection_reason = self._rejection_reason(
            endpoint=endpoint,
            workspace_id=workspace_id,
            secret_version=secret_version,
        )
        if rejection_reason:
            record = DeliveryRecord(
                idempotency_key=key,
                endpoint_id=endpoint_id,
                workspace_id=workspace_id,
                status="rejected",
                payload=sanitized,
                delivered_at=time.time(),
                reason=rejection_reason,
            )
            self._deliveries[delivery_key] = record
            return deepcopy(record)

        delivered = callback(deepcopy(sanitized))
        record = DeliveryRecord(
            idempotency_key=key,
            endpoint_id=endpoint_id,
            workspace_id=workspace_id,
            status="delivered" if delivered else "failed",
            payload=sanitized,
            delivered_at=time.time(),
        )
        self._deliveries[delivery_key] = record
        return deepcopy(record)

    def delivery_records(self) -> Dict[Tuple[str, str, str], DeliveryRecord]:
        return deepcopy(self._deliveries)

    def _rejection_reason(
        self,
        *,
        endpoint: Optional[WebhookEndpoint],
        workspace_id: str,
        secret_version: Optional[int],
    ) -> str:
        if not endpoint:
            return "endpoint not found"
        if endpoint.workspace_id != workspace_id:
            return "endpoint workspace mismatch"
        if not endpoint.enabled:
            return "endpoint disabled"
        if (
            secret_version is not None
            and secret_version != endpoint.secret_version
        ):
            return "endpoint secret rotated"
        return ""

    def _sanitize_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: deepcopy(value)
            for key, value in payload.items()
            if not key.startswith("_") and not key.startswith("internal_")
        }
