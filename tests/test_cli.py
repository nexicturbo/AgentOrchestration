import argparse

import pytest

from src.cli import build_parser
from src.cli.main import cli


def _subparser_action(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise AssertionError("parser has no subcommands")


def test_build_parser_exposes_global_options_and_commands():
    parser = build_parser()

    option_strings = {
        option
        for action in parser._actions
        for option in action.option_strings
    }
    commands = set(_subparser_action(parser).choices)

    assert {"--config", "-c", "--verbose", "-v"} <= option_strings
    assert commands == {"init", "deploy", "status", "logs"}


def test_build_parser_parses_status_watch_without_cli_execution():
    parser = build_parser()

    args = parser.parse_args(
        ["--config", "agent.toml", "--verbose", "status", "--watch"]
    )

    assert args.config == "agent.toml"
    assert args.verbose is True
    assert args.command == "status"
    assert args.watch is True


def test_build_parser_parses_logs_tail_default():
    parser = build_parser()

    args = parser.parse_args(["logs", "agent-123"])

    assert args.command == "logs"
    assert args.agent_id == "agent-123"
    assert args.tail == 50


def test_build_parser_returns_independent_instances():
    first = build_parser()
    second = build_parser()

    _subparser_action(first).choices["init"].description = "changed"

    assert first is not second
    assert _subparser_action(second).choices["init"].description != "changed"


def test_cli_execution_wrapper_accepts_explicit_argv(monkeypatch, capsys):
    levels = []
    monkeypatch.setattr("src.cli.main.configure_logging", levels.append)

    cli(["--verbose", "deploy", "agent.yaml"])

    assert levels == ["DEBUG"]
    assert capsys.readouterr().out == (
        "Deploying agent from manifest: agent.yaml\n"
    )


def test_cli_no_command_still_exits_after_printing_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli([])

    assert exc.value.code == 1
    assert "Available commands" in capsys.readouterr().out
