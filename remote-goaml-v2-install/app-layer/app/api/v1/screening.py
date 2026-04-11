"""
goAML-V2 screening API endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException

from models.casework import ScreenEntityRequest, ScreeningPanel, ScreeningResponse, ScreeningResultItem
from services.auth import AuthenticatedUser, require_permissions, resolve_request_actor
from services.screening import (
    ScreeningUnavailableError,
    build_screening_panels,
    get_screening_sample_queries,
    screen_entity,
)

router = APIRouter()


@router.post("/screen", response_model=ScreeningResponse, summary="Screen entity against sanctions data")
async def post_screen(
    payload: ScreenEntityRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("view_entities")),
):
    try:
        rows = await screen_entity(
            payload.model_copy(update={"screened_by": resolve_request_actor(requested_actor=payload.screened_by, current_user=current_user)})
        )
    except ScreeningUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return ScreeningResponse(
        query=payload.entity_name,
        result_count=len(rows),
        results=[ScreeningResultItem(**row) for row in rows],
        panels=[ScreeningPanel(**panel) for panel in build_screening_panels(rows)],
        sample_queries=get_screening_sample_queries(),
    )
