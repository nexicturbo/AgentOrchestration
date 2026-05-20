"""Multi-architecture release manifest validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

import yaml


DEFAULT_REQUIRED_ARCHITECTURES = ("linux/amd64", "linux/arm64")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
PASSING_STATUSES = {"ok", "pass", "passed", "success", "succeeded"}


@dataclass(frozen=True)
class ArchitectureValidation:
    architecture: str
    image: str
    digest: str
    test_status: str
    scan_status: str
    source_sha: Optional[str] = None

    @property
    def image_ref(self) -> str:
        return f"{self.image}@{self.digest}"

    def to_manifest_entry(self) -> Dict[str, str]:
        entry = {
            "architecture": self.architecture,
            "image": self.image,
            "digest": self.digest,
            "image_ref": self.image_ref,
            "test_status": self.test_status,
            "scan_status": self.scan_status,
        }
        if self.source_sha:
            entry["source_sha"] = self.source_sha
        return entry


@dataclass(frozen=True)
class MultiArchReleaseManifest:
    image: str
    architectures: List[ArchitectureValidation]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "image": self.image,
            "architectures": [
                architecture.to_manifest_entry()
                for architecture in self.architectures
            ],
        }

    def render_summary(self) -> str:
        rows = [
            "| Architecture | Digest | Tests | Scan | Source |",
            "| --- | --- | --- | --- | --- |",
        ]
        for architecture in self.architectures:
            rows.append(
                "| {architecture} | `{digest}` | {tests} | {scan} | {source} |"
                .format(
                    architecture=architecture.architecture,
                    digest=architecture.digest,
                    tests=architecture.test_status,
                    scan=architecture.scan_status,
                    source=architecture.source_sha or "n/a",
                )
            )
        return "\n".join(rows)


class MultiArchReleaseError(ValueError):
    def __init__(self, errors: Iterable[str]):
        self.errors = list(errors)
        details = "\n".join(f"- {error}" for error in self.errors)
        super().__init__(f"Multi-arch release validation failed:\n{details}")


def load_architecture_records(path: str) -> List[Mapping[str, Any]]:
    data = _load_file(path)
    if isinstance(data, Mapping):
        records = data.get("architectures") or data.get("digests")
    else:
        records = data
    if not isinstance(records, list):
        raise MultiArchReleaseError(
            ["release manifest must contain an architectures list"]
        )
    return records


def validate_multiarch_release(
    records: Sequence[Mapping[str, Any]],
    required_architectures: Sequence[str] = DEFAULT_REQUIRED_ARCHITECTURES,
    expected_source_sha: Optional[str] = None,
) -> MultiArchReleaseManifest:
    errors: List[str] = []
    seen: Dict[str, ArchitectureValidation] = {}
    image_name: Optional[str] = None

    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            errors.append(f"record {index} must be an object")
            continue

        architecture = _as_text(record, "architecture", "arch")
        image = _as_text(record, "image", "image_name")
        digest = _as_text(record, "digest")
        test_status = _as_text(record, "test_status", "tests")
        scan_status = _as_text(record, "scan_status", "scan")
        source_sha = _optional_text(record, "source_sha", "commit")

        if not architecture:
            errors.append(f"record {index} is missing architecture")
            continue
        if architecture in seen:
            errors.append(f"{architecture} appears more than once")
            continue
        if architecture not in required_architectures:
            errors.append(f"{architecture} is not a required architecture")
        if not image:
            errors.append(f"{architecture} is missing image")
        elif image_name is None:
            image_name = image
        elif image != image_name:
            errors.append(
                f"{architecture} image {image!r} does not match {image_name!r}"
            )
        if not digest or not DIGEST_PATTERN.match(digest):
            errors.append(
                f"{architecture} digest must be sha256:<64 lowercase hex>"
            )
        if not _is_passing(test_status):
            errors.append(f"{architecture} is missing passing test status")
        if not _is_passing(scan_status):
            errors.append(f"{architecture} is missing passing scan status")
        if expected_source_sha and source_sha != expected_source_sha:
            errors.append(
                f"{architecture} was built from stale source "
                f"{source_sha or '<missing>'}"
            )

        if image and digest and DIGEST_PATTERN.match(digest):
            seen[architecture] = ArchitectureValidation(
                architecture=architecture,
                image=image,
                digest=digest,
                test_status=test_status,
                scan_status=scan_status,
                source_sha=source_sha,
            )

    missing = sorted(set(required_architectures) - set(seen))
    for architecture in missing:
        errors.append(f"{architecture} validation result is missing")

    if errors:
        raise MultiArchReleaseError(errors)

    architectures = [
        seen[architecture]
        for architecture in required_architectures
    ]
    return MultiArchReleaseManifest(
        image=image_name or "",
        architectures=architectures,
    )


def write_validated_manifest(
    manifest: MultiArchReleaseManifest,
    output_path: str,
) -> None:
    with Path(output_path).open("w", encoding="utf-8") as output:
        json.dump(manifest.to_dict(), output, indent=2, sort_keys=True)
        output.write("\n")


def _load_file(path: str) -> Any:
    release_path = Path(path)
    with release_path.open(encoding="utf-8") as release_file:
        if release_path.suffix.lower() == ".json":
            return json.load(release_file)
        return yaml.safe_load(release_file)


def _as_text(record: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _optional_text(record: Mapping[str, Any], *keys: str) -> Optional[str]:
    value = _as_text(record, *keys)
    return value or None


def _is_passing(status: str) -> bool:
    return status.strip().lower() in PASSING_STATUSES
