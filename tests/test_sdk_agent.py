import pytest

from src.sdk.agent import BaseAgent


class DemoAgent(BaseAgent):
    async def setup(self):
        pass

    async def handle_task(self, task):
        return task

    async def cleanup(self):
        pass


def test_set_metadata_rejects_empty_key():
    agent = DemoAgent("agent-1", "demo")

    with pytest.raises(ValueError, match="non-empty string"):
        agent.set_metadata("", "ambiguous")

    assert agent._metadata == {}


@pytest.mark.parametrize("key", ["   ", None, 123])
def test_set_metadata_rejects_invalid_keys_without_mutation(key):
    agent = DemoAgent("agent-1", "demo")
    agent.set_metadata("region", "us-east")

    with pytest.raises(ValueError, match="non-empty string"):
        agent.set_metadata(key, "ambiguous")

    assert agent._metadata == {"region": "us-east"}


def test_metadata_keys_are_trimmed_for_consistent_lookup():
    agent = DemoAgent("agent-1", "demo")

    agent.set_metadata(" region ", "us-east")

    assert agent._metadata == {"region": "us-east"}
    assert agent.get_metadata("region") == "us-east"
    assert agent.get_metadata(" region ") == "us-east"
    assert agent.get_metadata("missing", "fallback") == "fallback"
