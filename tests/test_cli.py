from src.cli import main


def test_cli_deploy_backend_failure_returns_nonzero(monkeypatch, capsys):
    def fail_deploy(manifest):
        raise RuntimeError("orchestrator unreachable")

    monkeypatch.setattr(main, "_deploy_agent", fail_deploy)

    exit_code = main.cli(["deploy", "agent.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "orchestrator unreachable" in captured.err
    assert "Deploying agent" not in captured.out


def test_cli_deploy_rejected_result_returns_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(main, "_deploy_agent", lambda manifest: False)

    exit_code = main.cli(["deploy", "agent.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "backend rejected" in captured.err


def test_cli_deploy_success_returns_zero(monkeypatch, capsys):
    seen = {}

    def deploy(manifest):
        seen["manifest"] = manifest
        return True

    monkeypatch.setattr(main, "_deploy_agent", deploy)

    exit_code = main.cli(["deploy", "agent.yaml"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert seen["manifest"] == "agent.yaml"
    assert captured.err == ""


def test_cli_unknown_command_returns_one(capsys):
    exit_code = main.cli([])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Available commands" in captured.out
