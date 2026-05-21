"""Shared service for optimistic agent config updates."""

import copy
import re
import time
from typing import Any, Dict, Optional


CONFIG_VERSION_FIELD = "_config_version"
ETAG_RE = re.compile(r'^"(?P<version>[1-9]\d*)"$')


class AgentConfigUpdateError(Exception):
    """Deterministic API error raised before unsafe config mutation."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AgentConfigService:
    """Apply config updates only when auth, input, and ETag are current."""

    def __init__(self, registry):
        self.registry = registry

    def update_config(
        self,
        agent_id: str,
        payload: Any,
        if_match: Optional[str],
        authorization: Optional[str],
    ) -> Dict[str, Any]:
        self._validate_authorization(authorization)
        config = self._validate_payload(payload)
        expected_version = self._validate_etag(if_match)

        agent = self.registry.get(agent_id)
        if agent is None:
            raise AgentConfigUpdateError(404, "Agent not found")

        current_version = self._current_version(agent)
        if expected_version != current_version:
            raise AgentConfigUpdateError(412, "Agent config ETag is stale")

        next_version = current_version + 1
        agent["config"] = copy.deepcopy(config)
        agent[CONFIG_VERSION_FIELD] = next_version
        agent["updated_at"] = time.time()

        return {
            "agent_id": agent_id,
            "config": copy.deepcopy(agent["config"]),
            "etag": self.format_etag(next_version),
        }

    def current_etag(self, agent_id: str) -> str:
        agent = self.registry.get(agent_id)
        if agent is None:
            raise AgentConfigUpdateError(404, "Agent not found")
        return self.format_etag(self._current_version(agent))

    def read_config(
        self,
        agent_id: str,
        authorization: Optional[str],
    ) -> Dict[str, Any]:
        self._validate_authorization(authorization)

        agent = self.registry.get(agent_id)
        if agent is None:
            raise AgentConfigUpdateError(404, "Agent not found")

        return {
            "agent_id": agent_id,
            "config": copy.deepcopy(agent.get("config", {})),
            "etag": self.format_etag(self._current_version(agent)),
        }

    @staticmethod
    def format_etag(version: int) -> str:
        return f'"{version}"'

    @staticmethod
    def _validate_authorization(authorization: Optional[str]) -> None:
        if not authorization:
            raise AgentConfigUpdateError(401, "Authorization required")
        if (
            not authorization.startswith("Bearer ")
            or authorization == "Bearer "
        ):
            raise AgentConfigUpdateError(401, "Authorization required")

    @staticmethod
    def _validate_payload(payload: Any) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise AgentConfigUpdateError(400, "Request body must be an object")
        if "config" not in payload:
            raise AgentConfigUpdateError(400, "Missing config")
        if not isinstance(payload["config"], dict):
            raise AgentConfigUpdateError(400, "Config must be an object")
        return payload["config"]

    @staticmethod
    def _validate_etag(if_match: Optional[str]) -> int:
        if if_match is None:
            raise AgentConfigUpdateError(428, "If-Match header required")
        match = ETAG_RE.match(if_match)
        if not match:
            raise AgentConfigUpdateError(
                400,
                "If-Match must be a quoted version",
            )
        return int(match.group("version"))

    @staticmethod
    def _current_version(agent: Dict[str, Any]) -> int:
        version = agent.get(CONFIG_VERSION_FIELD, 1)
        if isinstance(version, int) and version > 0:
            return version
        return 1
