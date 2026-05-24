from src.cli import main as cli_main


def test_cli_returns_nonzero_when_no_command():
    assert cli_main.cli([]) == 1


def test_deploy_backend_failure_returns_nonzero(monkeypatch, capsys):
    def fail_deploy(manifest, config_path=None):
        raise ConnectionError("orchestrator unavailable")

    monkeypatch.setattr(cli_main, "deploy_agent", fail_deploy)

    exit_code = cli_main.cli(["deploy", "agent.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Deploy failed: orchestrator unavailable" in captured.err
    assert "agent.yaml" not in captured.err


def test_deploy_success_returns_zero(capsys):
    exit_code = cli_main.cli(["deploy", "agent.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Deploying agent from manifest: agent.yaml" in captured.out
