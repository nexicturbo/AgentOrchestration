"""Digest-verified local artifact download cache."""

import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Callable, Optional, Union


DownloaderResult = Optional[Union[bytes, str, Path]]
Downloader = Callable[[Path], DownloaderResult]


class ArtifactDownloadCache:
    """Caches downloaded artifacts and validates cache hits by SHA-256."""

    def __init__(self, root: Union[str, Path]):
        self.root = Path(root)
        self.blob_dir = self.root / "blobs"
        self.metadata_dir = self.root / "metadata"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)

    def get(
        self,
        artifact_id: str,
        expected_sha256: str,
        downloader: Downloader,
    ) -> Path:
        """Return a cached artifact, downloading it when validation fails."""
        expected_digest = self._normalize_digest(expected_sha256)
        blob_path = self._blob_path(artifact_id)
        metadata_path = self._metadata_path(artifact_id)

        if self._valid_cache_hit(blob_path, metadata_path, expected_digest):
            return blob_path

        self._evict(blob_path, metadata_path)
        return self._download_and_store(
            artifact_id,
            expected_digest,
            downloader,
            blob_path,
            metadata_path,
        )

    def _download_and_store(
        self,
        artifact_id: str,
        expected_digest: str,
        downloader: Downloader,
        blob_path: Path,
        metadata_path: Path,
    ) -> Path:
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{blob_path.name}.",
            suffix=".download",
            dir=self.blob_dir,
        )
        os.close(fd)
        tmp_path = Path(tmp_name)

        try:
            result = downloader(tmp_path)
            if isinstance(result, bytes):
                tmp_path.write_bytes(result)
            elif isinstance(result, (str, Path)):
                shutil.copyfile(Path(result), tmp_path)
            elif result is not None:
                if not isinstance(result, int) or not tmp_path.exists():
                    raise TypeError(
                        "downloader must return bytes, a path, or None"
                    )

            actual_digest, size = self._digest_file(tmp_path)
            if actual_digest != expected_digest:
                raise ValueError(
                    "downloaded artifact digest mismatch: "
                    f"expected {expected_digest}, got {actual_digest}"
                )

            os.replace(tmp_path, blob_path)
            self._write_metadata(
                metadata_path,
                artifact_id,
                expected_digest,
                size,
            )
            return blob_path
        except Exception:
            tmp_path.unlink(missing_ok=True)
            self._evict(blob_path, metadata_path)
            raise

    def _valid_cache_hit(
        self,
        blob_path: Path,
        metadata_path: Path,
        expected_digest: str,
    ) -> bool:
        if not blob_path.exists() or not metadata_path.exists():
            return False

        try:
            metadata = json.loads(metadata_path.read_text())
            if metadata.get("algorithm") != "sha256":
                return False
            if metadata.get("sha256") != expected_digest:
                return False
            if metadata.get("size") != blob_path.stat().st_size:
                return False
            actual_digest, _ = self._digest_file(blob_path)
            return actual_digest == expected_digest
        except (OSError, ValueError, json.JSONDecodeError):
            return False

    def _write_metadata(
        self,
        metadata_path: Path,
        artifact_id: str,
        digest: str,
        size: int,
    ) -> None:
        metadata = {
            "artifact_id": artifact_id,
            "algorithm": "sha256",
            "sha256": digest,
            "size": size,
            "cached_at": time.time(),
        }
        fd, tmp_name = tempfile.mkstemp(
            prefix=f"{metadata_path.name}.",
            suffix=".tmp",
            dir=self.metadata_dir,
        )
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, sort_keys=True)
        os.replace(tmp_name, metadata_path)

    def _evict(self, blob_path: Path, metadata_path: Path) -> None:
        blob_path.unlink(missing_ok=True)
        metadata_path.unlink(missing_ok=True)

    def _blob_path(self, artifact_id: str) -> Path:
        return self.blob_dir / self._cache_key(artifact_id)

    def _metadata_path(self, artifact_id: str) -> Path:
        return self.metadata_dir / f"{self._cache_key(artifact_id)}.json"

    @staticmethod
    def _cache_key(artifact_id: str) -> str:
        if not artifact_id:
            raise ValueError("artifact_id is required")
        return hashlib.sha256(artifact_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_digest(digest: str) -> str:
        value = digest.lower().strip()
        if value.startswith("sha256:"):
            value = value.removeprefix("sha256:")
        if len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value
        ):
            raise ValueError("expected_sha256 must be a SHA-256 hex digest")
        return value

    @staticmethod
    def _digest_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        return digest.hexdigest(), size
