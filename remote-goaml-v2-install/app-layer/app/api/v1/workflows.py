"""
Workflow, orchestration, and automation dashboard endpoints.
"""

from fastapi import APIRouter, Depends, Query

from models.analyst_ops import (
    DecisionQualityAutomationResponse,
    DecisionQualityRecommendationAutomationResponse,
    NotificationInboxBulkActionRequest,
    NotificationInboxBulkActionResponse,
    NotificationInboxResponse,
    NotificationInboxStateRequest,
    NotificationInboxStateResponse,
    ReportingAlertRunResponse,
    WorkflowExceptionsResponse,
)
from models.casework import SarQueueTrendResponse, SlaSnapshotCaptureRequest, SlaSnapshotCaptureResponse
from models.workflows import (
    DecisionQualityAutomationRequest,
    DecisionQualityRecommendationAutomationRequest,
    ModelMonitoringNotificationRequest,
    PlaybookAutomationRequest,
    ReportingAlertRequest,
    SlaNotificationRequest,
    WorkflowExceptionActionRequest,
)
from services.notification_center import (
    bulk_update_notification_center,
    get_notification_center,
    update_notification_center_state,
)
from services.management_reporting import get_reporting_control_overview, run_reporting_alerts
from services.maturity_features import get_workflow_exceptions, run_workflow_exception_action
from services.sla_analytics import capture_sar_queue_snapshot, get_sar_queue_trends
from services.workflow_engine import (
    dispatch_model_monitoring_notifications,
    get_camunda_dashboard,
    get_n8n_dashboard,
    get_workflow_overview,
    dispatch_sla_notifications,
    run_decision_quality_automation,
    run_decision_quality_recommendation_automation,
    run_playbook_automation,
)
from services.auth import (
    AuthenticatedUser,
    get_current_user,
    require_any_permissions,
    require_permissions,
    resolve_request_actor,
)

router = APIRouter()


@router.get("/workflow/overview", summary="Get workflow operations overview")
async def get_workflow_dashboard(
    current_user: AuthenticatedUser = Depends(require_permissions("view_workflow_ops")),
):
    return await get_workflow_overview()


@router.get("/workflow/exceptions", response_model=WorkflowExceptionsResponse, summary="Get workflow exceptions, guided states, and intervention-ready items")
async def get_workflow_exception_dashboard(
    limit: int = Query(20, ge=5, le=100),
    current_user: AuthenticatedUser = Depends(require_permissions("view_workflow_ops")),
):
    return WorkflowExceptionsResponse(**(await get_workflow_exceptions(limit=limit)))


@router.post("/workflow/exceptions/action", summary="Record a workflow exception handling action")
async def post_workflow_exception_action(
    payload: WorkflowExceptionActionRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_workflows")),
):
    return await run_workflow_exception_action(
        actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
        case_id=payload.case_id,
        action=payload.action,
        note=payload.note,
    )


@router.get("/workflow/inbox", response_model=NotificationInboxResponse, summary="Get analyst inbox items across notifications and tasks")
async def get_workflow_inbox(
    actor: str = Query("analyst1", min_length=2),
    state: str = Query("active", pattern="^(active|all|completed)$"),
    limit: int = Query(60, ge=10, le=200),
    team_key: str | None = Query(None),
    item_type: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_permissions("view_inbox")),
):
    actor_name = resolve_request_actor(
        requested_actor=actor,
        current_user=current_user,
        allow_delegate=current_user.has_permission("manage_queues") or current_user.has_permission("manage_workflows"),
    )
    item_types = [value.strip() for value in str(item_type or "").split(",") if value.strip()]
    return NotificationInboxResponse(
        **(
            await get_notification_center(
                actor=actor_name,
                state=state,
                limit=limit,
                team_key=team_key,
                item_types=item_types,
            )
        )
    )


@router.post("/workflow/inbox/state", response_model=NotificationInboxStateResponse, summary="Update inbox state for a notification or task")
async def post_workflow_inbox_state(
    payload: NotificationInboxStateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("view_inbox")),
):
    return NotificationInboxStateResponse(
        **(
            await update_notification_center_state(
                actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
                item_type=payload.item_type,
                item_id=payload.item_id,
                state=payload.state,
                metadata=payload.metadata,
            )
        )
    )


@router.post("/workflow/inbox/bulk-actions", response_model=NotificationInboxBulkActionResponse, summary="Apply a bulk action across inbox items")
async def post_workflow_inbox_bulk_actions(
    payload: NotificationInboxBulkActionRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("view_inbox")),
):
    return NotificationInboxBulkActionResponse(
        **(
            await bulk_update_notification_center(
                actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
                action=payload.action,
                items=[item.model_dump() for item in payload.items],
                note=payload.note,
            )
        )
    )


@router.get("/workflow/sla/trends", response_model=SarQueueTrendResponse, summary="Get historical SAR SLA trend data")
async def get_workflow_sla_trends(
    hours: int = Query(168, ge=12, le=24 * 90),
    limit: int = Query(24, ge=6, le=120),
    auto_capture: bool = Query(True),
    bootstrap_if_empty: bool = Query(True),
    current_user: AuthenticatedUser = Depends(require_permissions("view_workflow_ops")),
):
    return await get_sar_queue_trends(
        hours=hours,
        limit=limit,
        auto_capture=auto_capture,
        bootstrap_if_empty=bootstrap_if_empty,
    )


