import sys

import pytest

from src.cli import main


def write_manifest(tmp_path, body="name: worker\nimage: worker:latest\n"):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(body, encoding="utf-8")
    return manifest


def test_deploy_dry_run_validates_without_backend_mutation(
    tmp_path,
    capsys,
    monkeypatch,
):
    manifest = write_manifest(tmp_path)
    deployed = []

    def fake_deploy(path, data):
        deployed.append((path, data))

    monkeypatch.setattr(main, "_deploy_agent", fake_deploy)
    monkeypatch.setattr(
        sys,
        "argv",
        ["ao", "deploy", str(manifest), "--dry-run"],
    )

    main.cli()

    captured = capsys.readouterr()
    assert deployed == []
    assert f"Dry run passed for manifest: {manifest}" in captured.out
    assert "Deploying agent" not in captured.out


def test_deploy_dry_run_rejects_missing_manifest(capsys, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["ao", "deploy", "/tmp/does-not-exist.yaml", "--dry-run"],
    )

    with pytest.raises(SystemExit) as exc:
        main.cli()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "Invalid deployment manifest" in captured.err
    assert "Deploying agent" not in captured.out


def test_deploy_dry_run_rejects_non_mapping_manifest(
    tmp_path,
    capsys,
    monkeypatch,
):
    manifest = write_manifest(tmp_path, "- not\n- a\n- mapping\n")
    monkeypatch.setattr(
        sys,
        "argv",
        ["ao", "deploy", str(manifest), "--dry-run"],
    )

    with pytest.raises(SystemExit) as exc:
        main.cli()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "Deployment manifest must be a mapping" in captured.err


def test_normal_deploy_invokes_backend_after_validation(
    tmp_path,
    monkeypatch,
):
    manifest = write_manifest(tmp_path)
    deployed = []

    def fake_deploy(path, data):
        deployed.append((path, data))

    monkeypatch.setattr(main, "_deploy_agent", fake_deploy)
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", str(manifest)])

    main.cli()

    assert deployed == [(
        manifest,
        {"name": "worker", "image": "worker:latest"},
    )]
