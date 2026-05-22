import time

import pytest
from fastapi.testclient import TestClient

from src.api import routes
from src.api.collaboration import (
    CollaborationAuthorizationError,
    CollaborationPermissionService,
    SavedViewSharingService,
)
from src.api.server import create_app


def make_service():
    permissions = CollaborationPermissionService()
    permissions.add_principal(
        "user-1",
        {"workspace-a": "admin", "workspace-b": "member"},
        scopes={"saved_views:share"},
    )
    permissions.issue_api_token(
        "valid-token",
        "user-1",
        scopes={"saved_views:share"},
    )
    permissions.issue_session(
        "valid-session",
        "user-1",
        scopes={"saved_views:share"},
    )
    service = SavedViewSharingService(permissions)
    service.add_saved_view("view-1", "workspace-a", "user-1")
    return permissions, service


def configure_route_service():
    permissions, service = make_service()
    routes.collaboration_permissions = permissions
    routes.saved_view_sharing = service
    return permissions, service


def test_share_view_allows_authorized_api_token_member():
    _, service = make_service()

    record = service.share_view(
        "view-1",
        "workspace-a",
        "workspace-b",
        {"Authorization": "Bearer valid-token"},
        {},
    )

    assert record.view_id == "view-1"
    assert record.source_workspace_id == "workspace-a"
    assert record.target_workspace_id == "workspace-b"
    assert record.shared_by == "user-1"
    assert service.list_shares() == [record]


def test_share_view_allows_authorized_browser_session_route():
    configure_route_service()
    client = TestClient(create_app())
    client.cookies.set("ao_session", "valid-session")

    response = client.post(
        "/api/v2/saved-views/view-1/share",
        params={
            "workspace_id": "workspace-a",
            "target_workspace_id": "workspace-b",
        },
    )

    assert response.status_code == 200
    assert response.json()["view_id"] == "view-1"
    assert response.json()["shared_by"] == "user-1"


def test_share_view_denies_anonymous_before_lookup_mutation():
    _, service = make_service()

    with pytest.raises(
        CollaborationAuthorizationError,
        match="credentials are required",
    ):
        service.share_view("view-1", "workspace-a", "workspace-b", {}, {})

    assert service.list_shares() == []


def test_share_view_denies_revoked_api_token():
    permissions, service = make_service()
    permissions.revoke_api_token("valid-token")

    with pytest.raises(CollaborationAuthorizationError, match="revoked"):
        service.share_view(
            "view-1",
            "workspace-a",
            "workspace-b",
            {"Authorization": "Bearer valid-token"},
            {},
        )


def test_share_view_denies_expired_api_token():
    permissions, service = make_service()
    permissions.issue_api_token(
        "expired-token",
        "user-1",
        scopes={"saved_views:share"},
        expires_at=time.time() - 1,
    )

    with pytest.raises(CollaborationAuthorizationError, match="expired"):
        service.share_view(
            "view-1",
            "workspace-a",
            "workspace-b",
            {"Authorization": "Bearer expired-token"},
            {},
        )


def test_share_view_denies_stale_membership_token():
    permissions, service = make_service()
    permissions.update_workspace_role("user-1", "workspace-a", "viewer")

    with pytest.raises(CollaborationAuthorizationError, match="stale"):
        service.share_view(
            "view-1",
            "workspace-a",
            "workspace-b",
            {"Authorization": "Bearer valid-token"},
            {},
        )


def test_share_view_denies_insufficient_credential_scope():
    permissions, service = make_service()
    permissions.issue_api_token(
        "wrong-scope",
        "user-1",
        scopes={"saved_views:read"},
    )

    with pytest.raises(
        CollaborationAuthorizationError,
        match="credential is missing required scope",
    ):
        service.share_view(
            "view-1",
            "workspace-a",
            "workspace-b",
            {"Authorization": "Bearer wrong-scope"},
            {},
        )


def test_share_view_denies_insufficient_principal_scope():
    permissions, service = make_service()
    permissions.add_principal(
        "unscoped-user",
        {"workspace-a": "admin", "workspace-b": "member"},
        scopes={"saved_views:read"},
    )
    permissions.issue_api_token(
        "unscoped-token",
        "unscoped-user",
        scopes={"saved_views:share"},
    )

    with pytest.raises(
        CollaborationAuthorizationError,
        match="principal is missing required scope",
    ):
        service.share_view(
            "view-1",
            "workspace-a",
            "workspace-b",
            {"Authorization": "Bearer unscoped-token"},
            {},
        )


def test_share_view_denies_insufficient_source_workspace_role():
    permissions, service = make_service()
    permissions.add_principal(
        "viewer",
        {"workspace-a": "viewer", "workspace-b": "member"},
        scopes={"saved_views:share"},
    )
    permissions.issue_api_token(
        "viewer-token",
        "viewer",
        scopes={"saved_views:share"},
    )

    with pytest.raises(CollaborationAuthorizationError, match="role"):
        service.share_view(
            "view-1",
            "workspace-a",
            "workspace-b",
            {"Authorization": "Bearer viewer-token"},
            {},
        )


def test_share_view_denies_missing_target_workspace_membership():
    permissions, service = make_service()
    permissions.update_workspace_role("user-1", "workspace-b", None)
    permissions.issue_api_token(
        "fresh-token",
        "user-1",
        scopes={"saved_views:share"},
    )

    with pytest.raises(CollaborationAuthorizationError, match="member"):
        service.share_view(
            "view-1",
            "workspace-a",
            "workspace-b",
            {"Authorization": "Bearer fresh-token"},
            {},
        )


def test_share_view_lookup_is_scoped_to_authenticated_workspace():
    _, service = make_service()
    service.add_saved_view("external-view", "workspace-c", "other-user")

    with pytest.raises(CollaborationAuthorizationError, match="unknown"):
        service.share_view(
            "external-view",
            "workspace-a",
            "workspace-b",
            {"Authorization": "Bearer valid-token"},
            {},
        )

    assert service.list_shares() == []


def test_share_view_denies_disabled_principal_on_route():
    permissions, _ = configure_route_service()
    permissions.disable_principal("user-1")
    client = TestClient(create_app())

    response = client.post(
        "/api/v2/saved-views/view-1/share",
        params={
            "workspace_id": "workspace-a",
            "target_workspace_id": "workspace-b",
        },
        headers={"Authorization": "Bearer valid-token"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "principal is disabled"


def test_share_view_audit_uses_sanitized_identifiers():
    _, service = make_service()

    service.share_view(
        "view-1",
        "workspace-a",
        "workspace-b",
        {"Authorization": "Bearer valid-token"},
        {},
    )

    audit = service.audit_log[0]
    assert audit["action"] == "shared"
    assert "view-1" not in audit.values()
    assert "workspace-a" not in audit.values()
    assert "workspace-b" not in audit.values()
    assert "user-1" not in audit.values()
