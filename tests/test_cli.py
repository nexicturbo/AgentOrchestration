import sys

import pytest

from src.cli.main import MAX_LOG_TAIL_LINES, bounded_log_tail, cli


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["ao", *args])
    cli()


def test_logs_accepts_default_tail(monkeypatch, capsys):
    run_cli(monkeypatch, "logs", "agent-123")

    captured = capsys.readouterr()
    assert "Fetching last 50 log lines for agent: agent-123" in captured.out


def test_logs_accepts_maximum_tail(monkeypatch, capsys):
    run_cli(
        monkeypatch,
        "logs",
        "agent-123",
        "--tail",
        str(MAX_LOG_TAIL_LINES),
    )

    captured = capsys.readouterr()
    assert (
        f"Fetching last {MAX_LOG_TAIL_LINES} log lines for agent: agent-123"
        in captured.out
    )


def test_logs_rejects_oversized_tail(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, "logs", "agent-123", "--tail", "1001")

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "tail must be between 1 and 1000 lines" in captured.err


def test_logs_rejects_zero_tail(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        run_cli(monkeypatch, "logs", "agent-123", "--tail", "0")

    captured = capsys.readouterr()
    assert exc.value.code == 2
    assert "tail must be between 1 and 1000 lines" in captured.err


def test_bounded_log_tail_requires_integer():
    with pytest.raises(Exception, match="tail must be an integer"):
        bounded_log_tail("many")
