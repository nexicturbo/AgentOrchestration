import signal

import pytest

from src.agent.runtime import AgentRuntime, RuntimeState


class FakeProcess:
    def __init__(self):
        self.signals = []
        self.wait_timeouts = []
        self.killed = False
        self.returncode = None

    def poll(self):
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        self.returncode = 0
        return self.returncode

    def kill(self):
        self.killed = True


@pytest.mark.parametrize("timeout", [-1, 0, True, "1"])
def test_stop_rejects_invalid_timeout_before_signaling(timeout):
    runtime = AgentRuntime()
    process = FakeProcess()
    runtime._processes["agent-1"] = process
    runtime._states["agent-1"] = RuntimeState.RUNNING

    with pytest.raises(ValueError, match="timeout must be a positive number"):
        runtime.stop("agent-1", timeout=timeout)

    assert process.signals == []
    assert process.wait_timeouts == []
    assert not process.killed
    assert runtime.get_state("agent-1") == RuntimeState.RUNNING


def test_stop_rejects_invalid_timeout_before_process_lookup():
    runtime = AgentRuntime()

    with pytest.raises(ValueError, match="timeout must be a positive number"):
        runtime.stop("missing-agent", timeout=-1)


def test_stop_with_positive_timeout_signals_and_stops_process():
    runtime = AgentRuntime()
    process = FakeProcess()
    runtime._processes["agent-1"] = process
    runtime._states["agent-1"] = RuntimeState.RUNNING

    assert runtime.stop("agent-1", timeout=2)

    assert process.signals == [signal.SIGTERM]
    assert process.wait_timeouts == [2]
    assert not process.killed
    assert runtime._states["agent-1"] == RuntimeState.STOPPED
