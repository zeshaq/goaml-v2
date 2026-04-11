"""
Entity profile and resolution API endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from models.intelligence import (
    EntityListItem,
    EntityNetworkIntelligenceResponse,
    EntityProfileResponse,
    EntityResolutionRequest,
    WatchlistDashboardResponse,
    WatchlistRescreenRequest,
    WatchlistRescreenResponse,
)
from services.auth import AuthenticatedUser, require_permissions, resolve_request_actor
from services.entities import get_entity_profile, list_entities, list_watchlist_entities, resolve_entity, run_watchlist_rescreen
from services.maturity_features import get_entity_network_intelligence
from services.screening import ScreeningUnavailableError

router = APIRouter()


@router.get("/entities", response_model=list[EntityListItem], summary="List entities for the analyst workspace")
async def get_entities(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    query: str | None = Query(None, min_length=1, max_length=255),
    risk_level: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_permissions("view_entities")),
):
    rows = await list_entities(limit=limit, offset=offset, query=query, risk_level=risk_level)
    return [EntityListItem(**row) for row in rows]


@router.get("/entities/watchlist", response_model=WatchlistDashboardResponse, summary="Get active or historical watchlist dashboard entities")
async def get_watchlist_dashboard(
    status: str = Query("active", pattern="^(active|removed|all)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(require_permissions("view_entities")),
):
    try:
        row = await list_watchlist_entities(status=status, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return WatchlistDashboardResponse(**row)


@router.post("/entities/watchlist/rescreen", response_model=WatchlistRescreenResponse, summary="Run recurring re-screening across the watchlist")
async def post_watchlist_rescreen(
    payload: WatchlistRescreenRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("resolve_entities")),
):
    try:
        row = await run_watchlist_rescreen(
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            due_only=payload.due_only,
            limit=payload.limit,
            interval_days=payload.interval_days,
        )
    except ScreeningUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return WatchlistRescreenResponse(**row)


@router.get("/entities/{entity_id}", response_model=EntityProfileResponse, summary="Get entity profile and resolution workspace")
async def get_entity(entity_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_entities"))):
    row = await get_entity_profile(entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityProfileResponse(**row)


@router.get("/entities/{entity_id}/network-intelligence", response_model=EntityNetworkIntelligenceResponse, summary="Get network risk posture and graph-driven recommendations for an entity")
async def get_entity_network_view(
    entity_id: UUID,
    current_user: AuthenticatedUser = Depends(require_permissions("view_entities")),
):
    row = await get_entity_network_intelligence(entity_id)
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityNetworkIntelligenceResponse(**row)


@router.post("/entities/{entity_id}/rescreen", response_model=WatchlistRescreenResponse, summary="Run a watchlist re-screen for a single entity")
async def post_entity_rescreen(
    entity_id: UUID,
    payload: WatchlistRescreenRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("resolve_entities")),
):
    try:
        row = await run_watchlist_rescreen(
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
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
async def post_entity_resolution(
    entity_id: UUID,
    payload: EntityResolutionRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("resolve_entities")),
):
    try:
        row = await resolve_entity(
            entity_id,
            action=payload.action,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            note=payload.note,
            candidate_entity_id=payload.candidate_entity_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Entity not found")
    return EntityProfileResponse(**row)
