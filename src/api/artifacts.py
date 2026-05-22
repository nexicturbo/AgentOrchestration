"""Artifact upload ingestion guards."""

import hashlib
import re
from dataclasses import dataclass
from typing import Dict, Optional


_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class ArtifactIngestionError(ValueError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class ArtifactRecord:
    run_id: str
    artifact_name: str
    size: int
    sha256: str


class ArtifactIngestionService:
    def __init__(self, max_body_bytes: int = 1024 * 1024):
        self.max_body_bytes = max_body_bytes
        self._records: Dict[str, ArtifactRecord] = {}
        self.lookup_count = 0
        self.mutation_count = 0

    def reset(self) -> None:
        self._records.clear()
        self.lookup_count = 0
        self.mutation_count = 0

    def get(self, run_id: str, artifact_name: str) -> Optional[ArtifactRecord]:
        return self._records.get(self._key(run_id, artifact_name))

    def validate_request(
        self,
        run_id: str,
        artifact_name: str,
        content_length: Optional[str],
    ) -> None:
        if not self._valid_identifier(run_id):
            raise ArtifactIngestionError(400, "Invalid run id")
        if not self._valid_identifier(artifact_name):
            raise ArtifactIngestionError(400, "Invalid artifact name")

        if content_length is None:
            return
        try:
            declared_size = int(content_length)
        except (TypeError, ValueError) as exc:
            raise ArtifactIngestionError(
                400,
                "Invalid Content-Length",
            ) from exc
        if declared_size < 0:
            raise ArtifactIngestionError(400, "Invalid Content-Length")
        if declared_size > self.max_body_bytes:
            raise ArtifactIngestionError(
                413,
                "Artifact upload exceeds maximum size",
            )

    def ingest(
        self,
        run_id: str,
        artifact_name: str,
        body: bytes,
    ) -> ArtifactRecord:
        if not body:
            raise ArtifactIngestionError(400, "Artifact body is required")
        if len(body) > self.max_body_bytes:
            raise ArtifactIngestionError(
                413,
                "Artifact upload exceeds maximum size",
            )

        self.lookup_count += 1
        digest = hashlib.sha256(body).hexdigest()
        record = ArtifactRecord(
            run_id=run_id,
            artifact_name=artifact_name,
            size=len(body),
            sha256=digest,
        )
        self._records[self._key(run_id, artifact_name)] = record
        self.mutation_count += 1
        return record

    @staticmethod
    def _key(run_id: str, artifact_name: str) -> str:
        return f"{run_id}:{artifact_name}"

    @staticmethod
    def _valid_identifier(value: str) -> bool:
        return bool(_IDENTIFIER.fullmatch(value or ""))


artifact_ingestion_service = ArtifactIngestionService()
