from unittest.mock import MagicMock, patch

from src.sdk.client import OrchestratorClient


def test_base_url_trailing_slash_is_normalized():
    client = OrchestratorClient(base_url="https://api.example.test/")

    assert client.base_url == "https://api.example.test"
    assert (
        client._build_url("/agents")
        == "https://api.example.test/api/v2/agents"
    )


def test_base_url_without_trailing_slash_still_builds_canonical_route():
    client = OrchestratorClient(base_url="https://api.example.test")

    assert (
        client._build_url("/agents/agent-1")
        == "https://api.example.test/api/v2/agents/agent-1"
    )


def test_request_uses_single_api_prefix_when_base_url_has_trailing_slash():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"ok": true}'

    with patch("src.sdk.client.urlopen", return_value=response) as urlopen:
        client = OrchestratorClient(
            base_url="https://api.example.test/",
            api_key="test-key",
        )
        result = client.list_agents()

    assert result == {"ok": True}
    request = urlopen.call_args.args[0]
    assert request.full_url == "https://api.example.test/api/v2/agents"
