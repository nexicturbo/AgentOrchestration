import hashlib
import json

import pytest

from src.storage import ArtifactIntegrityError, ArtifactManifestReader


def write_manifest(tmp_path, *, content: bytes, sha256: str = None):
    blob_path = tmp_path / "blob.tar"
    blob_path.write_bytes(content)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_id": "agent-bundle-1",
                "path": blob_path.name,
                "sha256": sha256 or hashlib.sha256(content).hexdigest(),
                "metadata": {"agent": "demo"},
            }
        )
    )
    return manifest_path, blob_path


def test_manifest_reader_returns_verified_artifact(tmp_path):
    manifest_path, blob_path = write_manifest(
        tmp_path,
        content=b"verified artifact",
    )
    reader = ArtifactManifestReader()

    artifact = reader.read(manifest_path)

    assert artifact.artifact_id == "agent-bundle-1"
    assert artifact.path == blob_path
    assert artifact.content == b"verified artifact"
    assert artifact.metadata == {"agent": "demo"}


def test_digest_mismatch_emits_integrity_alert_and_quarantines_blob(tmp_path):
    alerts = []
    manifest_path, blob_path = write_manifest(
        tmp_path,
        content=b"corrupted artifact",
        sha256=hashlib.sha256(b"original artifact").hexdigest(),
    )
    reader = ArtifactManifestReader(
        quarantine_dir=tmp_path / "quarantine",
        blocked_cache_dir=tmp_path / "blocked-cache",
        alert_sink=alerts.append,
    )

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        reader.read(manifest_path)

    alert = exc_info.value.alert
    expected_digest = hashlib.sha256(b"original artifact").hexdigest()
    actual_digest = hashlib.sha256(b"corrupted artifact").hexdigest()

    assert alerts == [alert]
    assert alert.artifact_id == "agent-bundle-1"
    assert alert.expected_digest == expected_digest
    assert alert.actual_digest == actual_digest
    assert alert.quarantined_path is not None
    assert alert.quarantined_path.exists()
    assert alert.quarantined_path.read_bytes() == b"corrupted artifact"
    assert not blob_path.exists()

    blocked = json.loads(alert.blocked_marker.read_text())
    assert blocked["artifact_id"] == "agent-bundle-1"
    assert blocked["reason"] == "sha256_digest_mismatch"
    assert blocked["expected_sha256"] == alert.expected_digest
    assert blocked["actual_sha256"] == alert.actual_digest


def test_existing_block_marker_prevents_cache_reuse(tmp_path):
    alerts = []
    manifest_path, blob_path = write_manifest(
        tmp_path,
        content=b"replacement artifact",
    )
    blocked_dir = tmp_path / "blocked-cache"
    blocked_dir.mkdir()
    marker = blocked_dir / "agent-bundle-1.blocked.json"
    marker.write_text(
        json.dumps(
            {
                "artifact_id": "agent-bundle-1",
                "reason": "sha256_digest_mismatch",
                "expected_sha256": "expected-from-first-failure",
                "actual_sha256": "actual-from-first-failure",
            }
        )
    )
    reader = ArtifactManifestReader(
        blocked_cache_dir=blocked_dir,
        alert_sink=alerts.append,
    )

    with pytest.raises(ArtifactIntegrityError) as exc_info:
        reader.read(manifest_path)

    alert = exc_info.value.alert
    assert alerts == [alert]
    assert alert.blocked_marker == marker
    assert alert.expected_digest == "expected-from-first-failure"
    assert alert.actual_digest == "actual-from-first-failure"
    assert alert.quarantined_path is None
    assert blob_path.exists()
