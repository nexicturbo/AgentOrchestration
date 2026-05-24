"""Local artifact download cache with digest verification."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable, Dict, Optional


DownloadFn = Callable[[Path], None]


class ArtifactDownloadCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def get(
        self,
        cache_key: str,
        expected_sha256: str,
        download: DownloadFn,
    ) -> Path:
        artifact_path = self._artifact_path(cache_key)
        metadata_path = self._metadata_path(cache_key)

        if self._is_valid_hit(
            artifact_path,
            metadata_path,
            expected_sha256,
        ):
            return artifact_path

        self._evict(artifact_path, metadata_path)
        temp_path = artifact_path.with_suffix(".tmp")
        if temp_path.exists():
            temp_path.unlink()

        download(temp_path)
        digest = self._sha256(temp_path)
        if digest != expected_sha256:
            temp_path.unlink(missing_ok=True)
            raise ValueError("downloaded artifact digest mismatch")

        temp_path.replace(artifact_path)
        metadata_path.write_text(
            json.dumps(
                {
                    "sha256": expected_sha256,
                    "size": artifact_path.stat().st_size,
                },
                sort_keys=True,
            )
        )
        return artifact_path

    def _is_valid_hit(
        self,
        artifact_path: Path,
        metadata_path: Path,
        expected_sha256: str,
    ) -> bool:
        metadata = self._load_metadata(metadata_path)
        if not artifact_path.is_file() or metadata is None:
            return False
        if metadata.get("sha256") != expected_sha256:
            return False
        if metadata.get("size") != artifact_path.stat().st_size:
            return False
        return self._sha256(artifact_path) == expected_sha256

    def _load_metadata(self, path: Path) -> Optional[Dict[str, object]]:
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None

    def _artifact_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{self._safe_key(cache_key)}.artifact"

    def _metadata_path(self, cache_key: str) -> Path:
        return self.cache_dir / f"{self._safe_key(cache_key)}.json"

    def _safe_key(self, cache_key: str) -> str:
        return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()

    def _sha256(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _evict(self, artifact_path: Path, metadata_path: Path) -> None:
        for path in (artifact_path, metadata_path):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink(missing_ok=True)
