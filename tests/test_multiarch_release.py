import json

import pytest

from src.common.multiarch_release import (
    MultiArchReleaseError,
    load_architecture_records,
    validate_multiarch_release,
    write_validated_manifest,
)


AMD64 = "sha256:" + "a" * 64
ARM64 = "sha256:" + "b" * 64


def release_records():
    return [
        {
            "architecture": "linux/amd64",
            "image": "ghcr.io/acme/agent",
            "digest": AMD64,
            "test_status": "passed",
            "scan_status": "success",
            "source_sha": "release-sha",
        },
        {
            "architecture": "linux/arm64",
            "image": "ghcr.io/acme/agent",
            "digest": ARM64,
            "test_status": "ok",
            "scan_status": "succeeded",
            "source_sha": "release-sha",
        },
    ]


def test_valid_release_writes_digest_manifest_and_summary(tmp_path):
    manifest = validate_multiarch_release(
        release_records(),
        expected_source_sha="release-sha",
    )
    output = tmp_path / "validated.json"

    write_validated_manifest(manifest, str(output))
    written = json.loads(output.read_text(encoding="utf-8"))

    assert written["image"] == "ghcr.io/acme/agent"
    assert written["architectures"][0]["image_ref"] == (
        f"ghcr.io/acme/agent@{AMD64}"
    )
    assert written["architectures"][1]["image_ref"] == (
        f"ghcr.io/acme/agent@{ARM64}"
    )
    summary = manifest.render_summary()
    assert "| linux/amd64 |" in summary
    assert AMD64 in summary
    assert "passed" in summary
    assert "succeeded" in summary


def test_missing_architecture_fails_release():
    with pytest.raises(MultiArchReleaseError) as exc_info:
        validate_multiarch_release(release_records()[:1])

    assert "linux/arm64 validation result is missing" in str(exc_info.value)


def test_missing_test_result_fails_release():
    records = release_records()
    records[0]["test_status"] = ""

    with pytest.raises(MultiArchReleaseError) as exc_info:
        validate_multiarch_release(records)

    assert "linux/amd64 is missing passing test status" in str(exc_info.value)


def test_missing_scan_result_fails_release():
    records = release_records()
    records[1]["scan_status"] = "failed"

    with pytest.raises(MultiArchReleaseError) as exc_info:
        validate_multiarch_release(records)

    assert "linux/arm64 is missing passing scan status" in str(exc_info.value)


def test_stale_source_sha_fails_release():
    records = release_records()
    records[1]["source_sha"] = "old-sha"

    with pytest.raises(MultiArchReleaseError) as exc_info:
        validate_multiarch_release(
            records,
            expected_source_sha="release-sha",
        )

    assert "linux/arm64 was built from stale source old-sha" in str(
        exc_info.value
    )


def test_malformed_digest_fails_release():
    records = release_records()
    records[0]["digest"] = "sha256:NOT-HEX"

    with pytest.raises(MultiArchReleaseError) as exc_info:
        validate_multiarch_release(records)

    assert "digest must be sha256:<64 lowercase hex>" in str(exc_info.value)


def test_duplicate_architecture_fails_release():
    records = release_records()
    records[1]["architecture"] = "linux/amd64"

    with pytest.raises(MultiArchReleaseError) as exc_info:
        validate_multiarch_release(records)

    assert "linux/amd64 appears more than once" in str(exc_info.value)


def test_unexpected_architecture_fails_release():
    records = release_records()
    records.append(
        {
            "architecture": "linux/s390x",
            "image": "ghcr.io/acme/agent",
            "digest": "sha256:" + "c" * 64,
            "test_status": "passed",
            "scan_status": "passed",
        }
    )

    with pytest.raises(MultiArchReleaseError) as exc_info:
        validate_multiarch_release(records)

    assert "linux/s390x is not a required architecture" in str(exc_info.value)


def test_loads_architecture_records_from_yaml(tmp_path):
    manifest = tmp_path / "digests.yaml"
    digest = "sha256:" + "a" * 64
    manifest.write_text(
        f"""
architectures:
  - architecture: linux/amd64
    image: ghcr.io/acme/agent
    digest: {digest}
    test_status: passed
    scan_status: passed
""",
        encoding="utf-8",
    )

    records = load_architecture_records(str(manifest))

    assert records[0]["architecture"] == "linux/amd64"
