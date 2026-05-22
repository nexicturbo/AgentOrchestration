"""Sanitized exception event helpers."""

from typing import Any, Dict, Mapping, Optional


ALLOWED_CONTEXT_KEYS = {
    "agent_id",
    "attempt",
    "error_class",
    "execution_id",
    "queue",
    "run_id",
    "status",
    "task_id",
    "workflow_id",
}
SENSITIVE_KEY_PARTS = {
    "args",
    "body",
    "context",
    "cookie",
    "data",
    "headers",
    "locals",
    "password",
    "payload",
    "request",
    "secret",
    "token",
}


def sanitize_exception_context(
    context: Optional[Mapping[str, Any]],
    error: Optional[BaseException] = None,
) -> Dict[str, Any]:
    """Return dashboard lookup fields without raw payload or local data."""
    sanitized: Dict[str, Any] = {}
    for key, value in (context or {}).items():
        normalized = str(key).lower()
        if normalized in ALLOWED_CONTEXT_KEYS:
            sanitized[normalized] = _safe_scalar(value)
        elif any(part in normalized for part in SENSITIVE_KEY_PARTS):
            continue
        elif isinstance(value, Mapping):
            nested = sanitize_exception_context(value)
            for nested_key, nested_value in nested.items():
                sanitized.setdefault(nested_key, nested_value)

    if error is not None:
        sanitized["error_class"] = error.__class__.__name__
    return sanitized


def build_exception_event(
    error: BaseException,
    context: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    sanitized = sanitize_exception_context(context, error)
    sanitized.setdefault("error_class", error.__class__.__name__)
    return sanitized


def _safe_scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
