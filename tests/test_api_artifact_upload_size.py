"""Artifact upload size guard tests."""

import hashlib

from fastapi.testclient import TestClient

from src.api.artifacts import artifact_ingestion_service
from src.api.server import create_app


def client():
    artifact_ingestion_service.reset()
    artifact_ingestion_service.max_body_bytes = 8
    return TestClient(create_app())


def auth_headers(extra=None):
    headers = {"Authorization": "Bearer test-token"}
    if extra:
        headers.update(extra)
    return headers


def test_authorized_artifact_upload_records_metadata_only():
    api = client()

    response = api.post(
        "/api/v2/runs/run-1/artifacts/log.txt",
        content=b"payload",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "run_id": "run-1",
        "artifact_name": "log.txt",
        "size": 7,
        "sha256": hashlib.sha256(b"payload").hexdigest(),
    }
    assert artifact_ingestion_service.lookup_count == 1
    assert artifact_ingestion_service.mutation_count == 1


def test_unauthorized_artifact_upload_stops_before_mutation():
    api = client()

    response = api.post(
        "/api/v2/runs/run-1/artifacts/log.txt",
        content=b"payload",
    )

    assert response.status_code == 401
    assert artifact_ingestion_service.lookup_count == 0
    assert artifact_ingestion_service.mutation_count == 0


def test_malformed_artifact_upload_stops_before_mutation():
    api = client()

    response = api.post(
        "/api/v2/runs/run-1/artifacts/bad%20name",
        content=b"payload",
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert artifact_ingestion_service.lookup_count == 0
    assert artifact_ingestion_service.mutation_count == 0


def test_declared_oversized_artifact_upload_stops_before_body_handling():
    api = client()

    response = api.post(
        "/api/v2/runs/run-1/artifacts/log.txt",
        content=b"payload",
        headers=auth_headers({"Content-Length": "9"}),
    )

    assert response.status_code == 413
    assert artifact_ingestion_service.lookup_count == 0
    assert artifact_ingestion_service.mutation_count == 0


def test_actual_oversized_artifact_upload_stops_before_mutation():
    api = client()

    response = api.post(
        "/api/v2/runs/run-1/artifacts/log.txt",
        content=b"too-large",
        headers=auth_headers(),
    )

    assert response.status_code == 413
    assert artifact_ingestion_service.lookup_count == 0
    assert artifact_ingestion_service.mutation_count == 0


def test_empty_artifact_upload_stops_before_mutation():
    api = client()

    response = api.post(
        "/api/v2/runs/run-1/artifacts/log.txt",
        content=b"",
        headers=auth_headers(),
    )

    assert response.status_code == 400
    assert artifact_ingestion_service.lookup_count == 0
    assert artifact_ingestion_service.mutation_count == 0
