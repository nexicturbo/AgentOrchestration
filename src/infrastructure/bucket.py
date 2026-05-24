"""Storage bucket baseline validation for provisioning checks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional


class StorageBaselineViolation(ValueError):
    """Raised when a bucket does not meet the provisioning baseline."""


@dataclass(frozen=True)
class BucketLifecycleRule:
    name: str
    enabled: bool = True
    expire_after_days: Optional[int] = None

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, object],
    ) -> "BucketLifecycleRule":
        return cls(
            name=str(value.get("name", "")).strip(),
            enabled=bool(value.get("enabled", True)),
            expire_after_days=_optional_int(value.get("expire_after_days")),
        )


@dataclass(frozen=True)
class BucketConfig:
    name: str
    encryption: Optional[str] = None
    public_access_block: bool = False
    versioning: bool = False
    lifecycle_rules: List[BucketLifecycleRule] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "BucketConfig":
        rules = [
            BucketLifecycleRule.from_mapping(rule)
            for rule in value.get("lifecycle_rules", [])
        ]
        return cls(
            name=str(value.get("name", "")).strip(),
            encryption=_optional_string(value.get("encryption")),
            public_access_block=bool(value.get("public_access_block", False)),
            versioning=bool(value.get("versioning", False)),
            lifecycle_rules=rules,
        )


@dataclass(frozen=True)
class StorageBaselinePolicy:
    required_encryption: str = "aws:kms"
    require_public_access_block: bool = True
    require_versioning: bool = True
    require_lifecycle: bool = True
    min_lifecycle_days: int = 1

    def describe(self) -> Dict[str, object]:
        return {
            "required_encryption": self.required_encryption,
            "require_public_access_block": self.require_public_access_block,
            "require_versioning": self.require_versioning,
            "require_lifecycle": self.require_lifecycle,
            "min_lifecycle_days": self.min_lifecycle_days,
        }


def validate_bucket_baseline(
    bucket: BucketConfig,
    policy: StorageBaselinePolicy = StorageBaselinePolicy(),
) -> Dict[str, object]:
    """Return a provisioning summary or raise on baseline drift."""

    violations = []
    if not bucket.name:
        violations.append("bucket name is required")
    if bucket.encryption != policy.required_encryption:
        violations.append(
            f"encryption must be {policy.required_encryption}"
        )
    if policy.require_public_access_block and not bucket.public_access_block:
        violations.append("public access block must be enabled")
    if policy.require_versioning and not bucket.versioning:
        violations.append("versioning must be enabled")
    if policy.require_lifecycle and not _has_valid_lifecycle(bucket, policy):
        violations.append(
            "an enabled lifecycle rule with expire_after_days is required"
        )

    if violations:
        raise StorageBaselineViolation("; ".join(violations))

    return {
        "bucket": bucket.name,
        "policy": policy.describe(),
        "encryption": bucket.encryption,
        "public_access_block": bucket.public_access_block,
        "versioning": bucket.versioning,
        "lifecycle_rules": [
            {
                "name": rule.name,
                "enabled": rule.enabled,
                "expire_after_days": rule.expire_after_days,
            }
            for rule in bucket.lifecycle_rules
        ],
    }


def _has_valid_lifecycle(
    bucket: BucketConfig,
    policy: StorageBaselinePolicy,
) -> bool:
    for rule in bucket.lifecycle_rules:
        if (
            rule.enabled
            and rule.expire_after_days is not None
            and rule.expire_after_days >= policy.min_lifecycle_days
        ):
            return True
    return False


def _optional_string(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_int(value: object) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        raise StorageBaselineViolation("expire_after_days must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise StorageBaselineViolation(
            "expire_after_days must be an integer"
        ) from exc
