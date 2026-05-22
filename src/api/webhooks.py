"""Webhook subscription and delivery API."""

from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, status, Cookie
from pydantic import BaseModel, Field

from src.api.webhook_auth import webhook_auth_guard


ALLOWED_WEBHOOK_EVENTS = frozenset({
    "agent.created",
    "agent.updated",
    "task.completed",
    "task.failed",
    "workflow.completed",
    "workflow.failed",
})

INTERNAL_PAYLOAD_KEYS = {
    "internal_metadata",
    "trace_context",
    "callback_headers",
}


class WebhookSubscriptionCreate(BaseModel):
    workspace_id: str
    endpoint: str
    event_types: List[str] = Field(min_length=1)
    enabled: bool = True


class WebhookSubscriptionRotate(BaseModel):
    workspace_id: str
    endpoint: str
    enabled: bool = True


class WebhookDeliveryCreate(BaseModel):
    workspace_id: str
    event_type: str
    delivery_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    simulate_failure: bool = False


class WebhookRetryRequest(BaseModel):
    workspace_id: str


class WebhookService:
    def __init__(self):
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._deliveries: Dict[Tuple[str, str, str, int], Dict[str, Any]] = {}

    def clear(self) -> None:
        self._subscriptions.clear()
        self._deliveries.clear()

    def create_subscription(
        self,
        request: WebhookSubscriptionCreate,
    ) -> Dict[str, Any]:
        event_types = self._validated_event_types(request.event_types)
        self._validate_workspace_id(request.workspace_id)
        self._validate_endpoint(request.endpoint)

        subscription_id = str(uuid4())
        subscription = {
            "id": subscription_id,
            "workspace_id": request.workspace_id,
            "endpoint": request.endpoint,
            "event_types": event_types,
            "enabled": request.enabled,
            "_secret_version": 1,
            "_delivery_count": 0,
        }
        self._subscriptions[subscription_id] = subscription
        return self._public_subscription(subscription)

    def list_subscriptions(self, workspace_id: str) -> List[Dict[str, Any]]:
        return [
            self._public_subscription(subscription)
            for subscription in self._subscriptions.values()
            if subscription["workspace_id"] == workspace_id
        ]

    def rotate_subscription(
        self,
        subscription_id: str,
        request: WebhookSubscriptionRotate,
    ) -> Dict[str, Any]:
        self._validate_workspace_id(request.workspace_id)
        self._validate_endpoint(request.endpoint)

        subscription = self._subscriptions.get(subscription_id)
        if (
            subscription is None
            or subscription["workspace_id"] != request.workspace_id
        ):
            raise ValueError("webhook subscription not found")

        subscription["endpoint"] = request.endpoint
        subscription["enabled"] = request.enabled
        subscription["_secret_version"] += 1
        return self._public_subscription(subscription)

    def deliver(self, request: WebhookDeliveryCreate) -> Dict[str, Any]:
        self._validate_event_type(request.event_type)
        self._validate_workspace_id(request.workspace_id)

        deliveries = []
        for subscription in self._matching_subscriptions(
            request.workspace_id,
            request.event_type,
        ):
            key = (
                request.workspace_id,
                request.delivery_id,
                subscription["id"],
                subscription["_secret_version"],
            )
            fingerprint = self._delivery_fingerprint(request)
            existing = self._deliveries.get(key)
            if existing is not None:
                if existing["_idempotency_fingerprint"] != fingerprint:
                    raise ValueError(
                        "delivery_id already used for a different event"
                    )
            else:
                self._deliveries[key] = self._build_delivery_record(
                    request,
                    subscription,
                    fingerprint,
                )
                subscription["_delivery_count"] += 1
            deliveries.append(self._public_delivery(self._deliveries[key]))

        return {"deliveries": deliveries}

    def retry(
        self,
        delivery_id: str,
        request: WebhookRetryRequest,
    ) -> Dict[str, Any]:
        self._validate_workspace_id(request.workspace_id)

        deliveries = [
            record
            for key, record in self._deliveries.items()
            if key[0] == request.workspace_id and key[1] == delivery_id
        ]

        for record in deliveries:
            if record["status"] == "pending_retry":
                record["status"] = "delivered"
                record["attempts"] += 1

        return {
            "deliveries": [
                self._public_delivery(record)
                for record in deliveries
            ],
        }

    def _matching_subscriptions(
        self,
        workspace_id: str,
        event_type: str,
    ) -> List[Dict[str, Any]]:
        return [
            subscription
            for subscription in self._subscriptions.values()
            if subscription["workspace_id"] == workspace_id
            and subscription["enabled"]
            and event_type in subscription["event_types"]
        ]

    def _build_delivery_record(
        self,
        request: WebhookDeliveryCreate,
        subscription: Dict[str, Any],
        fingerprint: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "delivery_id": request.delivery_id,
            "subscription_id": subscription["id"],
            "workspace_id": request.workspace_id,
            "event_type": request.event_type,
            "endpoint": subscription["endpoint"],
            "status": (
                "pending_retry"
                if request.simulate_failure else "delivered"
            ),
            "attempts": 1,
            "_payload": self._public_payload(request.payload),
            "_callback_headers": {"X-Internal-Delivery": request.delivery_id},
            "_endpoint_version": subscription["_secret_version"],
            "_idempotency_fingerprint": fingerprint,
        }

    def _delivery_fingerprint(
        self,
        request: WebhookDeliveryCreate,
    ) -> Dict[str, Any]:
        return {
            "event_type": request.event_type,
            "payload": self._public_payload(request.payload),
        }

    def _validated_event_types(self, event_types: List[str]) -> List[str]:
        validated = []
        for event_type in event_types:
            self._validate_event_type(event_type)
            if event_type not in validated:
                validated.append(event_type)
        return validated

    def _validate_event_type(self, event_type: str) -> None:
        if event_type not in ALLOWED_WEBHOOK_EVENTS:
            raise ValueError(f"Unsupported webhook event type: {event_type}")

    def _validate_workspace_id(self, workspace_id: str) -> None:
        if not workspace_id:
            raise ValueError("workspace_id is required")

    def _validate_endpoint(self, endpoint: str) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("webhook endpoint must be an https URL")
        if parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("webhook endpoint must not target local hosts")

    def _public_subscription(
        self,
        subscription: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "id": subscription["id"],
            "workspace_id": subscription["workspace_id"],
            "endpoint": subscription["endpoint"],
            "event_types": list(subscription["event_types"]),
            "enabled": subscription["enabled"],
        }

    def _public_delivery(self, delivery: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "delivery_id": delivery["delivery_id"],
            "subscription_id": delivery["subscription_id"],
            "workspace_id": delivery["workspace_id"],
            "event_type": delivery["event_type"],
            "endpoint": delivery["endpoint"],
            "status": delivery["status"],
            "attempts": delivery["attempts"],
        }

    def _public_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            key: value
            for key, value in payload.items()
            if key not in INTERNAL_PAYLOAD_KEYS and not key.startswith("_")
        }