@router.post("/workflow/sla/snapshots/capture", response_model=SlaSnapshotCaptureResponse, summary="Capture a SAR SLA history snapshot")
async def post_workflow_sla_snapshot_capture(
    payload: SlaSnapshotCaptureRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_workflows")),
):
    payload = payload or SlaSnapshotCaptureRequest()
    return await capture_sar_queue_snapshot(
        triggered_by=resolve_request_actor(requested_actor=payload.triggered_by, current_user=current_user),
        source=payload.source,
        force=payload.force,
        bootstrap_if_empty=payload.bootstrap_if_empty,
        backfill_hours=payload.backfill_hours,
        interval_minutes=payload.interval_minutes,
    )


@router.get("/workflow/n8n", summary="Get n8n automation dashboard data")
async def get_n8n_workflow_dashboard(
    current_user: AuthenticatedUser = Depends(require_permissions("view_workflow_ops")),
):
    return await get_n8n_dashboard()


@router.get("/workflow/camunda", summary="Get Camunda orchestration dashboard data")
async def get_camunda_workflow_dashboard(
    current_user: AuthenticatedUser = Depends(require_permissions("view_workflow_ops")),
):
    return await get_camunda_dashboard()


@router.post("/workflow/sla/notify", summary="Dispatch SAR SLA breach notifications")
async def post_sla_notifications(
    payload: SlaNotificationRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_workflows")),
):
    return await dispatch_sla_notifications(
        triggered_by=resolve_request_actor(requested_actor=payload.triggered_by, current_user=current_user),
        channels=payload.channels,
        breached_only=payload.breached_only,
        include_due_soon=payload.include_due_soon,
    )


@router.post("/workflow/model-monitoring/notify", summary="Dispatch scorer drift and champion/challenger notifications")
async def post_model_monitoring_notifications(
    payload: ModelMonitoringNotificationRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_any_permissions("manage_workflows", "manage_models")),
):
    payload = payload or ModelMonitoringNotificationRequest()
    return await dispatch_model_monitoring_notifications(
        triggered_by=resolve_request_actor(requested_actor=payload.triggered_by, current_user=current_user),
        channels=payload.channels,
        include_stable=payload.include_stable,
        force=payload.force,
    )


@router.post("/workflow/playbooks/automate", summary="Run stuck-checklist and evidence-gap playbook automation")
async def post_playbook_automation(
    payload: PlaybookAutomationRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_workflows")),
):
    payload = payload or PlaybookAutomationRequest()
    return await run_playbook_automation(
        triggered_by=resolve_request_actor(requested_actor=payload.triggered_by, current_user=current_user),
        stuck_hours=payload.stuck_hours,
        evidence_gap_warning_hours=payload.evidence_gap_warning_hours,
        cooldown_hours=payload.cooldown_hours,
        limit=payload.limit,
        force=payload.force,
    )


@router.post(
    "/workflow/decision-quality/automate",
    response_model=DecisionQualityAutomationResponse,
    summary="Run feedback-to-action quality automation for noisy alerts, weak SAR drafts, and missing evidence",
)
async def post_decision_quality_automation(
    payload: DecisionQualityAutomationRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_any_permissions("manage_workflows", "view_reports")),
):
    payload = payload or DecisionQualityAutomationRequest()
    row = await run_decision_quality_automation(
        triggered_by=resolve_request_actor(requested_actor=payload.triggered_by, current_user=current_user),
        lookback_hours=payload.lookback_hours,
        noisy_threshold=payload.noisy_threshold,
        weak_sar_threshold=payload.weak_sar_threshold,
        missing_evidence_threshold=payload.missing_evidence_threshold,
        cooldown_hours=payload.cooldown_hours,
        limit=payload.limit,
        force=payload.force,
    )
    return DecisionQualityAutomationResponse(**row)


@router.post(
    "/workflow/decision-quality/recommendations/run",
    response_model=DecisionQualityRecommendationAutomationResponse,
    summary="Capture quality history and raise recurring decision-quality recommendations",
)
async def post_decision_quality_recommendation_automation(
    payload: DecisionQualityRecommendationAutomationRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_any_permissions("manage_workflows", "view_reports")),
):
    payload = payload or DecisionQualityRecommendationAutomationRequest()
    row = await run_decision_quality_recommendation_automation(
        triggered_by=resolve_request_actor(requested_actor=payload.triggered_by, current_user=current_user),
        range_days=payload.range_days,
        recurring_periods=payload.recurring_periods,
        noisy_threshold=payload.noisy_threshold,
        drafter_rejection_threshold=payload.drafter_rejection_threshold,
        cooldown_hours=payload.cooldown_hours,
        force=payload.force,
    )
    return DecisionQualityRecommendationAutomationResponse(**row)


@router.get("/workflow/reports/overview", summary="Get reporting automation and recommendation overview")
async def get_workflow_reporting_overview(
    snapshot_scope: str = Query("manager", pattern="^(manager|executive|compliance|board)$"),
    range_days: int = Query(180, ge=30, le=365),
    current_user: AuthenticatedUser = Depends(require_permissions("view_workflow_ops")),
):
    return await get_reporting_control_overview(range_days=range_days, snapshot_scope=snapshot_scope)


@router.post("/workflow/reports/alerts/run", response_model=ReportingAlertRunResponse, summary="Run threshold-based reporting alerts")
async def post_workflow_reporting_alerts_run(
    payload: ReportingAlertRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_any_permissions("manage_workflows", "view_reports")),
):
    payload = payload or ReportingAlertRequest()
    row = await run_reporting_alerts(
        actor=resolve_request_actor(requested_actor=payload.triggered_by, current_user=current_user),
        channels=payload.channels,
        snapshot_scope=payload.snapshot_scope,
        range_days=payload.range_days,
        force=payload.force,
    )
    return ReportingAlertRunResponse(**row)
