"""
Analyst profile and desk default endpoints.
"""

from fastapi import APIRouter, Depends, Query

from models.analyst_ops import AnalystContextResponse
from services.auth import AuthenticatedUser, get_current_user, resolve_request_actor
from services.analyst_context import get_analyst_context

router = APIRouter()


@router.get("/analyst/context", response_model=AnalystContextResponse, summary="Get analyst profile, team presets, and desk defaults")
async def get_analyst_context_route(
    actor: str | None = Query(None, min_length=2, max_length=255),
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    actor_name = resolve_request_actor(
        requested_actor=actor,
        current_user=current_user,
        allow_delegate=current_user.has_permission("manage_queues") or current_user.has_permission("manage_users"),
    )
    return AnalystContextResponse(**(await get_analyst_context(actor_name)))
