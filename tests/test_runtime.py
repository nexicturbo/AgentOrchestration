import subprocess

import pytest

from src.agent.runtime import (
    AgentRuntime,
    DEFAULT_MODEL_MODE,
    ModelMode,
    RuntimeState,
    resolve_model_mode,
)


class FakeProcess:
    pid = 12345

    def __init__(self):
        self.signals = []
        self.killed = False

    def poll(self):
        return None

    def send_signal(self, signal_value):
        self.signals.append(signal_value)

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.killed = True


def test_supported_model_modes_resolve_without_fallback():
    for mode in ModelMode:
        resolution = resolve_model_mode(mode.value)

        assert resolution.resolved is mode
        assert not resolution.fallback_used
        assert resolution.reason == "supported"


@pytest.mark.parametrize(
    "mode",
    [None, "", "CHAT", "vision", "../chat", " chat "],
)
def test_unsupported_model_modes_fall_back_to_chat(mode):
    resolution = resolve_model_mode(mode)

    assert resolution.resolved is DEFAULT_MODEL_MODE
    assert resolution.fallback_used


def test_start_resolves_unsupported_model_mode_before_launch(monkeypatch):
    launched = {}

    def fake_popen(command, env, stdout, stderr):
        launched["command"] = command
        launched["env"] = env
        launched["stdout"] = stdout
        launched["stderr"] = stderr
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    runtime = AgentRuntime()

    assert runtime.start(
        "agent-1",
        ["python", "-m", "worker"],
        env={"AO_MODEL_MODE": "vision", "PRIVATE_TOKEN": "keep-private"},
    )

    assert launched["env"]["AO_AGENT_ID"] == "agent-1"
    assert launched["env"]["AO_MODEL_MODE"] == "chat"
    assert runtime.get_state("agent-1") is RuntimeState.RUNNING
    assert runtime.get_routing_decisions("agent-1") == [
        {
            "requested": "vision",
            "resolved": "chat",
            "fallback_used": "true",
            "reason": "unsupported",
        }
    ]


def test_start_keeps_supported_model_mode_before_launch(monkeypatch):
    launched = {}

    def fake_popen(command, env, stdout, stderr):
        launched["env"] = env
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    runtime = AgentRuntime()

    assert runtime.start(
        "agent-2",
        ["python", "-m", "worker"],
        env={"AO_MODEL_MODE": "embedding"},
    )

    assert launched["env"]["AO_MODEL_MODE"] == "embedding"
    assert runtime.get_routing_decisions("agent-2")[-1] == {
        "requested": "embedding",
        "resolved": "embedding",
        "fallback_used": "false",
        "reason": "supported",
    }


def test_failed_launch_records_one_terminal_state_without_process(monkeypatch):
    def fake_popen(command, env, stdout, stderr):
        raise OSError("boom")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    runtime = AgentRuntime()

    assert not runtime.start(
        "agent-3",
        ["python", "-m", "worker"],
        env={"AO_MODEL_MODE": "rerank"},
    )

    assert runtime.get_state("agent-3") is RuntimeState.CRASHED
    assert not runtime.is_running("agent-3")
    assert runtime.get_routing_decisions("agent-3") == [
        {
            "requested": "rerank",
            "resolved": "rerank",
            "fallback_used": "false",
            "reason": "supported",
        }
    ]
