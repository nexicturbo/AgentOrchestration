import signal
import subprocess

from src.agent.runtime import AgentRuntime, RuntimeState


class FakeProcess:
    def __init__(self, returncode=None, on_signal=None, timeout_once=False):
        self.returncode = returncode
        self.on_signal = on_signal
        self.timeout_once = timeout_once
        self.waits = 0
        self.killed = False
        self.signals = []

    def poll(self):
        return self.returncode

    def send_signal(self, value):
        self.signals.append(value)
        if self.on_signal:
            self.on_signal(value)

    def wait(self, timeout=None):
        self.waits += 1
        if self.timeout_once and self.waits == 1:
            raise subprocess.TimeoutExpired("agent", timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_failure_reason_is_durable_before_shutdown_signal():
    runtime = AgentRuntime()
    observed = {}

    def on_signal(value):
        observed["signal"] = value
        observed["outcome"] = runtime.get_terminal_outcome("agent-1")

    runtime._processes["agent-1"] = FakeProcess(on_signal=on_signal)
    runtime._states["agent-1"] = RuntimeState.RUNNING

    assert runtime.stop("agent-1", failure_reason="heartbeat expired")

    outcome = runtime.get_terminal_outcome("agent-1")
    assert observed["signal"] == signal.SIGTERM
    assert observed["outcome"] is outcome
    assert outcome.state == RuntimeState.CRASHED
    assert outcome.reason == "heartbeat expired"
    assert runtime.get_state("agent-1") == RuntimeState.CRASHED


def test_forced_kill_does_not_overwrite_recorded_failure_reason():
    runtime = AgentRuntime()
    proc = FakeProcess(timeout_once=True)
    runtime._processes["agent-2"] = proc
    runtime._states["agent-2"] = RuntimeState.RUNNING

    assert runtime.stop("agent-2", timeout=0, failure_reason="worker shutdown")

    outcome = runtime.get_terminal_outcome("agent-2")
    assert proc.killed
    assert outcome.state == RuntimeState.CRASHED
    assert outcome.reason == "worker shutdown"
    assert runtime.get_state("agent-2") == RuntimeState.CRASHED


def test_process_exit_records_only_one_terminal_outcome():
    runtime = AgentRuntime()
    runtime._processes["agent-3"] = FakeProcess(returncode=1)

    assert runtime.get_state("agent-3") == RuntimeState.CRASHED
    first = runtime.get_terminal_outcome("agent-3")
    runtime._processes["agent-3"].returncode = 0

    assert runtime.get_state("agent-3") == RuntimeState.CRASHED
    assert runtime.get_terminal_outcome("agent-3") is first
