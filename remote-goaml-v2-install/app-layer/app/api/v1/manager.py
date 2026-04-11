"""
Manager console endpoints for queue control, workload visibility, reassignment, and reporting.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from io import BytesIO

from models.analyst_ops import (
    ManagementReportingOverviewResponse,
    ManagerAdvancedConsoleResponse,
    ManagerConsoleResponse,
    ManagerMassReassignRequest,
    ManagerMassReassignResponse,
    ReportingAlertRunResponse,
    ReportingAutomationSettings,
    ReportingAutomationSettingsUpdateRequest,
    ReportDistributionRuleItem,
    ReportDistributionRuleUpdateRequest,
    ReportDistributionRunResponse,
    ReportingDrilldownResponse,
    ReportingSnapshotCaptureResponse,
    ReportingSnapshotsResponse,
)
from models.casework import (
    PlaybookAnalyticsResponse,
    PlaybookAutomationSettings,
    PlaybookAutomationSettingsUpdateRequest,
    PlaybookBackfillResponse,
    PlaybookConfigItem,
    PlaybookConfigUpdateRequest,
)
from services.auth import AuthenticatedUser, ensure_assignment_allowed, require_permissions, resolve_request_actor
from services.playbook_analytics import get_playbook_analytics
from services.case_playbooks import backfill_case_playbooks, list_playbook_configs, update_playbook_config
from services.manager_console import get_manager_console, run_manager_mass_reassign
from services.management_reporting import (
    build_management_report_export,
    capture_reporting_snapshot,
    get_reporting_automation_settings,
    get_management_reporting_overview,
    get_reporting_drilldown,
    get_reporting_snapshots,
    list_report_distribution_rules,
    run_reporting_alerts,
    run_report_distribution,
    update_reporting_automation_settings,
    update_report_distribution_rule,
)
from services.maturity_features import get_manager_console_advanced
from services.workflow_engine import get_playbook_automation_settings, update_playbook_automation_settings

router = APIRouter()


@router.get("/manager/console", response_model=ManagerConsoleResponse, summary="Get manager queue console data")
async def get_manager_console_dashboard(
    team_key: str | None = Query(None),
    region_key: str | None = Query(None),
    typology: str | None = Query(None),
    sla_status: str | None = Query(None),
    owner: str | None = Query(None),
    limit: int = Query(30, ge=10, le=200),
    current_user: AuthenticatedUser = Depends(require_permissions("manage_queues")),
):
    row = await get_manager_console(
        team_key=team_key,
        region_key=region_key,
        typology=typology,
        sla_status=sla_status,
        owner=owner,
        limit=limit,
    )
    return ManagerConsoleResponse(**row)


@router.get("/manager/console/advanced", response_model=ManagerAdvancedConsoleResponse, summary="Get deeper manager control data, workspace presets, and intervention suggestions")
async def get_manager_console_advanced_dashboard(
    current_user: AuthenticatedUser = Depends(require_permissions("manage_queues")),
):
    return ManagerAdvancedConsoleResponse(**(await get_manager_console_advanced()))


@router.post(
    "/manager/console/reassign",
    response_model=ManagerMassReassignResponse,
    summary="Mass reassign alerts and SAR work from the manager console",
)
async def post_manager_console_reassign(
    payload: ManagerMassReassignRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_queues")),
):
    try:
        row = await run_manager_mass_reassign(
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            assigned_to=ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user),
            alert_ids=payload.alert_ids,
            case_ids=payload.case_ids,
            note=payload.note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ManagerMassReassignResponse(**row)


@router.get("/manager/playbooks", response_model=list[PlaybookConfigItem], summary="List typology playbook configurations")
async def get_manager_playbooks(current_user: AuthenticatedUser = Depends(require_permissions("manage_playbooks"))):
    rows = await list_playbook_configs()
    return [PlaybookConfigItem(**row) for row in rows]


@router.get(
    "/manager/playbooks/analytics",
    response_model=PlaybookAnalyticsResponse,
    summary="Get playbook compliance and typology outcome analytics",
)
async def get_manager_playbook_analytics(
    range_days: int = Query(180, ge=30, le=365),
    top_steps: int = Query(12, ge=5, le=30),
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    row = await get_playbook_analytics(range_days=range_days, top_steps=top_steps)
    return PlaybookAnalyticsResponse(**row)


@router.get(
    "/manager/reports/overview",
    response_model=ManagementReportingOverviewResponse,
    summary="Get management reporting overview with executive, playbook, and outcome analytics",
)
async def get_manager_reports_overview(
    range_days: int = Query(180, ge=30, le=365),
    snapshot_scope: str = Query("manager", pattern="^(manager|executive|compliance|board)$"),
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    return ManagementReportingOverviewResponse(**(await get_management_reporting_overview(range_days=range_days, snapshot_scope=snapshot_scope)))


@router.post(
    "/manager/reports/snapshots/capture",
    response_model=ReportingSnapshotCaptureResponse,
    summary="Capture a persisted reporting snapshot",
)
async def post_manager_reports_capture(
    range_days: int = Query(180, ge=30, le=365),
    snapshot_scope: str = Query("manager", pattern="^(manager|executive|compliance|board)$"),
    snapshot_granularity: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    actor: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    row = await capture_reporting_snapshot(
        actor=resolve_request_actor(requested_actor=actor, current_user=current_user),
        snapshot_scope=snapshot_scope,
        snapshot_granularity=snapshot_granularity,
        range_days=range_days,
        source="manual",
    )
    return ReportingSnapshotCaptureResponse(**row)


@router.get(
    "/manager/reports/snapshots",
    response_model=ReportingSnapshotsResponse,
    summary="List persisted reporting snapshots",
)
async def get_manager_reports_snapshots(
    range_days: int = Query(180, ge=30, le=365),
    snapshot_scope: str = Query("manager", pattern="^(manager|executive|compliance|board)$"),
    snapshot_granularity: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    limit: int = Query(90, ge=1, le=365),
    auto_capture: bool = Query(True),
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    row = await get_reporting_snapshots(
        snapshot_scope=snapshot_scope,
        snapshot_granularity=snapshot_granularity,
        range_days=range_days,
        limit=limit,
        auto_capture=auto_capture,
    )
    return ReportingSnapshotsResponse(**row)


@router.get(
    "/manager/reports/drilldown",
    response_model=ReportingDrilldownResponse,
    summary="Get drilldown case set for management reporting metrics",
)
async def get_manager_reports_drilldown(
    metric_key: str = Query(..., min_length=2, max_length=64),
    range_days: int = Query(180, ge=30, le=365),
    snapshot_id: str | None = Query(None),
    typology: str | None = Query(None),
    team_key: str | None = Query(None),
    region_key: str | None = Query(None),
    owner: str | None = Query(None),
    priority: str | None = Query(None),
    feedback_key: str | None = Query(None),
    limit: int = Query(40, ge=1, le=100),
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    row = await get_reporting_drilldown(
        metric_key=metric_key,
        range_days=range_days,
        snapshot_id=snapshot_id,
        typology=typology,
        team_key=team_key,
        region_key=region_key,
        owner=owner,
        priority=priority,
        feedback_key=feedback_key,
        limit=limit,
    )
    return ReportingDrilldownResponse(**row)


@router.get(
    "/manager/reports/export",
    summary="Export management reporting pack as JSON, CSV, PDF, or DOCX",
)
async def get_manager_reports_export(
    range_days: int = Query(180, ge=30, le=365),
    snapshot_id: str | None = Query(None),
    format: str = Query("json", pattern="^(json|csv|pdf|docx)$"),
    template: str = Query("manager", pattern="^(manager|executive|compliance|board)$"),
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    try:
        filename, payload, media_type = await build_management_report_export(range_days=range_days, snapshot_id=snapshot_id, export_format=format, template_key=template)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StreamingResponse(
        BytesIO(payload),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/manager/reports/distribution-rules",
    response_model=list[ReportDistributionRuleItem],
    summary="List scheduled report distribution rules",
)
async def get_manager_report_distribution_rules(
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    rows = await list_report_distribution_rules()
    return [ReportDistributionRuleItem(**row) for row in rows]


@router.put(
    "/manager/reports/distribution-rules/{rule_key}",
    response_model=ReportDistributionRuleItem,
    summary="Update a scheduled report distribution rule",
)
async def put_manager_report_distribution_rule(
    rule_key: str,
    payload: ReportDistributionRuleUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    try:
        row = await update_report_distribution_rule(
            rule_key=rule_key,
            actor=resolve_request_actor(requested_actor=payload.updated_by, current_user=current_user),
            updates=payload.model_dump(exclude_none=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ReportDistributionRuleItem(**row)


@router.post(
    "/manager/reports/distribute/run",
    response_model=ReportDistributionRunResponse,
    summary="Run scheduled report distribution using saved rules",
)
async def post_manager_report_distribution_run(
    cadence: str = Query("daily", pattern="^(daily|weekly|monthly|quarterly)$"),
    range_days: int = Query(180, ge=30, le=365),
    actor: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    row = await run_report_distribution(
        actor=resolve_request_actor(requested_actor=actor, current_user=current_user),
        cadence=cadence,
        range_days=range_days,
    )
    return ReportDistributionRunResponse(**row)


@router.get(
    "/manager/reports/automation-settings",
    response_model=ReportingAutomationSettings,
    summary="Get reporting threshold automation settings",
)
async def get_manager_reporting_automation_settings(
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    return ReportingAutomationSettings(**(await get_reporting_automation_settings()))


@router.put(
    "/manager/reports/automation-settings",
    response_model=ReportingAutomationSettings,
    summary="Update reporting threshold automation settings",
)
async def put_manager_reporting_automation_settings(
    payload: ReportingAutomationSettingsUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    row = await update_reporting_automation_settings(
        actor=resolve_request_actor(requested_actor=payload.updated_by, current_user=current_user),
        updates=payload.model_dump(exclude_none=True),
    )
    return ReportingAutomationSettings(**row)


@router.post(
    "/manager/reports/alerts/run",
    response_model=ReportingAlertRunResponse,
    summary="Run threshold-based reporting alerts and recommendations",
)
async def post_manager_reporting_alerts_run(
    snapshot_scope: str = Query("manager", pattern="^(manager|executive|compliance|board)$"),
    range_days: int = Query(180, ge=30, le=365),
    actor: str | None = Query(None),
    force: bool = Query(False),
    current_user: AuthenticatedUser = Depends(require_permissions("view_reports")),
):
    row = await run_reporting_alerts(
        actor=resolve_request_actor(requested_actor=actor, current_user=current_user),
        channels=["app"],
        snapshot_scope=snapshot_scope,
        range_days=range_days,
        force=force,
    )
    return ReportingAlertRunResponse(**row)


@router.get(
    "/manager/playbooks/automation-settings",
    response_model=PlaybookAutomationSettings,
    summary="Get playbook automation intervention settings",
)
async def get_manager_playbook_automation_settings(
    current_user: AuthenticatedUser = Depends(require_permissions("manage_playbooks")),
):
    row = await get_playbook_automation_settings()
    return PlaybookAutomationSettings(**row)


@router.put(
    "/manager/playbooks/automation-settings",
    response_model=PlaybookAutomationSettings,
    summary="Update playbook automation intervention settings",
)
async def put_manager_playbook_automation_settings(
    payload: PlaybookAutomationSettingsUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_playbooks")),
):
    row = await update_playbook_automation_settings(
        actor=resolve_request_actor(requested_actor=payload.updated_by, current_user=current_user),
        updates=payload.model_dump(exclude_none=True),
    )
    return PlaybookAutomationSettings(**row)


@router.put("/manager/playbooks/{typology}", response_model=PlaybookConfigItem, summary="Update a typology playbook configuration")
async def put_manager_playbook(
    typology: str,
    payload: PlaybookConfigUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_playbooks")),
):
    try:
        row = await update_playbook_config(
            typology,
            payload.model_dump(exclude_none=True)
            | {"updated_by": resolve_request_actor(requested_actor=payload.updated_by, current_user=current_user)},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return PlaybookConfigItem(**row)


@router.post("/manager/playbooks/backfill", response_model=PlaybookBackfillResponse, summary="Apply typology playbooks to existing cases")
async def post_manager_playbook_backfill(
    actor: str | None = Query(None),
    typology: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    current_user: AuthenticatedUser = Depends(require_permissions("manage_playbooks")),
):
    row = await backfill_case_playbooks(
        actor=resolve_request_actor(requested_actor=actor, current_user=current_user),
        typology=typology,
        limit=limit,
    )
    return PlaybookBackfillResponse(**row)
