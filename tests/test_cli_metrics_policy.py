import pytest

from src.cli.main import cli


def test_deploy_blocks_unbounded_metric_label(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(
        """
name: unsafe-agent
observability:
  metrics:
    - name: task.events
      labels:
        task_id:
          source: task.id
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        ["ao", "deploy", str(manifest)],
    )

    with pytest.raises(SystemExit) as exc_info:
        cli()

    captured = capsys.readouterr()
    assert exc_info.value.code == 2
    assert "Metrics cardinality policy failed" in captured.err
    assert "task.events.task_id" in captured.err
    assert "Deploying agent" not in captured.out


def test_deploy_accepts_bounded_metric_labels(tmp_path, monkeypatch, capsys):
    manifest = tmp_path / "agent.yaml"
    manifest.write_text(
        """
name: safe-agent
metrics:
  - name: task.events
    labels:
      environment: {}
      task_state: {}
      queue:
        values:
          - default
          - priority
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        ["ao", "deploy", str(manifest)],
    )

    cli()

    captured = capsys.readouterr()
    assert f"Deploying agent from manifest: {manifest}" in captured.out
    assert captured.err == ""
