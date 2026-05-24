import hashlib
import json

import pytest

from src.common.artifact_cache import ArtifactDownloadCache


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Downloader:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.calls = 0

    def __call__(self, destination):
        self.calls += 1
        destination.write_bytes(self.payload)


def test_cache_hit_verifies_digest_before_reuse(tmp_path):
    payload = b"artifact-data"
    downloader = Downloader(payload)
    cache = ArtifactDownloadCache(tmp_path)

    first = cache.get("artifact-1", digest(payload), downloader)
    second = cache.get("artifact-1", digest(payload), downloader)

    assert first == second
    assert first.read_bytes() == payload
    assert downloader.calls == 1


def test_digest_mismatch_evicts_and_redownloads(tmp_path):
    original = b"original"
    replacement = b"replacement"
    cache = ArtifactDownloadCache(tmp_path)
    first_downloader = Downloader(original)

    artifact = cache.get("artifact-2", digest(original), first_downloader)
    artifact.write_bytes(b"corrupt")

    replacement_downloader = Downloader(replacement)
    repaired = cache.get(
        "artifact-2",
        digest(replacement),
        replacement_downloader,
    )

    assert repaired.read_bytes() == replacement
    assert replacement_downloader.calls == 1


def test_partial_file_size_mismatch_evicts_and_redownloads(tmp_path):
    payload = b"complete payload"
    cache = ArtifactDownloadCache(tmp_path)
    downloader = Downloader(payload)

    artifact = cache.get("artifact-3", digest(payload), downloader)
    metadata_path = cache._metadata_path("artifact-3")
    metadata = json.loads(metadata_path.read_text())
    artifact.write_bytes(payload[:4])
    metadata["size"] = len(payload)
    metadata_path.write_text(json.dumps(metadata))

    replacement_downloader = Downloader(payload)
    repaired = cache.get(
        "artifact-3",
        digest(payload),
        replacement_downloader,
    )

    assert repaired.read_bytes() == payload
    assert replacement_downloader.calls == 1


def test_missing_metadata_evicts_and_redownloads(tmp_path):
    payload = b"payload"
    cache = ArtifactDownloadCache(tmp_path)
    downloader = Downloader(payload)

    cache.get("artifact-4", digest(payload), downloader)
    cache._metadata_path("artifact-4").unlink()

    replacement_downloader = Downloader(payload)
    cache.get("artifact-4", digest(payload), replacement_downloader)

    assert replacement_downloader.calls == 1


def test_download_digest_mismatch_is_not_cached(tmp_path):
    cache = ArtifactDownloadCache(tmp_path)

    with pytest.raises(
        ValueError,
        match="downloaded artifact digest mismatch",
    ):
        cache.get("artifact-5", digest(b"expected"), Downloader(b"wrong"))

    assert list(tmp_path.iterdir()) == []
