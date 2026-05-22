import sys

import pytest

from src.cli.main import cli


def run_cli(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["ao", *args])
    return cli()


def test_logs_tail_rejects_negative_values(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["logs", "agent-1", "--tail", "-5"])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert "must be a non-negative integer" in captured.err
    assert "Fetching logs" not in captured.out


@pytest.mark.parametrize("tail", ["0", "25"])
def test_logs_tail_accepts_zero_and_positive_values(
    monkeypatch,
    capsys,
    tail,
):
    run_cli(monkeypatch, ["logs", "agent-1", "--tail", tail])

    captured = capsys.readouterr()
    assert captured.err == ""
    assert "Fetching logs for agent: agent-1" in captured.out
