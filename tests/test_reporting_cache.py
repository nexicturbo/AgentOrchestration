import pytest

from src.common.errors import AuthenticationError
from src.common.reporting import (
    ReportingAuthorizationService,
    ReportingResultCache,
)


def test_report_cache_key_includes_workspace_and_role_context():
    authz = ReportingAuthorizationService()
    cache = ReportingResultCache(authz)
    authz.grant("user-1", "workspace-a", "admin")
    authz.grant("user-1", "workspace-b", "viewer")

    admin_result = cache.get_or_compute(
        user_id="user-1",
        workspace_id="workspace-a",
        report_name="activity",
        query_params={"range": "7d"},
        producer=lambda: {"rows": ["admin"]},
        minimum_role="viewer",
    )
    viewer_result = cache.get_or_compute(
        user_id="user-1",
        workspace_id="workspace-b",
        report_name="activity",
        query_params={"range": "7d"},
        producer=lambda: {"rows": ["viewer"]},
        minimum_role="viewer",
    )

    assert admin_result == {"rows": ["admin"]}
    assert viewer_result == {"rows": ["viewer"]}
    assert len(cache._entries) == 2
    fingerprints = {key[1] for key in cache._entries}
    assert (
        "workspace-a",
        "user-1",
        "admin",
        ("reports:read",),
        1,
    ) in fingerprints
    assert (
        "workspace-b",
        "user-1",
        "viewer",
        ("reports:read",),
        1,
    ) in fingerprints


def test_role_downgrade_does_not_reuse_broader_cached_report():
    authz = ReportingAuthorizationService()
    cache = ReportingResultCache(authz)
    authz.grant("user-1", "workspace-a", "admin")
    producer_calls = []

    result = cache.get_or_compute(
        user_id="user-1",
        workspace_id="workspace-a",
        report_name="admin-summary",
        query_params={"range": "30d"},
        producer=lambda: producer_calls.append("admin") or {"private": True},
        minimum_role="admin",
    )
    assert result == {"private": True}

    authz.grant("user-1", "workspace-a", "viewer")

    with pytest.raises(AuthenticationError, match="report role denied"):
        cache.get_or_compute(
            user_id="user-1",
            workspace_id="workspace-a",
            report_name="admin-summary",
            query_params={"range": "30d"},
            producer=lambda: (
                producer_calls.append("downgraded") or {"private": False}
            ),
            minimum_role="admin",
        )

    assert producer_calls == ["admin"]


def test_workspace_removal_denies_cached_report_before_producer_runs():
    authz = ReportingAuthorizationService()
    cache = ReportingResultCache(authz)
    authz.grant("user-1", "workspace-a", "editor")
    producer_calls = []

    result = cache.get_or_compute(
        user_id="user-1",
        workspace_id="workspace-a",
        report_name="activity",
        query_params={"range": "today"},
        producer=lambda: producer_calls.append("initial") or {"rows": [1]},
        minimum_role="viewer",
    )
    assert result == {"rows": [1]}

    authz.revoke("user-1", "workspace-a")

    with pytest.raises(AuthenticationError, match="report access denied"):
        cache.get_or_compute(
            user_id="user-1",
            workspace_id="workspace-a",
            report_name="activity",
            query_params={"range": "today"},
            producer=lambda: producer_calls.append("revoked") or {"rows": [2]},
            minimum_role="viewer",
        )

    assert producer_calls == ["initial"]


def test_cached_report_is_revalidated_before_hit():
    authz = ReportingAuthorizationService()
    cache = ReportingResultCache(authz)
    context = authz.grant("user-1", "workspace-a", "editor")
    cache_key = cache.cache_key("activity", {"range": "today"}, context)
    assert cache_key[1] == (
        "workspace-a",
        "user-1",
        "editor",
        ("reports:read",),
        1,
    )

    first = cache.get_or_compute(
        user_id="user-1",
        workspace_id="workspace-a",
        report_name="activity",
        query_params={"range": "today"},
        producer=lambda: {"rows": ["fresh"]},
        minimum_role="viewer",
    )
    second = cache.get_or_compute(
        user_id="user-1",
        workspace_id="workspace-a",
        report_name="activity",
        query_params={"range": "today"},
        producer=lambda: {"rows": ["should-not-run"]},
        minimum_role="viewer",
    )

    assert first == second == {"rows": ["fresh"]}
    assert cache.audit_records[-1]["event"] == "cache_hit"
