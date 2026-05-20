"""Metrics label cardinality policy validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

import yaml


DEFAULT_LABEL_CARDINALITY_BUDGET = 50

ALLOWED_LABEL_VALUES: Dict[str, List[str]] = {
    "agent_type": ["batch", "interactive", "service", "worker"],
    "environment": ["dev", "staging", "prod"],
    "event": ["created", "started", "completed", "failed", "cancelled"],
    "priority": ["low", "normal", "high", "critical"],
    "region": ["us-east", "us-west", "eu-central", "ap-south"],
    "result": ["success", "error", "timeout", "cancelled"],
    "run_state": ["queued", "running", "completed", "failed", "cancelled"],
    "task_state": ["queued", "running", "completed", "failed", "cancelled"],
    "worker_state": ["starting", "ready", "busy", "draining", "offline"],
}

UNBOUNDED_LABEL_NAMES = {
    "agent_id",
    "artifact_id",
    "email",
    "error_message",
    "exception",
    "hostname",
    "ip",
    "request_id",
    "run_id",
    "session_id",
    "task_id",
    "trace_id",
    "user_id",
    "worker_id",
}


@dataclass(frozen=True)
class MetricsPolicyViolation:
    metric: str
    label: str
    reason: str

    def __str__(self) -> str:
        return f"{self.metric}.{self.label}: {self.reason}"


class MetricsPolicyError(ValueError):
    def __init__(self, violations: Iterable[MetricsPolicyViolation]):
        self.violations = list(violations)
        details = "\n".join(f"- {violation}" for violation in self.violations)
        super().__init__(f"Metrics cardinality policy failed:\n{details}")


def load_metrics_schema(path: str) -> List[Mapping[str, Any]]:
    """Load metrics definitions from a deployment manifest."""
    manifest = _load_manifest(path)
    metrics = manifest.get("metrics")
    if metrics is None:
        observability = manifest.get("observability")
        if isinstance(observability, Mapping):
            metrics = observability.get("metrics")
    if metrics is None:
        return []
    if not isinstance(metrics, list):
        raise MetricsPolicyError(
            [
                MetricsPolicyViolation(
                    metric="<manifest>",
                    label="metrics",
                    reason="metrics must be a list of metric definitions",
                )
            ]
        )
    return metrics


def validate_metrics_schema(
    metrics: Iterable[Mapping[str, Any]],
    budget: int = DEFAULT_LABEL_CARDINALITY_BUDGET,
) -> None:
    violations: List[MetricsPolicyViolation] = []
    for metric in metrics:
        metric_name = str(metric.get("name") or "<unnamed>")
        labels = metric.get("labels", {})
        if not isinstance(labels, Mapping):
            violations.append(
                MetricsPolicyViolation(
                    metric=metric_name,
                    label="labels",
                    reason=(
                        "labels must be a mapping of label names to policies"
                    ),
                )
            )
            continue
        for label_name, label_policy in labels.items():
            reason = _label_violation_reason(
                str(label_name),
                label_policy,
                budget=budget,
            )
            if reason:
                violations.append(
                    MetricsPolicyViolation(
                        metric=metric_name,
                        label=str(label_name),
                        reason=reason,
                    )
                )
    if violations:
        raise MetricsPolicyError(violations)


def validate_metrics_manifest(path: str) -> None:
    validate_metrics_schema(load_metrics_schema(path))


def allowed_label_values() -> Dict[str, List[str]]:
    return {
        label: list(values)
        for label, values in ALLOWED_LABEL_VALUES.items()
    }


def _label_violation_reason(
    label: str,
    policy: Any,
    budget: int,
) -> Optional[str]:
    if not isinstance(policy, Mapping):
        return "label policy must declare values or an approved exception"

    values = policy.get("values")
    if isinstance(values, list):
        if not values:
            return "values must not be empty"
        if len(set(values)) != len(values):
            return "values must not contain duplicates"
        if len(values) > budget:
            return (
                f"{len(values)} values exceed cardinality budget of {budget}"
            )
        return None

    if label in ALLOWED_LABEL_VALUES:
        return None

    exception_reason = _exception_violation_reason(policy.get("exception"))
    if exception_reason is None:
        return None

    if label in UNBOUNDED_LABEL_NAMES:
        return (
            "unbounded label must be replaced with a bounded value set "
            f"or have an approved exception ({exception_reason})"
        )

    return (
        "new label must declare allowed values or have an approved exception "
        f"({exception_reason})"
    )


def _exception_violation_reason(exception: Any) -> Optional[str]:
    if not isinstance(exception, Mapping):
        return "missing exception"
    owner = exception.get("approved_by") or exception.get("owner")
    reason = exception.get("reason")
    if not owner:
        return "missing approved_by"
    if not reason:
        return "missing reason"

    expires_at = exception.get("expires_at")
    if expires_at:
        try:
            expiry = date.fromisoformat(str(expires_at))
        except ValueError:
            return "expires_at must be YYYY-MM-DD"
        if expiry < date.today():
            return "exception expired"
    return None


def _load_manifest(path: str) -> Mapping[str, Any]:
    manifest_path = Path(path)
    with manifest_path.open() as manifest_file:
        if manifest_path.suffix.lower() == ".json":
            data = json.load(manifest_file)
        else:
            data = yaml.safe_load(manifest_file) or {}
    if not isinstance(data, Mapping):
        raise MetricsPolicyError(
            [
                MetricsPolicyViolation(
                    metric="<manifest>",
                    label="root",
                    reason="manifest root must be a mapping",
                )
            ]
        )
    return data
