"""Secret environment metadata API."""

from typing import Dict, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request, status

from .auth import permission_service

router = APIRouter()


class SecretMetadataStore:
    def __init__(self):
        self._metadata: Dict[Tuple[str, str, str], Dict[str, object]] = {}
        self.lookup_count = 0

    def reset(self) -> None:
        self._metadata.clear()
        self.lookup_count = 0

    def put(
        self,
        workspace_id: str,
        project_id: str,
        name: str,
        metadata: Dict[str, object],
    ) -> None:
        public_metadata = dict(metadata)
        public_metadata.pop("value", None)
        self._metadata[(workspace_id, project_id, name)] = public_metadata

    def get(
        self,
        workspace_id: str,
        project_id: str,
        name: str,
    ) -> Optional[Dict[str, object]]:
        self.lookup_count += 1
        metadata = self._metadata.get((workspace_id, project_id, name))
        return dict(metadata) if metadata is not None else None


secret_metadata_store = SecretMetadataStore()


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}"
    "/environment/{name}/metadata"
)
async def get_environment_secret_metadata(
    workspace_id: str,
    project_id: str,
    name: str,
    request: Request,
):
    permission_service.require_secret_metadata_reader(
        request,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    metadata = secret_metadata_store.get(workspace_id, project_id, name)
    if metadata is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Secret metadata not found",
        )
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "name": name,
        "metadata": metadata,
    }