webhook_service = WebhookService()
webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@webhook_router.post("/subscriptions", status_code=status.HTTP_201_CREATED)
async def create_subscription(
    request: WebhookSubscriptionCreate,
    authorization: str = Header(default=None),
    ao_session: str = Cookie(default=None),
):
    webhook_auth_guard.require_manage_webhooks(
        workspace_id=request.workspace_id,
        authorization=authorization,
        session_id=ao_session,
    )
    try:
        return webhook_service.create_subscription(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@webhook_router.get("/subscriptions")
async def list_subscriptions(
    workspace_id: str,
    authorization: str = Header(default=None),
    ao_session: str = Cookie(default=None),
):
    webhook_auth_guard.require_manage_webhooks(
        workspace_id=workspace_id,
        authorization=authorization,
        session_id=ao_session,
    )
    return {"subscriptions": webhook_service.list_subscriptions(workspace_id)}


@webhook_router.post("/subscriptions/{subscription_id}/rotate")
async def rotate_subscription(
    subscription_id: str,
    request: WebhookSubscriptionRotate,
    authorization: str = Header(default=None),
    ao_session: str = Cookie(default=None),
):
    webhook_auth_guard.require_manage_webhooks(
        workspace_id=request.workspace_id,
        authorization=authorization,
        session_id=ao_session,
    )
    try:
        return webhook_service.rotate_subscription(subscription_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@webhook_router.post("/deliveries")
async def deliver_webhook(
    request: WebhookDeliveryCreate,
    authorization: str = Header(default=None),
    ao_session: str = Cookie(default=None),
):
    webhook_auth_guard.require_manage_webhooks(
        workspace_id=request.workspace_id,
        authorization=authorization,
        session_id=ao_session,
    )
    try:
        return webhook_service.deliver(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@webhook_router.post("/deliveries/{delivery_id}/retry")
async def retry_webhook(
    delivery_id: str,
    request: WebhookRetryRequest,
    authorization: str = Header(default=None),
    ao_session: str = Cookie(default=None),
):
    webhook_auth_guard.require_manage_webhooks(
        workspace_id=request.workspace_id,
        authorization=authorization,
        session_id=ao_session,
    )
    try:
        return webhook_service.retry(delivery_id, request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
