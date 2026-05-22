import pytest

from src.sdk.client import OrchestratorClient


class SpyClient(OrchestratorClient):
    def __init__(self):
        super().__init__(base_url="https://example.test", api_key="test")
        self.requests = []

    def _request(self, method, path, data=None):
        self.requests.append((method, path, data))
        return {"ok": True, "data": data}


class TestOrchestratorClient:
    def test_register_agent_rejects_blank_name_before_request(self):
        client = SpyClient()

        with pytest.raises(ValueError, match="agent name must not be blank"):
            client.register_agent("   ", "worker.processor")

        assert client.requests == []

    def test_register_agent_rejects_empty_name_before_request(self):
        client = SpyClient()

        with pytest.raises(ValueError, match="agent name must not be blank"):
            client.register_agent("", "worker.processor")

        assert client.requests == []

    def test_register_agent_rejects_non_string_name_before_request(self):
        client = SpyClient()

        with pytest.raises(ValueError, match="agent name must be a string"):
            client.register_agent(None, "worker.processor")

        assert client.requests == []

    def test_register_agent_trims_valid_name_before_payload(self):
        client = SpyClient()

        response = client.register_agent("  worker  ", "worker.processor")

        assert response == {
            "ok": True,
            "data": {
                "name": "worker",
                "agent_type": "worker.processor",
                "config": {},
            },
        }
        assert client.requests == [
            (
                "POST",
                "/agents",
                {
                    "name": "worker",
                    "agent_type": "worker.processor",
                    "config": {},
                },
            )
        ]
