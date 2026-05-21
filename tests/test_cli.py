import json
import sys

import pytest

from src.cli.main import cli


def test_deploy_blocks_manifest_when_migration_fails(
    tmp_path,
    monkeypatch,
    capsys,
):
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps(
        {
            "previous_version": "v1",
            "target_version": "v2",
            "migrations": [{"name": "fail:add_task_state"}],
        }
    ))
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", str(manifest)])

    with pytest.raises(SystemExit) as exc:
        cli()

    assert exc.value.code == 2
    output = capsys.readouterr().out
    assert "Rollout blocked; serving v1" in output
    assert "migration failed: fail:add_task_state" in output


def test_deploy_shifts_traffic_after_successful_migrations(
    tmp_path,
    monkeypatch,
    capsys,
):
    manifest = tmp_path / "release.json"
    manifest.write_text(json.dumps(
        {
            "previous_version": "v1",
            "target_version": "v2",
            "migrations": [{"name": "add_task_state"}],
        }
    ))
    monkeypatch.setattr(sys, "argv", ["ao", "deploy", str(manifest)])

    cli()

    output = capsys.readouterr().out
    assert "Deploying v2" in output
    assert "migrations succeeded" in output
    assert "traffic shifted to v2" in output
