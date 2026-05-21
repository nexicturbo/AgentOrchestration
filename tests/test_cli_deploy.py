import sys

import pytest

from src.cli.main import cli


def test_deploy_blocks_before_candidate_receives_traffic(
    tmp_path,
    capsys,
    monkeypatch,
):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(
        """
migrations:
  - id: 20260521_add_runs
    status: pending
    backward_compatible: true
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", str(manifest)])

    with pytest.raises(SystemExit) as exc:
        cli()

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "Rollout blocked: migration has not completed" in captured.err
    assert "Deploying agent" not in captured.out


def test_deploy_releases_traffic_after_migrations_complete(
    tmp_path,
    capsys,
    monkeypatch,
):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(
        """
migrations:
  - id: 20260521_add_runs
    status: completed
    backward_compatible: true
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", str(manifest)])

    cli()

    captured = capsys.readouterr()
    assert "Migrations complete; releasing application traffic" in captured.out
    assert f"Deploying agent from manifest: {manifest}" in captured.out
