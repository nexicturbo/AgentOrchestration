"""Plugin manifest validation and hook registration support."""

from dataclasses import dataclass
from threading import RLock
from typing import Any, Callable, Dict, Iterable, List, Mapping, Tuple


class PluginManifestError(ValueError):
    """Raised when a plugin manifest is unsafe to load."""


@dataclass(frozen=True)
class PluginLoadRecord:
    plugin_id: str
    status: str
    reason: str
    hooks_registered: int = 0


@dataclass(frozen=True)
class ValidatedPluginManifest:
    plugin_id: str
    hooks: Tuple[Tuple[str, Tuple[Callable, ...]], ...]


class PluginManifestValidator:
    def __init__(self, allowed_events: Iterable[str]):
        self._allowed_events = frozenset(allowed_events)

    def validate(
        self,
        manifest: Mapping[str, Any],
    ) -> ValidatedPluginManifest:
        if not isinstance(manifest, Mapping):
            raise PluginManifestError("manifest must be a mapping")

        name = manifest.get("name")
        if not isinstance(name, str) or not name.strip():
            raise PluginManifestError(
                "manifest name must be a non-empty string"
            )

        version = manifest.get("version")
        if not isinstance(version, str) or not version.strip():
            raise PluginManifestError(
                "manifest version must be a non-empty string"
            )

        hooks = manifest.get("hooks")
        if not isinstance(hooks, Mapping) or not hooks:
            raise PluginManifestError(
                "manifest hooks must be a non-empty mapping"
            )

        normalized: List[Tuple[str, Tuple[Callable, ...]]] = []
        for event, callbacks in hooks.items():
            if event not in self._allowed_events:
                raise PluginManifestError(f"unsupported hook event: {event}")
            if not isinstance(callbacks, (list, tuple)) or not callbacks:
                raise PluginManifestError(
                    f"hook {event} must list at least one callback"
                )
            if not all(callable(callback) for callback in callbacks):
                raise PluginManifestError(
                    f"hook {event} contains a non-callable callback"
                )
            normalized.append((event, tuple(callbacks)))

        plugin_id = f"{name.strip()}@{version.strip()}"
        return ValidatedPluginManifest(
            plugin_id=plugin_id,
            hooks=tuple(normalized),
        )


class PluginRuntime:
    def __init__(self, allowed_events: Iterable[str]):
        self._lock = RLock()
        self._validator = PluginManifestValidator(allowed_events)
        self._records: Dict[str, PluginLoadRecord] = {}

    def load_manifest(
        self,
        manifest: Mapping[str, Any],
        hook_store: Dict[str, List[Callable]],
    ) -> PluginLoadRecord:
        try:
            validated = self._validator.validate(manifest)
        except PluginManifestError as exc:
            plugin_id = self._rejected_plugin_id(manifest)
            record = PluginLoadRecord(
                plugin_id=plugin_id,
                status="rejected",
                reason=str(exc),
            )
            with self._lock:
                self._records[plugin_id] = record
            return record

        with self._lock:
            existing = self._records.get(validated.plugin_id)
            if existing and existing.status == "loaded":
                return existing

            hooks_registered = sum(
                len(callbacks) for _, callbacks in validated.hooks
            )
            for event, callbacks in validated.hooks:
                hook_store[event].extend(callbacks)

            record = PluginLoadRecord(
                plugin_id=validated.plugin_id,
                status="loaded",
                reason="validated",
                hooks_registered=hooks_registered,
            )
            self._records[validated.plugin_id] = record
            return record

    def load_records(self) -> Dict[str, PluginLoadRecord]:
        with self._lock:
            return dict(self._records)

    def _rejected_plugin_id(self, manifest: Any) -> str:
        if not isinstance(manifest, Mapping):
            return "<invalid>@<invalid>"
        name = manifest.get("name")
        version = manifest.get("version")
        safe_name = (
            name.strip()
            if isinstance(name, str) and name.strip()
            else "<invalid>"
        )
        safe_version = (
            version.strip()
            if isinstance(version, str) and version.strip()
            else "<invalid>"
        )
        return f"{safe_name}@{safe_version}"
