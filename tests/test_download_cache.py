import hashlib
import json

import pytest

from src.common.download_cache import ArtifactDownloadCache


def sha256_bytes(payload):
    return hashlib.sha256(payload).hexdigest()


def test_cache_hit_verifies_digest_and_reuses_download(tmp_path):
    payload = b"trusted artifact bytes"
    cache = ArtifactDownloadCache(tmp_path)
    calls = []

    def downloader(destination):
        calls.append(destination)
        destination.write_bytes(payload)

    first = cache.get("task/step/artifact", sha256_bytes(payload), downloader)
    second = cache.get(
        "task/step/artifact",
        sha256_bytes(payload),
        lambda destination: pytest.fail("cache hit should not download"),
    )

    assert first == second
    assert second.read_bytes() == payload
    assert len(calls) == 1


def test_partial_cached_file_is_evicted_and_redownloaded(tmp_path):
    payload = b"complete artifact"
    cache = ArtifactDownloadCache(tmp_path)

    path = cache.get(
        "artifact",
        sha256_bytes(payload),
        lambda destination: destination.write_bytes(payload),
    )
    path.write_bytes(payload[:4])

    redownloaded = []

    def downloader(destination):
        redownloaded.append(destination)
        destination.write_bytes(payload)

    repaired = cache.get("artifact", sha256_bytes(payload), downloader)

    assert repaired.read_bytes() == payload
    assert len(redownloaded) == 1


def test_digest_mismatch_cache_hit_is_evicted_and_redownloaded(tmp_path):
    payload = b"correct artifact"
    cache = ArtifactDownloadCache(tmp_path)

    path = cache.get(
        "artifact",
        sha256_bytes(payload),
        lambda destination: destination.write_bytes(payload),
    )
    path.write_bytes(b"tampered artifact")

    redownloaded = []

    def downloader(destination):
        redownloaded.append(destination)
        destination.write_bytes(payload)

    repaired = cache.get("artifact", sha256_bytes(payload), downloader)

    assert repaired.read_bytes() == payload
    assert len(redownloaded) == 1


def test_new_download_digest_mismatch_leaves_no_cache_entry(tmp_path):
    expected_payload = b"expected artifact"
    cache = ArtifactDownloadCache(tmp_path)

    with pytest.raises(ValueError, match="digest mismatch"):
        cache.get(
            "artifact",
            sha256_bytes(expected_payload),
            lambda destination: destination.write_bytes(b"wrong artifact"),
        )

    assert list((tmp_path / "blobs").iterdir()) == []
    assert list((tmp_path / "metadata").iterdir()) == []


def test_metadata_digest_mismatch_is_not_trusted(tmp_path):
    payload = b"current artifact"
    cache = ArtifactDownloadCache(tmp_path)
    path = cache.get(
        "artifact",
        sha256_bytes(payload),
        lambda destination: destination.write_bytes(payload),
    )

    metadata_path = next((tmp_path / "metadata").iterdir())
    metadata = json.loads(metadata_path.read_text())
    metadata["sha256"] = sha256_bytes(b"older artifact")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

    redownloaded = []

    def downloader(destination):
        redownloaded.append(destination)
        destination.write_bytes(payload)

    repaired = cache.get("artifact", sha256_bytes(payload), downloader)

    assert repaired == path
    assert repaired.read_bytes() == payload
    assert len(redownloaded) == 1
