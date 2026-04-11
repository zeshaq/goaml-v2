"""
Analyst productivity, inbox, and model outcome request/response models.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class SavedViewItem(BaseModel):
    id: UUID
    scope: str
    owner: str | None = None
    name: str
    is_shared: bool = False
    is_default: bool = False
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class SavedViewCreateRequest(BaseModel):
    scope: str = Field(..., min_length=2, max_length=64)
    owner: str | None = Field(None, max_length=255)
    name: str = Field(..., min_length=2, max_length=255)
    is_shared: bool = False
    is_default: bool = False
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SavedViewDeleteResponse(BaseModel):
    status: str
    id: UUID


class DeskPresetItem(BaseModel):
    id: str
    scope: str
    name: str
    description: str | None = None
    kind: str = "system_preset"
    is_default: bool = False
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnalystProfile(BaseModel):
    actor: str
    role_key: str
    team_key: str
    team_label: str
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    workflows: list[str] = Field(default_factory=list)
    team_members: list[str] = Field(default_factory=list)


class AnalystContextResponse(BaseModel):
    generated_at: datetime
    profile: AnalystProfile
    desk_defaults: dict[str, str] = Field(default_factory=dict)
    desk_presets: dict[str, list[DeskPresetItem]] = Field(default_factory=dict)
    summary: list[str] = Field(default_factory=list)


class BulkAlertActionRequest(BaseModel):
    alert_ids: list[UUID] = Field(default_factory=list, min_length=1, max_length=200)
    action: str = Field(..., min_length=2, max_length=64)
    actor: str | None = Field(None, max_length=255)
    assigned_to: str | None = Field(None, max_length=255)
    note: str | None = Field(None, max_length=4000)
    create_case: bool = False
    priority: str | None = Field(None, max_length=32)
    case_title: str | None = Field(None, max_length=512)
    case_description: str | None = Field(None, max_length=4000)


class BulkAlertActionResult(BaseModel):
    alert_id: UUID
    action: str
    status: str
    alert_ref: str | None = None
    case_id: UUID | None = None
    case_ref: str | None = None
    message: str | None = None


class BulkAlertActionResponse(BaseModel):
    action: str
    processed_count: int
    success_count: int
    failure_count: int
    results: list[BulkAlertActionResult] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    generated_at: datetime


class BulkSarActionRequest(BaseModel):
    case_ids: list[UUID] = Field(default_factory=list, min_length=1, max_length=200)
    action: str = Field(..., min_length=2, max_length=64)
    actor: str | None = Field(None, max_length=255)
    assigned_to: str | None = Field(None, max_length=255)
    note: str | None = Field(None, max_length=4000)
    filing_ref_prefix: str | None = Field(None, max_length=64)


class BulkSarActionResult(BaseModel):
    case_id: UUID
    action: str
    status: str
    case_ref: str | None = None
    sar_id: UUID | None = None
    sar_ref: str | None = None
    message: str | None = None


class BulkSarActionResponse(BaseModel):
    action: str
    processed_count: int
    success_count: int
    failure_count: int
    results: list[BulkSarActionResult] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    generated_at: datetime


class BulkActionPreviewItem(BaseModel):
    id: str
    ref: str
    title: str
    status: str | None = None
    severity: str | None = None
    owner: str | None = None
    team_key: str | None = None
    region_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class QueueNavigationState(BaseModel):
    selected_id: str | None = None
    previous_id: str | None = None
    next_id: str | None = None
    visible_ids: list[str] = Field(default_factory=list)


class BulkActionTemplateItem(BaseModel):
    key: str
    label: str
    action: str
    note_template: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BulkActionPreviewResponse(BaseModel):
    scope: str
    action: str
    selected_count: int
    preview_items: list[BulkActionPreviewItem] = Field(default_factory=list)
    queue_navigation: QueueNavigationState | None = None
    templates: list[BulkActionTemplateItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    generated_at: datetime


class NotificationInboxItem(BaseModel):
    item_type: str
    item_id: str
    state: str
    priority: str = "info"
    title: str
    body: str | None = None
    actor: str | None = None
    owner: str | None = None
    team_key: str | None = None
    region_key: str | None = None
    case_id: UUID | None = None
    case_ref: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    deep_link: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class NotificationInboxResponse(BaseModel):
    actor: str
    generated_at: datetime
    counts: dict[str, int] = Field(default_factory=dict)
    items: list[NotificationInboxItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class NotificationInboxStateRequest(BaseModel):
    actor: str = Field(..., min_length=2, max_length=255)
    item_type: str = Field(..., min_length=2, max_length=32)
    item_id: str = Field(..., min_length=1, max_length=255)
    state: str = Field(..., min_length=2, max_length=32)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NotificationInboxStateResponse(BaseModel):
    status: str
    actor: str
    item_type: str
    item_id: str
    state: str
    updated_at: datetime


class NotificationInboxBulkActionItem(BaseModel):
    item_type: str = Field(..., min_length=2, max_length=32)
    item_id: str = Field(..., min_length=1, max_length=255)
    case_id: UUID | None = None


class NotificationInboxBulkActionRequest(BaseModel):
    actor: str = Field(..., min_length=2, max_length=255)
    action: str = Field(..., min_length=2, max_length=32)
    items: list[NotificationInboxBulkActionItem] = Field(default_factory=list, min_length=1, max_length=200)
    note: str | None = Field(None, max_length=4000)


class NotificationInboxBulkActionResult(BaseModel):
    item_type: str
    item_id: str
    case_id: UUID | None = None
    action: str
    status: str
    message: str | None = None


class NotificationInboxBulkActionResponse(BaseModel):
    action: str
    processed_count: int
    success_count: int
    failure_count: int
    results: list[NotificationInboxBulkActionResult] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    generated_at: datetime


class ManagerQueueAlertItem(BaseModel):
    id: UUID
    alert_ref: str
    alert_type: str
    status: str
    severity: str
    title: str
    assigned_to: str | None = None
    case_id: UUID | None = None
    case_ref: str | None = None
    team_key: str | None = None
    team_label: str | None = None
    region_key: str | None = None
    region_label: str | None = None
    created_at: datetime


class ManagerQueueSarItem(BaseModel):
    case_id: UUID
    case_ref: str
    case_title: str
    case_priority: str
    case_status: str
    sar_id: UUID | None = None
    sar_ref: str | None = None
    sar_status: str | None = None
    queue: str
    queue_owner: str | None = None
    team_key: str | None = None
    team_label: str | None = None
    region_key: str | None = None
    region_label: str | None = None
    sla_status: str | None = None
    age_hours: float | None = None
    subject_name: str | None = None


class ManagerHeatmapCell(BaseModel):
    team_key: str
    team_label: str
    backlog_count: int = 0
    breached_count: int = 0
    critical_count: int = 0
    alert_count: int = 0
    sar_count: int = 0


class ManagerWorkloadItem(BaseModel):
    owner: str
    team_key: str | None = None
    team_label: str | None = None
    region_key: str | None = None
    region_label: str | None = None
    alert_count: int = 0
    high_alert_count: int = 0
    sar_active_count: int = 0
    sar_breached_count: int = 0
    combined_backlog: int = 0


class ManagerConsoleResponse(BaseModel):
    generated_at: datetime
    filters: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    summary: list[str] = Field(default_factory=list)
    alert_backlog: list[ManagerQueueAlertItem] = Field(default_factory=list)
    sar_backlog: list[ManagerQueueSarItem] = Field(default_factory=list)
    backlog_heatmap: list[ManagerHeatmapCell] = Field(default_factory=list)
    workload_board: list[ManagerWorkloadItem] = Field(default_factory=list)


class ManagerMassReassignRequest(BaseModel):
    actor: str = Field(..., min_length=2, max_length=255)
    assigned_to: str = Field(..., min_length=2, max_length=255)
    alert_ids: list[UUID] = Field(default_factory=list, max_length=200)
    case_ids: list[UUID] = Field(default_factory=list, max_length=200)
    note: str | None = Field(None, max_length=4000)


class ManagerMassReassignResponse(BaseModel):
    actor: str
    assigned_to: str
    alert_result: BulkAlertActionResponse | None = None
    sar_result: BulkSarActionResponse | None = None
    summary: list[str] = Field(default_factory=list)
    generated_at: datetime


class ManagerSavedWorkspaceItem(BaseModel):
    key: str
    label: str
    description: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ManagerBalancingRuleItem(BaseModel):
    key: str
    label: str
    value: str
    description: str | None = None
    editable: bool = False


class ManagerInterventionSuggestionItem(BaseModel):
    key: str
    title: str
    severity: str = "info"
    rationale: str
    suggested_action: str | None = None
    target_scope: str | None = None
    target_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ManagerQueueHotspotItem(BaseModel):
    scope_key: str
    scope_label: str
    backlog_count: int = 0
    breached_count: int = 0
    high_priority_count: int = 0
    avg_age_hours: float | None = None
    typology_mix: list[str] = Field(default_factory=list)


class ManagerAdvancedConsoleResponse(BaseModel):
    generated_at: datetime
    saved_workspaces: list[ManagerSavedWorkspaceItem] = Field(default_factory=list)
    balancing_rules: list[ManagerBalancingRuleItem] = Field(default_factory=list)
    intervention_suggestions: list[ManagerInterventionSuggestionItem] = Field(default_factory=list)
    team_hotspots: list[ManagerQueueHotspotItem] = Field(default_factory=list)
    region_hotspots: list[ManagerQueueHotspotItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ModelOutcomeVersionMetric(BaseModel):
    version: str
    stage: str | None = None
    score_count: int = 0
    avg_score: float | None = None
    high_risk_rate: float | None = None
    alert_rate: float | None = None
    case_conversion_rate: float | None = None
    false_positive_rate: float | None = None
    escalated_rate: float | None = None
    sar_conversion_rate: float | None = None
    filed_sar_rate: float | None = None
    avg_case_cycle_hours: float | None = None
    avg_case_event_count: float | None = None
    dominant_typology: str | None = None


class ModelOutcomeTrendPoint(BaseModel):
    bucket: str
    version: str
    score_count: int = 0
    avg_score: float | None = None
    alert_rate: float | None = None
    high_risk_rate: float | None = None
    case_conversion_rate: float | None = None
    sar_conversion_rate: float | None = None
    false_positive_rate: float | None = None
    filed_sar_rate: float | None = None


class WorkflowEffectivenessItem(BaseModel):
    workflow_key: str
    title: str
    status: str = "info"
    triggered_count: int = 0
    touched_case_count: int = 0
    positive_outcome_rate: float | None = None
    breached_rate: float | None = None
    avg_cycle_hours: float | None = None
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowEffectivenessTrendPoint(BaseModel):
    bucket: str
    workflow_key: str
    workflow_label: str
    triggered_count: int = 0
    touched_case_count: int = 0
    positive_outcome_rate: float | None = None
    breached_rate: float | None = None


class DecisionQualityBreakdownItem(BaseModel):
    scope_key: str
    scope_label: str
    metric: float = 0.0
    count: int = 0
    secondary_metric: float | None = None
    note: str | None = None


class DecisionQualityTrendPoint(BaseModel):
    bucket: str
    dimension_type: str
    dimension_key: str
    dimension_label: str
    true_positive_rate: float = 0.0
    false_positive_rate: float = 0.0
    filed_sar_rate: float | None = None
    count: int = 0


class DecisionFeedbackItem(BaseModel):
    id: UUID
    subject_type: str
    subject_id: UUID
    case_id: UUID | None = None
    alert_id: UUID | None = None
    actor: str | None = None
    actor_role: str | None = None
    feedback_key: str
    label: str
    sentiment: str = "neutral"
    rating: int = 0
    note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DecisionFeedbackCreateRequest(BaseModel):
    feedback_key: str = Field(..., min_length=2, max_length=64)
    note: str | None = Field(None, max_length=4000)
    actor: str | None = Field(None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionFeedbackResponse(BaseModel):
    status: str = "recorded"
    item: DecisionFeedbackItem
    summary: list[str] = Field(default_factory=list)


class ModelOutcomeAnalyticsResponse(BaseModel):
    generated_at: datetime
    range_days: int
    totals: dict[str, Any] = Field(default_factory=dict)
    versions: list[ModelOutcomeVersionMetric] = Field(default_factory=list)
    trends: list[ModelOutcomeTrendPoint] = Field(default_factory=list)
    impact_summary: list[dict[str, Any]] = Field(default_factory=list)
    typology_impact: list[dict[str, Any]] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ReportingKpiItem(BaseModel):
    key: str
    label: str
    value: float | int | str
    note: str | None = None
    status: str | None = None


class ReportingTrendPoint(BaseModel):
    bucket: str
    scope_key: str
    scope_label: str
    value: float = 0.0
    count: int = 0
    secondary_value: float | None = None


class ReportingHeatmapPoint(BaseModel):
    bucket: str
    typology: str
    display_name: str
    step_key: str
    step_label: str
    affected_case_count: int = 0
    affected_case_rate: float = 0.0


class ReportingEffectivenessItem(BaseModel):
    typology: str
    display_name: str
    priority: str
    case_count: int = 0
    avg_progress: float = 0.0
    blocked_case_rate: float = 0.0
    missing_evidence_case_rate: float = 0.0
    false_positive_rate: float = 0.0
    sar_conversion_rate: float = 0.0
    filed_sar_rate: float = 0.0


class ReportingBreakdownItem(BaseModel):
    scope_key: str
    scope_label: str
    metric: float = 0.0
    count: int = 0
    secondary_metric: float | None = None


class ReportingAlertItem(BaseModel):
    alert_key: str
    title: str
    severity: str = "info"
    status: str = "stable"
    metric_key: str
    metric_label: str
    current_value: float | int | str
    threshold_value: float | int | str | None = None
    delta_value: float | int | str | None = None
    delta_pct: float | None = None
    message: str | None = None
    recommendation_key: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportingRecommendationItem(BaseModel):
    recommendation_key: str
    title: str
    priority: str = "medium"
    action_type: str
    rationale: str
    target_scope: str | None = None
    target_key: str | None = None
    deep_link: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportingAutomationSettings(BaseModel):
    backlog_delta_warning_pct: float = 10.0
    backlog_delta_critical_pct: float = 20.0
    filing_timeliness_warning_drop_pct: float = 5.0
    filing_timeliness_critical_drop_pct: float = 10.0
    false_positive_warning_rate: float = 0.35
    false_positive_critical_rate: float = 0.5
    blocked_step_warning_rate: float = 0.3
    blocked_step_critical_rate: float = 0.45
    updated_by: str | None = None
    updated_at: datetime | None = None
    summary: list[str] = Field(default_factory=list)


class ReportingAutomationSettingsUpdateRequest(BaseModel):
    backlog_delta_warning_pct: float | None = Field(None, ge=0, le=500)
    backlog_delta_critical_pct: float | None = Field(None, ge=0, le=500)
    filing_timeliness_warning_drop_pct: float | None = Field(None, ge=0, le=100)
    filing_timeliness_critical_drop_pct: float | None = Field(None, ge=0, le=100)
    false_positive_warning_rate: float | None = Field(None, ge=0, le=1)
    false_positive_critical_rate: float | None = Field(None, ge=0, le=1)
    blocked_step_warning_rate: float | None = Field(None, ge=0, le=1)
    blocked_step_critical_rate: float | None = Field(None, ge=0, le=1)
    updated_by: str | None = Field(None, max_length=255)


class ReportingAlertRunResponse(BaseModel):
    triggered_at: datetime
    triggered_by: str
    processed_count: int = 0
    sent_count: int = 0
    skipped_count: int = 0
    alerts: list[ReportingAlertItem] = Field(default_factory=list)
    recommendations: list[ReportingRecommendationItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ManagementReportingOverviewResponse(BaseModel):
    generated_at: datetime
    range_days: int
    snapshot_scope: str = "manager"
    snapshot_granularity: str = "daily"
    high_level_kpis: list[ReportingKpiItem] = Field(default_factory=list)
    monthly_summary: list[str] = Field(default_factory=list)
    typology_mix: list[ReportingBreakdownItem] = Field(default_factory=list)
    watchlist_screening_posture: dict[str, Any] = Field(default_factory=dict)
    model_workflow_health: dict[str, Any] = Field(default_factory=dict)
    team_playbook_trends: list[ReportingTrendPoint] = Field(default_factory=list)
    region_playbook_trends: list[ReportingTrendPoint] = Field(default_factory=list)
    step_heatmap_trends: list[ReportingHeatmapPoint] = Field(default_factory=list)
    playbook_effectiveness: list[ReportingEffectivenessItem] = Field(default_factory=list)
    false_positive_by_team: list[ReportingBreakdownItem] = Field(default_factory=list)
    false_positive_by_typology: list[ReportingBreakdownItem] = Field(default_factory=list)
    false_positive_by_owner: list[ReportingBreakdownItem] = Field(default_factory=list)
    case_to_sar_by_typology: list[ReportingBreakdownItem] = Field(default_factory=list)
    filed_sar_volume_by_team: list[ReportingBreakdownItem] = Field(default_factory=list)
    filed_sar_volume_by_region: list[ReportingBreakdownItem] = Field(default_factory=list)
    backlog_aging_trends: list[ReportingTrendPoint] = Field(default_factory=list)
    compliance_posture: dict[str, Any] = Field(default_factory=dict)
    outcome_correlations: list[dict[str, Any]] = Field(default_factory=list)
    workflow_effectiveness: dict[str, Any] = Field(default_factory=dict)
    decision_quality: dict[str, Any] = Field(default_factory=dict)
    period_over_period: list[dict[str, Any]] = Field(default_factory=list)
    reporting_alerts: list[ReportingAlertItem] = Field(default_factory=list)
    action_recommendations: list[ReportingRecommendationItem] = Field(default_factory=list)
    board_reporting: dict[str, Any] = Field(default_factory=dict)
    summary: list[str] = Field(default_factory=list)


class ReportingSnapshotItem(BaseModel):
    id: UUID
    snapshot_scope: str
    snapshot_granularity: str = "daily"
    range_days: int
    period_start: datetime | None = None
    period_end: datetime | None = None
    period_label: str | None = None
    captured_at: datetime
    captured_by: str | None = None
    source: str = "manual"
    summary_metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReportingSnapshotsResponse(BaseModel):
    generated_at: datetime
    snapshot_scope: str
    snapshot_granularity: str = "daily"
    range_days: int
    total_points: int = 0
    points: list[ReportingSnapshotItem] = Field(default_factory=list)
    period_over_period: list[dict[str, Any]] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ReportingSnapshotCaptureResponse(BaseModel):
    captured: bool = True
    snapshot_scope: str
    snapshot_granularity: str = "daily"
    range_days: int
    snapshot_id: UUID
    period_start: datetime | None = None
    period_end: datetime | None = None
    period_label: str | None = None
    captured_at: datetime
    summary: list[str] = Field(default_factory=list)


class ReportingDrilldownCaseItem(BaseModel):
    case_id: UUID
    case_ref: str
    status: str
    priority: str
    assigned_to: str | None = None
    team_key: str | None = None
    team_label: str | None = None
    region_key: str | None = None
    region_label: str | None = None
    typology: str | None = None
    model_version: str | None = None
    sar_status: str | None = None
    has_sar: bool = False
    false_positive: bool = False
    workflow_delay_hours: float | None = None
    review_lag_hours: float | None = None
    approval_lag_hours: float | None = None
    filing_lag_hours: float | None = None
    audit_trail_completeness: float | None = None
    evidence_pack_completeness: float | None = None
    evidence_count: int = 0
    included_evidence_count: int = 0
    missing_evidence_count: int = 0
    progress: float | None = None
    created_at: datetime | None = None
    case_deep_link: str | None = None
    recommended_desk: str | None = None


class ReportingDrilldownResponse(BaseModel):
    generated_at: datetime
    metric_key: str
    filters: dict[str, Any] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    drill_path: list[str] = Field(default_factory=list)
    snapshot_id: UUID | None = None
    period_label: str | None = None
    summary: list[str] = Field(default_factory=list)
    cases: list[ReportingDrilldownCaseItem] = Field(default_factory=list)


class DecisionQualityAutomationAffectedItem(BaseModel):
    subject_type: str
    subject_key: str
    title: str
    severity: str = "warning"
    count: int = 0
    team_key: str | None = None
    region_key: str | None = None
    case_id: UUID | None = None
    case_ref: str | None = None
    note: str | None = None
    deep_link: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionQualityAutomationResponse(BaseModel):
    triggered_at: datetime
    triggered_by: str
    lookback_hours: int
    processed_feedback_count: int = 0
    noisy_hotspot_count: int = 0
    weak_sar_case_count: int = 0
    missing_evidence_case_count: int = 0
    items: list[DecisionQualityAutomationAffectedItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class DecisionQualitySnapshotItem(BaseModel):
    id: UUID
    snapshot_granularity: str = "daily"
    range_days: int
    period_start: datetime | None = None
    period_end: datetime | None = None
    period_label: str | None = None
    captured_at: datetime
    captured_by: str | None = None
    source: str = "manual"
    summary_metrics: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionQualitySnapshotsResponse(BaseModel):
    generated_at: datetime
    snapshot_granularity: str = "daily"
    range_days: int
    total_points: int = 0
    points: list[DecisionQualitySnapshotItem] = Field(default_factory=list)
    period_over_period: list[dict[str, Any]] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class DecisionQualityRecommendationAutomationResponse(BaseModel):
    triggered_at: datetime
    triggered_by: str
    range_days: int
    recurring_periods: int
    notification_count: int = 0
    items: list[DecisionQualityAutomationAffectedItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class WorkflowExceptionItem(BaseModel):
    key: str
    title: str
    severity: str = "warning"
    source: str
    case_id: UUID | None = None
    case_ref: str | None = None
    owner: str | None = None
    due_at: datetime | None = None
    note: str | None = None
    recommended_action: str | None = None
    deep_link: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowExceptionsResponse(BaseModel):
    generated_at: datetime
    counts: dict[str, int] = Field(default_factory=dict)
    guided_states: list[dict[str, Any]] = Field(default_factory=list)
    items: list[WorkflowExceptionItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ModelTuningRecommendationItem(BaseModel):
    recommendation_key: str
    title: str
    severity: str = "info"
    rationale: str
    suggested_version: str | None = None
    target_stage: str | None = None
    business_impact: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelTuningSummaryResponse(BaseModel):
    generated_at: datetime
    range_days: int
    current_version: str | None = None
    recommendations: list[ModelTuningRecommendationItem] = Field(default_factory=list)
    handoff_history: list[dict[str, Any]] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class ModelTuningHandoffResponse(BaseModel):
    status: str
    version: str | None = None
    recommendation_key: str | None = None
    target_stage: str | None = None
    notification_id: UUID | None = None
    summary: list[str] = Field(default_factory=list)


class ReportDistributionRuleItem(BaseModel):
    id: UUID
    rule_key: str
    display_name: str
    target_roles: list[str] = Field(default_factory=list)
    template_key: str = "manager"
    export_format: str = "pdf"
    cadence: str = "daily"
    enabled: bool = True
    channels: list[str] = Field(default_factory=list)
    recipients: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class ReportDistributionRuleUpdateRequest(BaseModel):
    display_name: str | None = Field(None, min_length=2, max_length=255)
    target_roles: list[str] | None = None
    template_key: str | None = Field(None, pattern="^(manager|executive|compliance|board)$")
    export_format: str | None = Field(None, pattern="^(json|csv|pdf|docx)$")
    cadence: str | None = Field(None, pattern="^(daily|weekly|monthly|quarterly|manual)$")
    enabled: bool | None = None
    channels: list[str] | None = None
    recipients: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_by: str | None = Field(None, max_length=255)


class ReportDistributionRunResponse(BaseModel):
    triggered_at: datetime
    cadence: str
    processed_count: int = 0
    delivered_count: int = 0
    skipped_count: int = 0
    rules: list[dict[str, Any]] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
