import pytest

from src.infrastructure import (
    BucketConfig,
    BucketLifecycleRule,
    StorageBaselinePolicy,
    StorageBaselineViolation,
    validate_bucket_baseline,
)


def secure_bucket():
    return BucketConfig(
        name="agent-artifacts",
        encryption="aws:kms",
        public_access_block=True,
        versioning=True,
        lifecycle_rules=[
            BucketLifecycleRule(
                name="expire-old-artifacts",
                expire_after_days=30,
            )
        ],
    )


def test_valid_bucket_returns_reviewable_baseline_summary():
    summary = validate_bucket_baseline(secure_bucket())

    assert summary["bucket"] == "agent-artifacts"
    assert summary["policy"] == {
        "required_encryption": "aws:kms",
        "require_public_access_block": True,
        "require_versioning": True,
        "require_lifecycle": True,
        "min_lifecycle_days": 1,
    }
    assert summary["encryption"] == "aws:kms"
    assert summary["public_access_block"] is True
    assert summary["versioning"] is True
    assert summary["lifecycle_rules"] == [
        {
            "name": "expire-old-artifacts",
            "enabled": True,
            "expire_after_days": 30,
        }
    ]


def test_missing_encryption_fails_provisioning_check():
    bucket = BucketConfig(
        name="agent-logs",
        public_access_block=True,
        versioning=True,
        lifecycle_rules=[
            BucketLifecycleRule("expire-logs", expire_after_days=30),
        ],
    )

    with pytest.raises(
        StorageBaselineViolation,
        match="encryption must be aws:kms",
    ):
        validate_bucket_baseline(bucket)


def test_public_access_block_versioning_and_lifecycle_are_required():
    bucket = BucketConfig(
        name="agent-exports",
        encryption="aws:kms",
        public_access_block=False,
        versioning=False,
        lifecycle_rules=[],
    )

    with pytest.raises(StorageBaselineViolation) as error:
        validate_bucket_baseline(bucket)

    message = str(error.value)
    assert "public access block must be enabled" in message
    assert "versioning must be enabled" in message
    assert "enabled lifecycle rule" in message


def test_lifecycle_rule_must_meet_minimum_retention():
    bucket = BucketConfig(
        name="agent-exports",
        encryption="aws:kms",
        public_access_block=True,
        versioning=True,
        lifecycle_rules=[
            BucketLifecycleRule(
                name="disabled",
                enabled=False,
                expire_after_days=30,
            ),
            BucketLifecycleRule(
                name="too-short",
                expire_after_days=1,
            ),
        ],
    )
    policy = StorageBaselinePolicy(min_lifecycle_days=7)

    with pytest.raises(
        StorageBaselineViolation,
        match="enabled lifecycle rule",
    ):
        validate_bucket_baseline(bucket, policy)


def test_bucket_config_from_mapping_normalizes_values():
    bucket = BucketConfig.from_mapping(
        {
            "name": " agent-metrics ",
            "encryption": " aws:kms ",
            "public_access_block": True,
            "versioning": True,
            "lifecycle_rules": [
                {
                    "name": "expire-metrics",
                    "enabled": True,
                    "expire_after_days": 90,
                }
            ],
        }
    )

    summary = validate_bucket_baseline(bucket)

    assert summary["bucket"] == "agent-metrics"
    assert summary["lifecycle_rules"][0]["expire_after_days"] == 90
