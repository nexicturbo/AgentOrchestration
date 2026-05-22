import pytest

from src.agent.sandbox import AgentSandbox


def test_sandbox_resolves_relative_symlink_base_path(tmp_path, monkeypatch):
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    link_root = tmp_path / "sandbox-link"
    link_root.symlink_to(real_root, target_is_directory=True)
    monkeypatch.chdir(tmp_path)

    sandbox = AgentSandbox("sandbox-link")

    assert sandbox.base_path == real_root.resolve()
    child = sandbox.create("agent-1")
    assert child == real_root / "agent-1"
    assert sandbox.get_path("agent-1") == child


def test_sandbox_rejects_parent_directory_escape(tmp_path):
    sandbox = AgentSandbox(tmp_path / "base")

    with pytest.raises(ValueError, match="escapes base path"):
        sandbox.create("../outside")

    assert sandbox.get_path("../outside") is None
    assert not (tmp_path / "outside").exists()


def test_sandbox_rejects_symlink_child_escape(tmp_path):
    base = tmp_path / "base"
    base.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    (base / "linked").symlink_to(external, target_is_directory=True)
    sandbox = AgentSandbox(base)

    with pytest.raises(ValueError, match="escapes base path"):
        sandbox.create("linked/agent-1")

    assert sandbox.get_path("linked/agent-1") is None
    assert not (external / "agent-1").exists()
