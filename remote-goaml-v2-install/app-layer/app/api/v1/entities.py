"""
Entity profile and resolution API endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from models.intelligence import EntityListItem, EntityProfileResponse, EntityResolutionRequest, WatchlistDashboardResponse
from services.entities import get_entity_profile, list_entities, list_watchlist_entities, resolve_entity

router = APIRouter()


@router.get("/entities", response_model=list[EntityListItem], summary="List entities for the analyst workspace")
async def get_entities(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, min_length=1, max_length=255),
    risk_level: str | None = Query(None),
):
    rows = await list_entities(limit=limit, offset=offset, query=query, risk_level=risk_level)
    return [EntityListItem(**row) for row in rows]


@router.get("/entities/watchlist", response_model=WatchlistDashboardResponse, summary="Get active or historical watchlist dashboard entities")
async def get_watchlist_dashboard(
    status: str = Query("active", pattern="^(active|removed|all)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        row = await list_watchlist_entities(status=status, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WatchlistDashboardResponse(**row)


@router.get("/entities/{entity_id}", response_model=EntityProfileResponse, summary="Get entity profile and resolution workspace")
async def get_entity(entity_id: UUID):
    row = await get_entity_profile(entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityProfileResponse(**row)


@router.post("/entities/{entity_id}/resolve", response_model=EntityProfileResponse, summary="Apply an entity resolution action")
async def post_entity_resolution(entity_id: UUID, payload: EntityResolutionRequest):
    try:
        row = await resolve_entity(
            entity_id,
            action=payload.action,
            actor=payload.actor,
            note=payload.note,
            candidate_entity_id=payload.candidate_entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityProfileResponse(**row)
