"""
Graph exploration API endpoints.
"""

from fastapi import APIRouter, Depends

from models.intelligence import (
    GraphDrilldownRequest,
    GraphDrilldownResponse,
    GraphExploreRequest,
    GraphExploreResponse,
    GraphPathfindRequest,
    GraphPathfindResponse,
    GraphSyncRequest,
    GraphSyncResponse,
)
from services.auth import AuthenticatedUser, require_permissions
from services.graph import explore_graph
from services.graph_sync import find_graph_paths, get_graph_drilldown, sync_graph_from_postgres

router = APIRouter()


@router.post("/graph/explore", response_model=GraphExploreResponse, summary="Explore AML relationship graph")
async def post_graph_explore(
    payload: GraphExploreRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("view_graph")),
):
    data = await explore_graph(payload.query, payload.hops, payload.limit)
    return GraphExploreResponse(**data)


@router.post("/graph/drilldown", response_model=GraphDrilldownResponse, summary="Drill into a persisted graph node")
async def post_graph_drilldown(
    payload: GraphDrilldownRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("view_graph")),
):
    data = await get_graph_drilldown(payload.node_id, payload.hops, payload.limit)
    return GraphDrilldownResponse(**data)


@router.post("/graph/pathfind", response_model=GraphPathfindResponse, summary="Find case-centric paths through the persisted graph")
async def post_graph_pathfind(
    payload: GraphPathfindRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("view_graph")),
):
    data = await find_graph_paths(
        source_node_id=payload.source_node_id,
        target_node_id=payload.target_node_id,
        target_query=payload.target_query,
        max_hops=payload.max_hops,
        limit=payload.limit,
    )
    return GraphPathfindResponse(**data)


@router.post("/graph/sync", response_model=GraphSyncResponse, summary="Sync PostgreSQL AML data into persistent Neo4j graph")
async def post_graph_sync(
    payload: GraphSyncRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("sync_graph")),
):
    data = await sync_graph_from_postgres(clear_existing=payload.clear_existing)
    return GraphSyncResponse(**data)
