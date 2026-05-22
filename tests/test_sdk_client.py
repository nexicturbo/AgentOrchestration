from urllib.error import URLError

import pytest

import src.sdk.client as client_module
from src.sdk.client import OrchestratorClient, OrchestratorTransportError


def test_register_agent_transport_error_has_safe_context(monkeypatch):
    def fail(_request):
        raise URLError("network down")

    monkeypatch.setattr(client_module, "urlopen", fail)
    client = OrchestratorClient(
        base_url="https://orchestrator.example",
        api_key="credential-value",
    )

    with pytest.raises(OrchestratorTransportError) as exc_info:
        client.register_agent("worker-a", "worker.processor")

    message = str(exc_info.value)
    assert "POST /agents" in message
    assert "network down" in message
    assert "credential-value" not in message
    assert "Authorization" not in message
    assert "https://orchestrator.example" not in message
