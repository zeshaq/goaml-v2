"""
Saved desk views for analyst productivity.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from models.analyst_ops import SavedViewCreateRequest, SavedViewDeleteResponse, SavedViewItem
from services.auth import AuthenticatedUser, get_current_user, resolve_request_actor
from services.saved_views import create_saved_view, delete_saved_view, list_saved_views

router = APIRouter()


@router.get("/saved-views", response_model=list[SavedViewItem], summary="List saved desk views for a scope")
async def get_saved_views(
    scope: str = Query(..., min_length=2),
    owner: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    owner_name = resolve_request_actor(
        requested_actor=owner,
        current_user=current_user,
        allow_delegate=current_user.has_permission("manage_queues") or current_user.has_permission("manage_users"),
    )
    return [SavedViewItem(**row) for row in (await list_saved_views(scope=scope, owner=owner_name))]


@router.post("/saved-views", response_model=SavedViewItem, status_code=status.HTTP_201_CREATED, summary="Create or update a saved desk view")
async def post_saved_view(payload: SavedViewCreateRequest, current_user: AuthenticatedUser = Depends(get_current_user)):
    try:
        owner = resolve_request_actor(
            requested_actor=payload.owner,
            current_user=current_user,
            allow_delegate=current_user.has_permission("manage_queues") or current_user.has_permission("manage_users"),
        )
        return SavedViewItem(**(await create_saved_view(payload.model_dump() | {"owner": owner})))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/saved-views/{view_id}", response_model=SavedViewDeleteResponse, summary="Delete a saved desk view")
async def delete_saved_view_route(view_id: UUID, current_user: AuthenticatedUser = Depends(get_current_user)):
    deleted = await delete_saved_view(view_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Saved view not found")
    return SavedViewDeleteResponse(status="deleted", id=view_id)
