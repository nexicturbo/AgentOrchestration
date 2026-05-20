"""Artifact manifest reading with digest verification."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from src.common.metrics import metrics


AlertSink = Callable[["ArtifactIntegrityAlert"], None]


@dataclass(frozen=True)
class ArtifactBlob:
    """A verified artifact read from a manifest."""

    artifact_id: str
    path: Path
    digest: str
    content: bytes
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactIntegrityAlert:
    """Operator-facing alert emitted when an artifact digest does not match."""

    artifact_id: str
    manifest_path: Path
    blob_path: Path
    expected_digest: str
    actual_digest: str
    quarantined_path: Optional[Path]
    blocked_marker: Path


class ArtifactIntegrityError(Exception):
    """Raised when a manifest digest mismatch indicates possible corruption."""

    def __init__(self, alert: ArtifactIntegrityAlert):
        super().__init__(
            "Artifact digest mismatch for "
            f"{alert.artifact_id}: expected {alert.expected_digest}, "
            f"got {alert.actual_digest}"
        )
        self.alert = alert


class ArtifactManifestReader:
    """Read artifact manifests and quarantine blobs with invalid digests."""

    def __init__(
        self,
        *,
        quarantine_dir: Optional[Path] = None,
        blocked_cache_dir: Optional[Path] = None,
        alert_sink: Optional[AlertSink] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.quarantine_dir = quarantine_dir
        self.blocked_cache_dir = blocked_cache_dir
        self.alert_sink = alert_sink
        self.logger = logger or logging.getLogger(__name__)

    def read(self, manifest_path: Path) -> ArtifactBlob:
        manifest_path = Path(manifest_path)
        manifest = self._load_manifest(manifest_path)
        artifact_id = str(
            manifest.get("artifact_id")
            or manifest.get("id")
            or manifest_path.stem
        )
        expected_digest = self._normalize_digest(str(manifest["sha256"]))
        blob_path = self._resolve_blob_path(manifest_path, manifest)
        blocked_marker = self._block_marker_path(artifact_id, blob_path)
        if blocked_marker.exists():
            alert = self._build_blocked_cache_alert(
                artifact_id=artifact_id,
                manifest_path=manifest_path,
                blob_path=blob_path,
                blocked_marker=blocked_marker,
                expected_digest=expected_digest,
            )
            self._emit_alert(alert)
            raise ArtifactIntegrityError(alert)

        content = blob_path.read_bytes()
        actual_digest = hashlib.sha256(content).hexdigest()

        if actual_digest != expected_digest:
            alert = self._handle_digest_mismatch(
                artifact_id=artifact_id,
                manifest_path=manifest_path,
                blob_path=blob_path,
                expected_digest=expected_digest,
                actual_digest=actual_digest,
            )
            raise ArtifactIntegrityError(alert)

        return ArtifactBlob(
            artifact_id=artifact_id,
            path=blob_path,
            digest=actual_digest,
            content=content,
            metadata=dict(manifest.get("metadata") or {}),
        )

    def _load_manifest(self, manifest_path: Path) -> Dict[str, object]:
        with manifest_path.open() as f:
            manifest = json.load(f)

        if "sha256" not in manifest:
            raise ValueError(
                "Artifact manifest is missing required sha256 digest"
            )
        if not any(key in manifest for key in ("path", "blob_path", "file")):
            raise ValueError(
                "Artifact manifest is missing required artifact path"
            )
        return manifest

    def _resolve_blob_path(
        self,
        manifest_path: Path,
        manifest: Dict[str, object],
    ) -> Path:
        raw_path = (
            manifest.get("path")
            or manifest.get("blob_path")
            or manifest.get("file")
        )
        blob_path = Path(str(raw_path))
        if not blob_path.is_absolute():
            blob_path = manifest_path.parent / blob_path
        return blob_path

    def _handle_digest_mismatch(
        self,
        *,
        artifact_id: str,
        manifest_path: Path,
        blob_path: Path,
        expected_digest: str,
        actual_digest: str,
    ) -> ArtifactIntegrityAlert:
        blocked_marker = self._write_block_marker(
            artifact_id=artifact_id,
            blob_path=blob_path,
            expected_digest=expected_digest,
            actual_digest=actual_digest,
        )
        quarantined_path = self._quarantine_blob(
            artifact_id=artifact_id,
            blob_path=blob_path,
            actual_digest=actual_digest,
        )
        alert = ArtifactIntegrityAlert(
            artifact_id=artifact_id,
            manifest_path=manifest_path,
            blob_path=blob_path,
            expected_digest=expected_digest,
            actual_digest=actual_digest,
            quarantined_path=quarantined_path,
            blocked_marker=blocked_marker,
        )
        self._emit_alert(alert)
        return alert

    def _quarantine_blob(
        self,
        *,
        artifact_id: str,
        blob_path: Path,
        actual_digest: str,
    ) -> Optional[Path]:
        if not blob_path.exists():
            return None

        quarantine_dir = (
            self.quarantine_dir or blob_path.parent / ".quarantine"
        )
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        destination = (
            quarantine_dir
            / f"{artifact_id}-{actual_digest[:12]}{blob_path.suffix}"
        )
        shutil.move(str(blob_path), str(destination))
        return destination

    def _write_block_marker(
        self,
        *,
        artifact_id: str,
        blob_path: Path,
        expected_digest: str,
        actual_digest: str,
    ) -> Path:
        marker = self._block_marker_path(artifact_id, blob_path)
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(
            json.dumps(
                {
                    "artifact_id": artifact_id,
                    "reason": "sha256_digest_mismatch",
                    "expected_sha256": expected_digest,
                    "actual_sha256": actual_digest,
                },
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        return marker

    def _block_marker_path(self, artifact_id: str, blob_path: Path) -> Path:
        blocked_cache_dir = (
            self.blocked_cache_dir
            or blob_path.parent / ".artifact-blocked-cache"
        )
        safe_artifact_id = artifact_id.replace("/", "_").replace("\\", "_")
        return blocked_cache_dir / f"{safe_artifact_id}.blocked.json"

    def _build_blocked_cache_alert(
        self,
        *,
        artifact_id: str,
        manifest_path: Path,
        blob_path: Path,
        blocked_marker: Path,
        expected_digest: str,
    ) -> ArtifactIntegrityAlert:
        try:
            blocked = json.loads(blocked_marker.read_text())
        except (OSError, json.JSONDecodeError):
            blocked = {}

        return ArtifactIntegrityAlert(
            artifact_id=artifact_id,
            manifest_path=manifest_path,
            blob_path=blob_path,
            expected_digest=str(
                blocked.get("expected_sha256") or expected_digest
            ),
            actual_digest=str(
                blocked.get("actual_sha256") or "blocked_cache_reuse"
            ),
            quarantined_path=None,
            blocked_marker=blocked_marker,
        )

    def _emit_alert(self, alert: ArtifactIntegrityAlert) -> None:
        metrics.increment("artifact.integrity_mismatch")
        self.logger.critical(
            "artifact_integrity_mismatch",
            extra={
                "artifact_id": alert.artifact_id,
                "expected_digest": alert.expected_digest,
                "actual_digest": alert.actual_digest,
                "quarantined_path": (
                    str(alert.quarantined_path)
                    if alert.quarantined_path
                    else None
                ),
            },
        )
        if self.alert_sink:
            self.alert_sink(alert)

    def _normalize_digest(self, digest: str) -> str:
        digest = digest.lower()
        if digest.startswith("sha256:"):
            return digest.split(":", 1)[1]
        return digest
