"""
Entity profile and resolution API endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from models.intelligence import (
    EntityListItem,
    EntityProfileResponse,
    EntityResolutionRequest,
    WatchlistDashboardResponse,
    WatchlistRescreenRequest,
    WatchlistRescreenResponse,
)
from services.entities import get_entity_profile, list_entities, list_watchlist_entities, resolve_entity, run_watchlist_rescreen
from services.screening import ScreeningUnavailableError

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


@router.post("/entities/watchlist/rescreen", response_model=WatchlistRescreenResponse, summary="Run recurring re-screening across the watchlist")
async def post_watchlist_rescreen(payload: WatchlistRescreenRequest):
    try:
        row = await run_watchlist_rescreen(
            actor=payload.actor,
            due_only=payload.due_only,
            limit=payload.limit,
            interval_days=payload.interval_days,
        )
    except ScreeningUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return WatchlistRescreenResponse(**row)


@router.get("/entities/{entity_id}", response_model=EntityProfileResponse, summary="Get entity profile and resolution workspace")
async def get_entity(entity_id: UUID):
    row = await get_entity_profile(entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityProfileResponse(**row)


@router.post("/entities/{entity_id}/rescreen", response_model=WatchlistRescreenResponse, summary="Run a watchlist re-screen for a single entity")
async def post_entity_rescreen(entity_id: UUID, payload: WatchlistRescreenRequest):
    try:
        row = await run_watchlist_rescreen(
            actor=payload.actor,
            due_only=False,
            limit=1,
            interval_days=payload.interval_days,
            entity_id=entity_id,
        )
    except ScreeningUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return WatchlistRescreenResponse(**row)


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
