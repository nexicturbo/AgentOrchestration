"""Agent Registry — Manages agent lifecycle and metadata."""

import hashlib
import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._capability_schema_cache: Dict[str, Dict[str, str]] = {}
        self._schema_audit_log: List[Dict[str, Any]] = []

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
    ) -> str:
        config = config or {}
        capabilities = self._normalize_capabilities(
            config.get("capabilities", {})
        )
        self._reject_active_contract_conflicts(capabilities)

        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config,
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        self._cache_capabilities(agent_id, capabilities)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        capabilities = self._agent_capabilities(self._agents[agent_id])
        self._invalidate_capabilities(capabilities.keys(), "agent_deleted")
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def update_capabilities(self, agent_id: str, capabilities: Any) -> bool:
        if agent_id not in self._agents:
            return False

        normalized = self._normalize_capabilities(capabilities)
        self._reject_active_contract_conflicts(
            normalized,
            exclude_agent_id=agent_id,
        )
        agent = self._agents[agent_id]
        old_capabilities = self._agent_capabilities(agent)
        affected = set(old_capabilities) | set(normalized)

        agent["config"]["capabilities"] = capabilities
        agent["updated_at"] = time.time()
        self._invalidate_capabilities(affected, "capability_contract_changed")
        self._cache_capabilities(agent_id, normalized)
        self._audit(
            "capability_contract_updated",
            reason="cache_invalidated",
            agent_id=agent_id,
            capabilities=sorted(affected),
        )
        return True

    def resolve_capability(
        self,
        capability: str,
        expected_schema: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        candidates = [
            agent for agent in self._agents.values()
            if self._is_active(agent)
            and capability in self._agent_capabilities(agent)
        ]
        if not candidates:
            return None

        cached = self._capability_schema_cache.get(capability)
        if cached is None:
            agent = candidates[0]
            contract = self._agent_capabilities(agent)[capability]
            cached = self._schema_cache_entry(
                agent["id"],
                capability,
                contract,
            )
            self._capability_schema_cache[capability] = cached

        if expected_schema is not None:
            expected_fingerprint = self._fingerprint_schema(expected_schema)
            if expected_fingerprint != cached["schema_fingerprint"]:
                self._audit(
                    "schema_resolution_rejected",
                    capability=capability,
                    reason="stale_expected_schema",
                    expected_fingerprint=expected_fingerprint,
                    cached_fingerprint=cached["schema_fingerprint"],
                )
                raise ValueError(
                    f"stale schema for capability {capability!r}"
                )

        for agent in candidates:
            capabilities = self._agent_capabilities(agent)
            if (
                capabilities[capability]["fingerprint"]
                == cached["fingerprint"]
            ):
                return agent

        self._audit(
            "schema_resolution_rejected",
            capability=capability,
            reason="cached_schema_unavailable",
            cached_fingerprint=cached["fingerprint"],
        )
        self._capability_schema_cache.pop(capability, None)
        return None

    @property
    def schema_audit_log(self) -> List[Dict[str, Any]]:
        return list(self._schema_audit_log)

    def _normalize_capabilities(
        self,
        capabilities: Any,
    ) -> Dict[str, Dict[str, Any]]:
        normalized: Dict[str, Dict[str, Any]] = {}
        if not capabilities:
            return normalized

        if isinstance(capabilities, dict):
            items = []
            for name, contract in capabilities.items():
                if isinstance(contract, dict):
                    items.append({"name": name, **contract})
                else:
                    items.append({"name": name, "schema": contract})
        elif isinstance(capabilities, list):
            items = capabilities
        else:
            raise ValueError("capabilities must be a mapping or list")

        for item in items:
            if not isinstance(item, dict):
                raise ValueError("capability entries must be mappings")
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("capability name must be a non-empty string")
            contract = {
                "name": name,
                "version": item.get("version", "1.0"),
                "schema": item.get("schema", {}),
                "policy": item.get("policy", {}),
            }
            contract["fingerprint"] = self._fingerprint_contract(contract)
            contract["schema_fingerprint"] = self._fingerprint_schema(
                contract["schema"]
            )
            normalized[name] = contract
        return normalized

    def _fingerprint_schema(self, schema: Any) -> str:
        payload = json.dumps(
            schema,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _fingerprint_contract(self, contract: Dict[str, Any]) -> str:
        public_contract = {
            key: contract.get(key)
            for key in ("name", "version", "schema", "policy")
            if key in contract
        }
        payload = json.dumps(
            public_contract,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _agent_capabilities(
        self,
        agent: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        return self._normalize_capabilities(
            agent.get("config", {}).get("capabilities", {})
        )

    def _reject_active_contract_conflicts(
        self,
        capabilities: Dict[str, Dict[str, Any]],
        exclude_agent_id: Optional[str] = None,
    ) -> None:
        for capability, contract in capabilities.items():
            for agent in self._agents.values():
                if (
                    agent["id"] == exclude_agent_id
                    or not self._is_active(agent)
                ):
                    continue
                existing = self._agent_capabilities(agent).get(capability)
                if (
                    existing
                    and existing["fingerprint"] != contract["fingerprint"]
                ):
                    self._audit(
                        "schema_registration_rejected",
                        capability=capability,
                        reason="active_contract_conflict",
                        existing_fingerprint=existing["fingerprint"],
                        proposed_fingerprint=contract["fingerprint"],
                        agent_id=agent["id"],
                    )
                    raise ValueError(
                        f"capability {capability!r} already has an active "
                        "incompatible schema"
                    )

    def _cache_capabilities(
        self,
        agent_id: str,
        capabilities: Dict[str, Dict[str, Any]],
    ) -> None:
        for capability, contract in capabilities.items():
            self._capability_schema_cache[capability] = (
                self._schema_cache_entry(agent_id, capability, contract)
            )

    def _schema_cache_entry(
        self,
        agent_id: str,
        capability: str,
        contract: Dict[str, Any],
    ) -> Dict[str, str]:
        return {
            "agent_id": agent_id,
            "capability": capability,
            "fingerprint": contract["fingerprint"],
            "schema_fingerprint": contract["schema_fingerprint"],
        }

    def _invalidate_capabilities(
        self,
        capabilities: Set[str],
        reason: str,
    ) -> None:
        for capability in capabilities:
            if self._capability_schema_cache.pop(capability, None):
                self._audit(
                    "schema_cache_invalidated",
                    capability=capability,
                    reason=reason,
                )

    def _is_active(self, agent: Dict[str, Any]) -> bool:
        return agent["status"] in {
            AgentStatus.PENDING.value,
            AgentStatus.RUNNING.value,
            AgentStatus.PAUSED.value,
        }

    def _audit(self, action: str, **fields: Any) -> None:
        record = {
            "action": action,
            "timestamp": time.time(),
        }
        record.update(fields)
        self._schema_audit_log.append(record)

# 2019-01-29T11:24:49 update

# 2019-04-09T13:38:38 update

# 2019-04-11T11:24:12 update

# 2019-06-26T17:03:48 update

# 2019-07-03T14:55:48 update

# 2019-07-18T18:18:47 update

# 2019-11-05T11:27:19 update

# 2019-11-20T11:35:05 update

# 2019-11-23T15:28:54 update

# 2020-03-13T09:23:07 update

# 2020-03-30T19:31:18 update

# 2020-04-22T15:03:30 update

# 2020-07-21T10:00:48 update

# 2020-09-10T09:02:08 update

# 2020-09-10T13:39:12 update

# 2020-09-22T16:27:52 update

# 2020-10-15T10:33:14 update

# 2021-05-13T11:15:56 update

# 2021-07-07T14:57:13 update

# 2021-07-13T15:15:19 update

# 2021-07-27T10:18:16 update

# 2022-03-11T15:24:11 update

# 2022-09-22T13:24:20 update

# 2022-11-01T12:20:40 update

# 2023-01-30T12:32:27 update

# 2023-03-10T09:43:50 update

# 2023-05-10T14:28:01 update

# 2023-05-11T20:04:46 update

# 2023-05-30T17:00:59 update

# 2023-07-13T17:54:32 update

# 2023-07-20T19:04:20 update

# 2023-07-31T17:00:02 update

# 2023-09-05T19:42:07 update

# 2024-01-02T10:29:47 update

# 2024-09-17T12:45:29 update

# 2024-09-17T11:51:01 update

# 2024-11-06T18:20:15 update

# 2025-01-12T15:13:14 update

# 2025-01-14T20:24:39 update

# 2025-03-26T20:21:27 update

# 2025-04-10T18:27:06 update

# 2025-06-19T20:34:58 update

# 2025-06-21T20:23:53 update

# 2025-06-24T20:30:30 update

# 2025-07-03T13:28:03 update

# 2025-07-24T17:42:21 update

# 2025-08-19T17:42:23 update

# 2025-08-21T11:06:52 update

# 2025-10-24T09:10:08 update

# 2025-12-18T19:34:38 update

# 2026-02-06T11:22:22 update

# 2026-02-13T15:42:04 update

# 2026-04-10T08:16:30 update

# 2026-04-29T18:16:11 update
