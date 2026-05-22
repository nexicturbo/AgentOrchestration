import sys

import pytest

from src.cli import main as cli_main


VALID_AGENT_ID = "123e4567-e89b-12d3-a456-426614174000"


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["ao", *args])
    cli_main.cli()


def test_logs_rejects_invalid_agent_id_before_output(monkeypatch, capsys):
    monkeypatch.setattr(
        cli_main.OrchestratorClient,
        "start_agent",
        lambda *_: pytest.fail("SDK should not be called"),
    )

    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, "logs", "../bad")

    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "agent_id must be a valid UUID" in captured.err
    assert "Fetching logs" not in captured.out


@pytest.mark.parametrize("command", ["start", "stop", "delete"])
def test_lifecycle_rejects_invalid_agent_id_before_sdk(monkeypatch, command):
    class FailingClient:
        def start_agent(self, agent_id):
            pytest.fail(f"unexpected start call for {agent_id}")

        def stop_agent(self, agent_id):
            pytest.fail(f"unexpected stop call for {agent_id}")

        def delete_agent(self, agent_id):
            pytest.fail(f"unexpected delete call for {agent_id}")

    monkeypatch.setattr(cli_main, "OrchestratorClient", FailingClient)

    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, command, "not-a-uuid")

    assert exc.value.code == 2


@pytest.mark.parametrize(
    ("command", "method_name"),
    [
        ("start", "start_agent"),
        ("stop", "stop_agent"),
        ("delete", "delete_agent"),
    ],
)
def test_lifecycle_commands_pass_valid_agent_id_to_sdk(
    monkeypatch, capsys, command, method_name
):
    calls = []

    class SpyClient:
        def start_agent(self, agent_id):
            calls.append(("start_agent", agent_id))
            return {"status": "started"}

        def stop_agent(self, agent_id):
            calls.append(("stop_agent", agent_id))
            return {"status": "stopped"}

        def delete_agent(self, agent_id):
            calls.append(("delete_agent", agent_id))
            return {"status": "deleted"}

    monkeypatch.setattr(cli_main, "OrchestratorClient", SpyClient)

    run_cli(monkeypatch, command, VALID_AGENT_ID.upper())

    assert calls == [(method_name, VALID_AGENT_ID)]
    assert "status" in capsys.readouterr().out
