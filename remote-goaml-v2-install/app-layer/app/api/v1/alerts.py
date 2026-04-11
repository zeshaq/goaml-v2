"""
goAML-V2 alert API endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from models.casework import (
    AlertActionRequest,
    AlertActionResponse,
    AlertDetail,
    AlertInvestigateRequest,
    AlertListItem,
    AlertStatusUpdate,
)
from services.alerts import get_alert, investigate_alert, list_alerts, run_alert_action, update_alert_status

router = APIRouter()


@router.get("/alerts", response_model=list[AlertListItem], summary="List alerts")
async def get_alerts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    severity: str | None = Query(None),
):
    rows = await list_alerts(limit=limit, offset=offset, status=status, severity=severity)
    return [AlertListItem(**row) for row in rows]


@router.patch("/alerts/{alert_id}", response_model=AlertListItem, summary="Update alert status")
async def patch_alert(alert_id: UUID, payload: AlertStatusUpdate):
    row = await update_alert_status(alert_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertListItem(**row)


@router.get("/alerts/{alert_id}", response_model=AlertDetail, summary="Get alert detail")
async def get_alert_detail(alert_id: UUID):
    row = await get_alert(alert_id)
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertDetail(**row)


@router.post("/alerts/{alert_id}/investigate", summary="Assign alert for investigation and optionally open a case")
async def post_alert_investigation(alert_id: UUID, payload: AlertInvestigateRequest):
    result = await investigate_alert(alert_id, payload)
    if not result:
        raise HTTPException(status_code=404, detail="Alert not found")
    return result


@router.post("/alerts/{alert_id}/actions", response_model=AlertActionResponse, summary="Apply an analyst action to an alert")
async def post_alert_action(alert_id: UUID, payload: AlertActionRequest):
    try:
        result = await run_alert_action(alert_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertActionResponse(**result)
