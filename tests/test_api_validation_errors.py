from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent import AgentStatus
from src.api.middleware import AuthMiddleware
from src.api import routes


class SpyRegistry:
    def __init__(self):
        self.calls = []
        self.agent_id = "11111111-1111-1111-1111-111111111111"
        self.agent = {
            "id": self.agent_id,
            "name": "worker",
            "type": "worker.processor",
            "status": AgentStatus.PENDING.value,
        }

    def list(self, status=None, group=None):
        self.calls.append(("list", status, group))
        return [self.agent]

    def register(self, name, agent_type, config=None):
        self.calls.append(("register", name, agent_type, config))
        return self.agent_id

    def get(self, agent_id):
        self.calls.append(("get", agent_id))
        return self.agent if agent_id == self.agent_id else None

    def delete(self, agent_id):
        self.calls.append(("delete", agent_id))
        return agent_id == self.agent_id

    def update_status(self, agent_id, status):
        self.calls.append(("update_status", agent_id, status))
        return agent_id == self.agent_id

    def count(self):
        self.calls.append(("count",))
        return 1


def build_client(registry):
    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    app.include_router(routes.router, prefix="/api/v2")
    routes.registry = registry
    return TestClient(app)


def auth_headers():
    return {"Authorization": "Bearer test-token"}


def validation_detail(response):
    return response.json()["detail"]


class TestPublicApiValidation:
    def test_authorized_count_uses_static_route_before_agent_lookup(self):
        registry = SpyRegistry()
        client = build_client(registry)

        response = client.get("/api/v2/agents/count", headers=auth_headers())

        assert response.status_code == 200
        assert response.json() == {"count": 1}
        assert registry.calls == [("count",)]

    def test_unauthorized_request_stops_before_registry_lookup(self):
        registry = SpyRegistry()
        client = build_client(registry)

        response = client.get("/api/v2/agents/count")

        assert response.status_code == 401
        assert registry.calls == []

    def test_malformed_status_returns_validation_error_without_lookup(self):
        registry = SpyRegistry()
        client = build_client(registry)

        response = client.get(
            "/api/v2/agents?status=bogus",
            headers=auth_headers(),
        )

        assert response.status_code == 400
        assert validation_detail(response)["code"] == "validation_error"
        message = validation_detail(response)["message"]
        assert "status must be one of" in message
        assert registry.calls == []

    def test_malformed_agent_id_returns_validation_error_without_lookup(self):
        registry = SpyRegistry()
        client = build_client(registry)

        response = client.get(
            "/api/v2/agents/not-a-uuid",
            headers=auth_headers(),
        )

        assert response.status_code == 400
        assert validation_detail(response) == {
            "code": "validation_error",
            "message": "agent_id must be a UUID",
        }
        assert registry.calls == []

    def test_blank_registration_fields_do_not_mutate_registry(self):
        registry = SpyRegistry()
        client = build_client(registry)

        response = client.post(
            "/api/v2/agents?name=%20%20&agent_type=worker.processor",
            headers=auth_headers(),
        )

        assert response.status_code == 400
        assert validation_detail(response) == {
            "code": "validation_error",
            "message": "name must not be blank",
        }
        assert registry.calls == []

    def test_authorized_valid_registration_trims_fields(self):
        registry = SpyRegistry()
        client = build_client(registry)

        response = client.post(
            "/api/v2/agents"
            "?name=%20worker%20&agent_type=%20worker.processor%20",
            headers=auth_headers(),
        )

        assert response.status_code == 200
        assert response.json() == {
            "agent_id": registry.agent_id,
            "status": "registered",
        }
        assert registry.calls == [
            ("register", "worker", "worker.processor", None)
        ]
