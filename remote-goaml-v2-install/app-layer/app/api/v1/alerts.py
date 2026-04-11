"""
goAML-V2 alert API endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from models.analyst_ops import (
    BulkAlertActionRequest,
    BulkActionPreviewResponse,
    BulkAlertActionResponse,
    DecisionFeedbackCreateRequest,
    DecisionFeedbackItem,
    DecisionFeedbackResponse,
)
from models.casework import (
    AlertActionRequest,
    AlertActionResponse,
    AlertDetail,
    AlertInvestigateRequest,
    AlertListItem,
    AlertStatusUpdate,
)
from services.alerts import (
    get_alert,
    investigate_alert,
    list_alerts,
    run_alert_action,
    run_bulk_alert_actions,
    update_alert_status,
)
from services.decision_quality import list_decision_feedback, record_decision_feedback
from services.maturity_features import get_alert_bulk_preview
from services.auth import AuthenticatedUser, ensure_assignment_allowed, require_permissions, resolve_request_actor

router = APIRouter()


@router.get("/alerts", response_model=list[AlertListItem], summary="List alerts")
async def get_alerts(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    severity: str | None = Query(None),
    assigned_to: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_permissions("view_alerts")),
):
    rows = await list_alerts(limit=limit, offset=offset, status=status, severity=severity, assigned_to=assigned_to)
    return [AlertListItem(**row) for row in rows]


@router.patch("/alerts/{alert_id}", response_model=AlertListItem, summary="Update alert status")
async def patch_alert(
    alert_id: UUID,
    payload: AlertStatusUpdate,
    current_user: AuthenticatedUser = Depends(require_permissions("triage_alerts")),
):
    reviewed_by = payload.reviewed_by or (current_user.username if payload.status.value != "open" else None)
    row = await update_alert_status(alert_id, payload.model_copy(update={"reviewed_by": reviewed_by}))
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertListItem(**row)


@router.get("/alerts/{alert_id}", response_model=AlertDetail, summary="Get alert detail")
async def get_alert_detail(
    alert_id: UUID,
    current_user: AuthenticatedUser = Depends(require_permissions("view_alerts")),
):
    row = await get_alert(alert_id)
    if not row:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertDetail(**row)


@router.get("/alerts/{alert_id}/feedback", response_model=list[DecisionFeedbackItem], summary="List closed-loop feedback for an alert")
async def get_alert_feedback(
    alert_id: UUID,
    current_user: AuthenticatedUser = Depends(require_permissions("view_alerts")),
):
    rows = await list_decision_feedback("alert", alert_id, limit=20)
    return [DecisionFeedbackItem(**row) for row in rows]


@router.post("/alerts/{alert_id}/feedback", response_model=DecisionFeedbackResponse, summary="Record closed-loop feedback for an alert")
async def post_alert_feedback(
    alert_id: UUID,
    payload: DecisionFeedbackCreateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("triage_alerts")),
):
    try:
        row = await record_decision_feedback(
            subject_type="alert",
            subject_id=alert_id,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            actor_role=current_user.role_key,
            feedback_key=payload.feedback_key,
            note=payload.note,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DecisionFeedbackResponse(item=DecisionFeedbackItem(**row), summary=[f"Recorded {row['label'].lower()} feedback for the selected alert."])


@router.post("/alerts/{alert_id}/investigate", summary="Assign alert for investigation and optionally open a case")
async def post_alert_investigation(
    alert_id: UUID,
    payload: AlertInvestigateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("triage_alerts")),
):
    result = await investigate_alert(
        alert_id,
        payload.model_copy(
            update={
                "assigned_to": ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user) or current_user.username,
                "reviewed_by": resolve_request_actor(requested_actor=payload.reviewed_by, current_user=current_user),
                "created_by": resolve_request_actor(requested_actor=payload.created_by, current_user=current_user),
            }
        ),
    )
    if not result:
        raise HTTPException(status_code=404, detail="Alert not found")
    return result


@router.post("/alerts/{alert_id}/actions", response_model=AlertActionResponse, summary="Apply an analyst action to an alert")
async def post_alert_action(
    alert_id: UUID,
    payload: AlertActionRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("triage_alerts")),
):
    try:
        result = await run_alert_action(
            alert_id,
            payload.model_copy(
                update={
                    "actor": resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
                    "assigned_to": ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user),
                }
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result:
        raise HTTPException(status_code=404, detail="Alert not found")
    return AlertActionResponse(**result)


@router.post("/alerts/bulk-actions", response_model=BulkAlertActionResponse, summary="Apply a bulk analyst action to multiple alerts")
async def post_bulk_alert_action(
    payload: BulkAlertActionRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("triage_alerts")),
):
    try:
        result = await run_bulk_alert_actions(
            payload.model_copy(
                update={
                    "actor": resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
                    "assigned_to": ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user),
                }
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BulkAlertActionResponse(**result)


@router.post("/alerts/bulk-preview", response_model=BulkActionPreviewResponse, summary="Preview a bulk alert action before applying it")
async def post_bulk_alert_preview(
    payload: BulkAlertActionRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("triage_alerts")),
):
    return BulkActionPreviewResponse(**(await get_alert_bulk_preview(payload.alert_ids, payload.action)))
