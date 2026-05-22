from src.cli import main as cli_main


def test_status_watch_interrupt_returns_documented_code(monkeypatch, capsys):
    def interrupt(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main.time, "sleep", interrupt)

    exit_code = cli_main.cli(["status", "--watch"])

    captured = capsys.readouterr()
    combined_output = captured.out + captured.err

    assert exit_code == cli_main.STATUS_WATCH_INTERRUPT_EXIT_CODE
    assert "exiting with code 130" in captured.err
    assert "Traceback" not in combined_output


def test_status_without_watch_returns_success(capsys):
    exit_code = cli_main.cli(["status"])

    assert exit_code == 0
    assert "Checking agent status..." in capsys.readouterr().out
