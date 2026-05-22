from pathlib import Path

import yaml


COMPOSE_PATH = Path("infra/docker-compose.yml")
DOCS_PATH = Path("docs/sidecar-runtime.md")


def _load_compose():
    with COMPOSE_PATH.open() as compose_file:
        return yaml.safe_load(compose_file)


def _sidecar_services(compose):
    return {
        name: service
        for name, service in compose["services"].items()
        if service.get("labels", {}).get("ao.role") == "sidecar"
    }


def _sidecar_runtime_violations(compose):
    violations = []
    for name, service in _sidecar_services(compose).items():
        if service.get("read_only") is not True:
            violations.append(f"{name} must set read_only: true")
        if not service.get("tmpfs"):
            violations.append(f"{name} must declare tmpfs writable paths")
        if "no-new-privileges:true" not in service.get("security_opt", []):
            violations.append(f"{name} must disable privilege escalation")
    return violations


def test_sidecars_use_read_only_root_filesystems():
    compose = _load_compose()

    assert _sidecar_services(compose)
    assert _sidecar_runtime_violations(compose) == []


def test_compose_validation_rejects_missing_sidecar_read_only_setting():
    compose = _load_compose()
    compose["services"]["metrics-sidecar"].pop("read_only")

    assert "metrics-sidecar must set read_only: true" in (
        _sidecar_runtime_violations(compose)
    )


def test_sidecar_writable_paths_are_documented():
    compose = _load_compose()
    docs = DOCS_PATH.read_text()

    for name, service in _sidecar_services(compose).items():
        assert name in docs
        for mount in service["tmpfs"]:
            path = mount.split(":", 1)[0]
            assert path in docs
