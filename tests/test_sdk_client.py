from unittest.mock import MagicMock, patch

import pytest

from src.sdk import AuthenticationError, OrchestratorClient


def test_client_requires_env_api_key_when_argument_missing(monkeypatch):
    monkeypatch.delenv("AO_API_KEY", raising=False)

    with pytest.raises(AuthenticationError, match="AO_API_KEY"):
        OrchestratorClient()


def test_client_rejects_blank_env_api_key(monkeypatch):
    monkeypatch.setenv("AO_API_KEY", "   ")

    with pytest.raises(AuthenticationError, match="AO_API_KEY"):
        OrchestratorClient()


def test_client_rejects_blank_explicit_api_key(monkeypatch):
    monkeypatch.setenv("AO_API_KEY", "valid-env-key")

    with pytest.raises(AuthenticationError, match="api_key"):
        OrchestratorClient(api_key="")


def test_client_rejects_non_string_api_key(monkeypatch):
    monkeypatch.setenv("AO_API_KEY", "valid-env-key")

    with pytest.raises(AuthenticationError, match="api_key"):
        OrchestratorClient(api_key=123)


def test_client_uses_trimmed_explicit_api_key(monkeypatch):
    monkeypatch.delenv("AO_API_KEY", raising=False)
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key=" token ",
    )
    response = MagicMock()
    response.read.return_value = b'{"agents": []}'
    response.__enter__.return_value = response

    with patch(
        "src.sdk.client.urlopen",
        return_value=response,
    ) as urlopen_mock:
        assert client.list_agents() == {"agents": []}

    request = urlopen_mock.call_args.args[0]
    assert request.full_url == "https://example.test/api/v2/agents"
    assert request.get_header("Authorization") == "Bearer token"


def test_client_uses_trimmed_env_api_key(monkeypatch):
    monkeypatch.setenv("AO_API_KEY", " env-token ")
    client = OrchestratorClient(base_url="https://example.test")
    response = MagicMock()
    response.read.return_value = b'{"agents": []}'
    response.__enter__.return_value = response

    with patch(
        "src.sdk.client.urlopen",
        return_value=response,
    ) as urlopen_mock:
        assert client.list_agents() == {"agents": []}

    request = urlopen_mock.call_args.args[0]
    assert request.get_header("Authorization") == "Bearer env-token"


def test_client_revalidates_api_key_before_each_request(monkeypatch):
    monkeypatch.delenv("AO_API_KEY", raising=False)
    client = OrchestratorClient(
        base_url="https://example.test",
        api_key="token",
    )
    client.api_key = "   "

    with patch("src.sdk.client.urlopen") as urlopen_mock:
        with pytest.raises(AuthenticationError, match="api_key"):
            client.list_agents()

    urlopen_mock.assert_not_called()
