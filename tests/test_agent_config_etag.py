from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.agent.registry import AgentRegistry
from src.api import routes
from src.api.agent_config import AgentConfigService, AgentConfigUpdateError


AUTH_HEADERS = {"Authorization": "Bearer test-token", "If-Match": '"1"'}


class LookupSpyRegistry(AgentRegistry):
    def __init__(self):
        super().__init__()
        self.get_calls = 0

    def get(self, agent_id):
        self.get_calls += 1
        return super().get(agent_id)


def assert_config_error(status_code, func, *args, **kwargs):
    with pytest.raises(AgentConfigUpdateError) as exc_info:
        func(*args, **kwargs)
    assert exc_info.value.status_code == status_code


def test_unauthorized_config_update_never_reads_or_mutates_agent():
    registry = LookupSpyRegistry()
    agent_id = registry.register(
        "secured-agent",
        "worker.processor",
        {"mode": "current"},
    )
    service = AgentConfigService(registry)

    assert_config_error(
        401,
        service.update_config,
        agent_id,
        {"config": {"mode": "new"}},
        '"1"',
        None,
    )

    assert registry.get_calls == 0
    assert registry._agents[agent_id]["config"] == {"mode": "current"}


def test_malformed_config_update_never_reads_or_mutates_agent():
    registry = LookupSpyRegistry()
    agent_id = registry.register(
        "validated-agent",
        "worker.processor",
        {"mode": "current"},
    )
    service = AgentConfigService(registry)

    assert_config_error(
        400,
        service.update_config,
        agent_id,
        {"config": "not-an-object"},
        '"1"',
        "Bearer test-token",
    )

    assert registry.get_calls == 0
    assert registry._agents[agent_id]["config"] == {"mode": "current"}


def test_malformed_etag_update_never_reads_or_mutates_agent():
    registry = LookupSpyRegistry()
    agent_id = registry.register(
        "etag-agent",
        "worker.processor",
        {"mode": "current"},
    )
    service = AgentConfigService(registry)

    assert_config_error(
        400,
        service.update_config,
        agent_id,
        {"config": {"mode": "new"}},
        "1",
        "Bearer test-token",
    )

    assert registry.get_calls == 0
    assert registry._agents[agent_id]["config"] == {"mode": "current"}


def test_stale_etag_update_is_rejected_without_overwriting_config():
    registry = AgentRegistry()
    agent_id = registry.register(
        "optimistic-agent",
        "worker.processor",
        {"mode": "first"},
    )
    service = AgentConfigService(registry)

    result = service.update_config(
        agent_id,
        {"config": {"mode": "second"}},
        '"1"',
        "Bearer test-token",
    )
    assert result["etag"] == '"2"'

    assert_config_error(
        412,
        service.update_config,
        agent_id,
        {"config": {"mode": "stale-write"}},
        '"1"',
        "Bearer test-token",
    )

    assert registry.get(agent_id)["config"] == {"mode": "second"}


def test_missing_if_match_update_never_reads_or_mutates_agent():
    registry = LookupSpyRegistry()
    agent_id = registry.register(
        "required-etag-agent",
        "worker.processor",
        {"mode": "current"},
    )
    service = AgentConfigService(registry)

    assert_config_error(
        428,
        service.update_config,
        agent_id,
        {"config": {"mode": "new"}},
        None,
        "Bearer test-token",
    )

    assert registry.get_calls == 0
    assert registry._agents[agent_id]["config"] == {"mode": "current"}


def test_config_read_returns_current_etag_for_next_optimistic_update():
    registry = AgentRegistry()
    agent_id = registry.register(
        "read-agent",
        "worker.processor",
        {"mode": "current"},
    )
    service = AgentConfigService(registry)

    result = service.read_config(agent_id, "Bearer test-token")

    assert result == {
        "agent_id": agent_id,
        "config": {"mode": "current"},
        "etag": '"1"',
    }


def test_authorized_route_updates_config_and_returns_next_etag():
    client = TestClient(_route_app())
    agent_id = routes.registry.register(
        "route-agent",
        "worker.processor",
        {"mode": "current"},
    )

    response = client.patch(
        f"/api/v2/agents/{agent_id}/config",
        headers=AUTH_HEADERS,
        json={"config": {"mode": "updated"}},
    )

    assert response.status_code == 200
    assert response.headers["etag"] == '"2"'
    assert response.json() == {
        "agent_id": agent_id,
        "config": {"mode": "updated"},
    }
    assert routes.registry.get(agent_id)["config"] == {"mode": "updated"}


def test_route_get_config_returns_etag_for_optimistic_update():
    client = TestClient(_route_app())
    agent_id = routes.registry.register(
        "route-read-agent",
        "worker.processor",
        {"mode": "current"},
    )

    response = client.get(
        f"/api/v2/agents/{agent_id}/config",
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    assert response.headers["etag"] == '"1"'
    assert response.json() == {
        "agent_id": agent_id,
        "config": {"mode": "current"},
    }


def test_unauthorized_route_returns_deterministic_4xx():
    client = TestClient(_route_app())
    agent_id = routes.registry.register(
        "unauthorized-route-agent",
        "worker.processor",
        {"mode": "current"},
    )

    response = client.patch(
        f"/api/v2/agents/{agent_id}/config",
        headers={"If-Match": '"1"'},
        json={"config": {"mode": "updated"}},
    )

    assert response.status_code == 401
    assert routes.registry.get(agent_id)["config"] == {"mode": "current"}


def test_malformed_route_returns_deterministic_4xx():
    client = TestClient(_route_app())
    agent_id = routes.registry.register(
        "malformed-route-agent",
        "worker.processor",
        {"mode": "current"},
    )

    response = client.patch(
        f"/api/v2/agents/{agent_id}/config",
        headers=AUTH_HEADERS,
        json={"config": ["bad"]},
    )

    assert response.status_code == 400
    assert routes.registry.get(agent_id)["config"] == {"mode": "current"}


def _route_app():
    routes.registry = AgentRegistry()
    routes.config_service = AgentConfigService(routes.registry)

    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v2")
    return app
