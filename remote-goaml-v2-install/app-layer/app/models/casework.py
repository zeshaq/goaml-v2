"""
goAML-V2 Pydantic models for alerts, cases, and screening.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from models.analyst_ops import DecisionFeedbackItem
from models.intelligence import CaseContextResponse, GraphDrilldownResponse, GroundedEvidenceItem


class AlertStatus(str, Enum):
    open = "open"
    reviewing = "reviewing"
    escalated = "escalated"
    closed = "closed"
    false_positive = "false_positive"


class CaseStatus(str, Enum):
    open = "open"
    reviewing = "reviewing"
    pending_sar = "pending_sar"
    sar_filed = "sar_filed"
    closed = "closed"
    referred = "referred"


class CasePriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class AlertListItem(BaseModel):
    id: UUID
    alert_ref: str
    alert_type: str
    status: str
    severity: str
    title: str
    transaction_id: UUID | None
    account_id: UUID | None
    entity_id: UUID | None
    case_id: UUID | None
    assigned_to: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertNoteItem(BaseModel):
    action: str | None = None
    actor: str | None = None
    note: str | None = None
    created_at: datetime | None = None
    status: str | None = None
    assigned_to: str | None = None


class AlertDetail(AlertListItem):
    description: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    ml_explanation: str | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    closed_at: datetime | None = None
    resolution_note: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    analyst_notes: list[AlertNoteItem] = Field(default_factory=list)
    feedback: list[DecisionFeedbackItem] = Field(default_factory=list)
    updated_at: datetime | None = None


class AlertStatusUpdate(BaseModel):
    status: AlertStatus
    reviewed_by: str | None = None
    resolution_note: str | None = None


class AlertInvestigateRequest(BaseModel):
    assigned_to: str | None = None
    reviewed_by: str | None = None
    create_case: bool = False
    case_title: str | None = None
    case_description: str | None = None
    priority: CasePriority = CasePriority.medium
    created_by: str | None = None


class AlertAction(str, Enum):
    investigate = "investigate"
    dismiss = "dismiss"
    false_positive = "false_positive"
    escalate = "escalate"
    add_note = "add_note"


class AlertActionRequest(BaseModel):
    action: AlertAction
    actor: str | None = None
    assigned_to: str | None = None
    note: str | None = None
    create_case: bool | None = None
    priority: CasePriority = CasePriority.high
    case_title: str | None = None
    case_description: str | None = None


class CaseCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=512)
    description: str | None = None
    priority: CasePriority = CasePriority.medium
    assigned_to: str | None = None
    created_by: str | None = None
    primary_account_id: UUID | None = None
    primary_entity_id: UUID | None = None
    sar_required: bool = False
    alert_ids: list[UUID] = Field(default_factory=list)
    transaction_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseUpdate(BaseModel):
    status: CaseStatus | None = None
    priority: CasePriority | None = None
    assigned_to: str | None = None
    closed_by: str | None = None
    ai_summary: str | None = None
    ai_risk_factors: list[str] | None = None
    sar_required: bool | None = None
    add_alert_ids: list[UUID] = Field(default_factory=list)
    add_transaction_ids: list[UUID] = Field(default_factory=list)
    event_actor: str | None = None
    event_detail: str | None = None


class CaseListItem(BaseModel):
    id: UUID
    case_ref: str
    title: str
    status: str
    priority: str
    assigned_to: str | None
    sar_required: bool
    created_at: datetime
    alert_count: int = 0
    transaction_count: int = 0

    model_config = {"from_attributes": True}


class CaseDetail(BaseModel):
    id: UUID
    case_ref: str
    title: str
    description: str | None
    status: str
    priority: str
    assigned_to: str | None
    created_by: str | None
    closed_by: str | None
    closed_at: datetime | None
    primary_account_id: UUID | None
    primary_entity_id: UUID | None
    sar_required: bool
    sar_id: UUID | None
    ai_summary: str | None
    ai_risk_factors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    alert_ids: list[UUID] = Field(default_factory=list)
    transaction_ids: list[UUID] = Field(default_factory=list)


class CaseEventItem(BaseModel):
    id: UUID
    case_id: UUID
    event_type: str
    actor: str | None
    detail: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class SarWorkflowAction(str, Enum):
    submit_review = "submit_review"
    approve = "approve"
    reject = "reject"


class SarDraftRequest(BaseModel):
    drafted_by: str | None = None
    subject_name: str | None = None
    subject_account: str | None = None
    subject_type: str | None = None
    activity_type: str | None = None
    prioritize_pinned_evidence: bool = True


class SarWorkflowRequest(BaseModel):
    action: SarWorkflowAction
    actor: str | None = None
    note: str | None = None


class SarFileRequest(BaseModel):
    filed_by: str | None = None
    filing_ref: str | None = None
    approved_by: str | None = None
    reviewed_by: str | None = None


class SarUpdateRequest(BaseModel):
    narrative: str | None = Field(None, min_length=10, max_length=20000)
    subject_name: str | None = Field(None, max_length=255)
    subject_type: str | None = Field(None, max_length=64)
    subject_account: str | None = Field(None, max_length=255)
    activity_type: str | None = Field(None, max_length=255)
    editor: str | None = Field(None, max_length=255)
    note: str | None = Field(None, max_length=4000)


class SarReportDetail(BaseModel):
    id: UUID
    sar_ref: str
    case_id: UUID | None
    status: str
    subject_name: str | None
    subject_type: str | None
    subject_account: str | None
    narrative: str | None
    activity_type: str | None
    activity_amount: float | None
    activity_from: datetime | None
    activity_to: datetime | None
    filing_agency: str | None
    drafted_by: str | None
    drafted_at: datetime | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    approved_by: str | None
    approved_at: datetime | None
    filed_at: datetime | None
    filing_ref: str | None
    ai_drafted: bool
    ai_model: str | None
    metadata: dict[str, Any] = Field(default_factory=dict)
    used_evidence: list[GroundedEvidenceItem] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class SarQueueCounts(BaseModel):
    draft: int = 0
    review: int = 0
    approval: int = 0
    filed: int = 0
    total: int = 0


class SarQueueItem(BaseModel):
    case_id: UUID
    case_ref: str
    case_title: str
    case_status: str
    case_priority: str
    assigned_to: str | None = None
    primary_entity_id: UUID | None = None
    primary_account_id: UUID | None = None
    alert_count: int = 0
    transaction_count: int = 0
    sar_id: UUID
    sar_ref: str
    sar_status: str
    subject_name: str | None = None
    subject_type: str | None = None
    subject_account: str | None = None
    activity_type: str | None = None
    activity_amount: float | None = None
    drafted_by: str | None = None
    drafted_at: datetime | None = None
    reviewed_by: str | None = None
    reviewed_at: datetime | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None
    filed_at: datetime | None = None
    filing_ref: str | None = None
    ai_drafted: bool = False
    ai_model: str | None = None
    latest_workflow_note: str | None = None
    workflow_step_count: int = 0
    queue_owner: str | None = None
    age_hours: float | None = None
    sla_hours: float | None = None
    sla_due_at: datetime | None = None
    sla_status: str | None = None
    created_at: datetime
    updated_at: datetime


class SarQueueSlaMetric(BaseModel):
    queue: str
    label: str
    item_count: int = 0
    breached_count: int = 0
    due_soon_count: int = 0
    avg_age_hours: float | None = None
    oldest_age_hours: float | None = None
    sla_hours: float | None = None


class SarWorkloadOwnerItem(BaseModel):
    owner: str
    display_name: str
    draft_count: int = 0
    review_count: int = 0
    approval_count: int = 0
    filed_count: int = 0
    breached_count: int = 0
    high_priority_count: int = 0
    avg_age_hours: float | None = None
    oldest_age_hours: float | None = None


class SarQueueAnalytics(BaseModel):
    generated_at: datetime
    overall_breached_count: int = 0
    overall_due_soon_count: int = 0
    active_owner_count: int = 0
    queue_sla: list[SarQueueSlaMetric] = Field(default_factory=list)
    owner_workloads: list[SarWorkloadOwnerItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class SarQueueResponse(BaseModel):
    queue: str
    counts: SarQueueCounts
    analytics: SarQueueAnalytics | None = None
    items: list[SarQueueItem] = Field(default_factory=list)


class SarRebalanceRequest(BaseModel):
    actor: str | None = None
    queue: str = Field("all", pattern="^(draft|review|approval|all)$")
    limit: int = Field(8, ge=1, le=100)
    analyst_pool: list[str] = Field(default_factory=list)
    breached_only: bool = True
    include_due_soon: bool = True
    max_items_per_owner: int | None = Field(None, ge=1, le=50)
    min_workload_gap: int = Field(1, ge=1, le=10)


class SarRebalanceItem(BaseModel):
    case_id: UUID
    case_ref: str
    sar_id: UUID
    sar_ref: str
    queue: str
    previous_owner: str | None = None
    new_owner: str
    previous_active_count: int = 0
    new_owner_active_count: int = 0
    sla_status: str | None = None
    case_priority: str | None = None
    note: str | None = None


class SarRebalanceResponse(BaseModel):
    queue: str
    processed_count: int = 0
    reassigned_count: int = 0
    owner_count: int = 0
    items: list[SarRebalanceItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    generated_at: datetime


class SlaSnapshotCaptureRequest(BaseModel):
    triggered_by: str | None = None
    source: str = "manual"
    force: bool = False
    bootstrap_if_empty: bool = False
    backfill_hours: int = Field(0, ge=0, le=24 * 30)
    interval_minutes: int = Field(60, ge=15, le=24 * 60)


class SarQueueSnapshotPoint(BaseModel):
    captured_at: datetime
    counts: SarQueueCounts = Field(default_factory=SarQueueCounts)
    overall_breached_count: int = 0
    overall_due_soon_count: int = 0
    active_owner_count: int = 0
    avg_active_age_hours: float | None = None
    oldest_active_age_hours: float | None = None
    queue_metrics: dict[str, SarQueueSlaMetric] = Field(default_factory=dict)
    source: str | None = None
    captured_by: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SarQueueTrendResponse(BaseModel):
    generated_at: datetime
    range_hours: int
    snapshot_count: int = 0
    oldest_snapshot_at: datetime | None = None
    latest_snapshot_at: datetime | None = None
    points: list[SarQueueSnapshotPoint] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class SlaSnapshotCaptureResponse(BaseModel):
    captured: bool = True
    inserted_count: int = 0
    snapshot_count: int = 0
    latest_snapshot_at: datetime | None = None
    oldest_snapshot_at: datetime | None = None
    source: str | None = None
    triggered_by: str | None = None
    summary: list[str] = Field(default_factory=list)


class ScreenEntityRequest(BaseModel):
    entity_name: str = Field(..., min_length=2, max_length=512)
    trigger: str = "manual"
    linked_txn_id: UUID | None = None
    screened_by: str | None = None
    limit: int = Field(5, ge=1, le=20)


class ScreeningResultItem(BaseModel):
    id: UUID
    entity_name: str
    matched_name: str | None
    match_score: float | None
    dataset: str | None
    dataset_id: str | None
    match_type: str | None
    matched_country: str | None
    screened_by: str | None
    trigger: str | None
    linked_txn_id: UUID | None
    matched_detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class ScreeningPanel(BaseModel):
    key: str
    label: str
    result_count: int
    results: list[ScreeningResultItem] = Field(default_factory=list)


class ScreeningResponse(BaseModel):
    query: str
    result_count: int
    results: list[ScreeningResultItem]
    panels: list[ScreeningPanel] = Field(default_factory=list)
    sample_queries: dict[str, str] = Field(default_factory=dict)


class AlertActionResponse(BaseModel):
    action: str
    alert: AlertDetail
    case: CaseDetail | None = None


class CaseTaskStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    blocked = "blocked"
    done = "done"


class CaseTaskPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class CaseTaskItem(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    status: str
    priority: str
    assigned_to: str | None = None
    created_by: str | None = None
    note: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseTaskCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: str | None = None
    assigned_to: str | None = None
    created_by: str | None = None
    priority: CaseTaskPriority = CaseTaskPriority.medium
    note: str | None = None
    due_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseTaskUpdate(BaseModel):
    status: CaseTaskStatus | None = None
    assigned_to: str | None = None
    note: str | None = None
    actor: str | None = None


class PlaybookChecklistItem(BaseModel):
    key: str
    label: str
    description: str | None = None
    status: str
    blocking: bool = True
    guidance: str | None = None
    evidence_related: bool = False
    auto_task_id: UUID | None = None


class PlaybookEvidenceRuleItem(BaseModel):
    rule_key: str
    label: str
    required: bool = True
    met: bool = False
    current_value: float | int | bool | str | None = None
    required_value: float | int | bool | str | None = None
    message: str | None = None


class CasePlaybookState(BaseModel):
    typology: str
    display_name: str
    active: bool = True
    checklist_progress: int = 0
    checklist_completed_count: int = 0
    checklist_total_count: int = 0
    checklist: list[PlaybookChecklistItem] = Field(default_factory=list)
    blocked_steps: list[str] = Field(default_factory=list)
    required_evidence_missing: list[str] = Field(default_factory=list)
    evidence_rules: list[PlaybookEvidenceRuleItem] = Field(default_factory=list)
    suggested_tasks: list[str] = Field(default_factory=list)
    sla_targets: dict[str, float] = Field(default_factory=dict)
    summary: list[str] = Field(default_factory=list)
    configured_at: datetime | None = None
    updated_at: datetime | None = None


class PlaybookConfigItem(BaseModel):
    typology: str
    display_name: str
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    evidence_rules: dict[str, Any] = Field(default_factory=dict)
    sla_targets: dict[str, dict[str, float]] = Field(default_factory=dict)
    task_templates: list[dict[str, Any]] = Field(default_factory=list)
    updated_by: str | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlaybookConfigUpdateRequest(BaseModel):
    display_name: str | None = Field(None, min_length=3, max_length=255)
    checklist: list[dict[str, Any]] | None = None
    evidence_rules: dict[str, Any] | None = None
    sla_targets: dict[str, dict[str, float]] | None = None
    task_templates: list[dict[str, Any]] | None = None
    updated_by: str | None = Field(None, max_length=255)
    metadata: dict[str, Any] | None = None


class PlaybookBackfillResponse(BaseModel):
    processed_count: int = 0
    applied_count: int = 0
    task_count: int = 0
    summary: list[str] = Field(default_factory=list)
    generated_at: datetime


class PlaybookChecklistComplianceItem(BaseModel):
    typology: str
    display_name: str
    case_count: int = 0
    checklist_completion_rate: float = 0.0
    fully_completed_case_rate: float = 0.0
    avg_progress: float = 0.0
    blocked_case_rate: float = 0.0
    false_positive_rate: float = 0.0
    sar_conversion_rate: float = 0.0
    filed_sar_rate: float = 0.0
    missing_evidence_case_rate: float = 0.0


class PlaybookMissedStepItem(BaseModel):
    typology: str
    display_name: str
    step_key: str
    step_label: str
    missed_count: int = 0
    affected_case_rate: float = 0.0
    blocking: bool = True
    evidence_related: bool = False


class PlaybookBlockedTrendPoint(BaseModel):
    bucket: str
    blocked_case_count: int = 0
    blocked_step_total: int = 0
    missing_evidence_total: int = 0


class PlaybookScopeBreakdownItem(BaseModel):
    scope_key: str
    scope_label: str
    case_count: int = 0
    typology_count: int = 0
    avg_progress: float = 0.0
    blocked_case_rate: float = 0.0
    missing_evidence_case_rate: float = 0.0
    false_positive_rate: float = 0.0
    sar_conversion_rate: float = 0.0
    filed_sar_rate: float = 0.0


class PlaybookStepHeatmapItem(BaseModel):
    scope_type: str
    scope_key: str
    scope_label: str
    typology: str
    display_name: str
    step_key: str
    step_label: str
    affected_case_count: int = 0
    affected_case_rate: float = 0.0
    blocking_case_count: int = 0
    evidence_gap_case_count: int = 0


class PlaybookAnalyticsResponse(BaseModel):
    generated_at: datetime
    range_days: int
    totals: dict[str, Any] = Field(default_factory=dict)
    typologies: list[PlaybookChecklistComplianceItem] = Field(default_factory=list)
    most_missed_steps: list[PlaybookMissedStepItem] = Field(default_factory=list)
    blocked_step_trends: list[PlaybookBlockedTrendPoint] = Field(default_factory=list)
    team_breakdown: list[PlaybookScopeBreakdownItem] = Field(default_factory=list)
    region_breakdown: list[PlaybookScopeBreakdownItem] = Field(default_factory=list)
    worst_offending_steps: list[PlaybookStepHeatmapItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class PlaybookAutomationSettings(BaseModel):
    stuck_hours: float = 18.0
    evidence_gap_warning_hours: float = 8.0
    cooldown_hours: float = 12.0
    max_cases: int = 50
    updated_by: str | None = None
    updated_at: datetime | None = None
    summary: list[str] = Field(default_factory=list)


class PlaybookAutomationSettingsUpdateRequest(BaseModel):
    stuck_hours: float | None = Field(None, ge=1, le=168)
    evidence_gap_warning_hours: float | None = Field(None, ge=1, le=72)
    cooldown_hours: float | None = Field(None, ge=1, le=168)
    max_cases: int | None = Field(None, ge=1, le=200)
    updated_by: str | None = None


class CaseNoteItem(BaseModel):
    id: UUID
    author: str | None = None
    text: str
    created_at: datetime


class CaseNoteCreate(BaseModel):
    author: str | None = None
    text: str = Field(..., min_length=2, max_length=4000)


class CaseEvidenceItem(BaseModel):
    id: UUID
    case_id: UUID
    evidence_type: str
    source_evidence_id: str | None = None
    title: str
    summary: str | None = None
    source: str | None = None
    importance: int = 50
    include_in_sar: bool = False
    pinned_by: str | None = None
    pinned_at: datetime
    updated_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseEvidencePinRequest(BaseModel):
    evidence_type: str = Field(..., min_length=2, max_length=64)
    source_evidence_id: str | None = Field(None, max_length=255)
    title: str = Field(..., min_length=2, max_length=1000)
    summary: str | None = Field(None, max_length=4000)
    source: str | None = Field(None, max_length=64)
    importance: int = Field(50, ge=0, le=100)
    include_in_sar: bool = False
    pinned_by: str | None = Field(None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseEvidenceUpdateRequest(BaseModel):
    title: str | None = Field(None, min_length=2, max_length=1000)
    summary: str | None = Field(None, max_length=4000)
    importance: int | None = Field(None, ge=0, le=100)
    include_in_sar: bool | None = None
    updated_by: str | None = Field(None, max_length=255)
    metadata: dict[str, Any] | None = None


class CaseEvidenceDeleteResponse(BaseModel):
    status: str
    case_id: UUID
    evidence_id: UUID


class CaseWorkflowStateResponse(BaseModel):
    case_id: UUID
    case_ref: str
    routing: dict[str, Any] = Field(default_factory=dict)
    queue_item: dict[str, Any] | None = None
    owner_workload: dict[str, Any] | None = None
    active_process: dict[str, Any] | None = None
    active_task: dict[str, Any] | None = None
    expected_role: str | None = None
    process_history: list[dict[str, Any]] = Field(default_factory=list)
    latest_automation_touches: list[dict[str, Any]] = Field(default_factory=list)
    quick_links: dict[str, Any] = Field(default_factory=dict)
    notifications: list[dict[str, Any]] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    generated_at: datetime


class FilingReadinessResponse(BaseModel):
    case_id: UUID
    case_ref: str
    sar_id: UUID | None = None
    sar_status: str | None = None
    overall_status: str
    score: int = 0
    blocking_items: list[str] = Field(default_factory=list)
    warning_items: list[str] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)
    recommended_next_actions: list[str] = Field(default_factory=list)
    playbook: CasePlaybookState | None = None
    generated_at: datetime


class CaseFilingPackRequest(BaseModel):
    generated_by: str | None = None
    include_notes: bool = True
    include_tasks: bool = True
    include_ai_summary: bool = True
    evidence_limit: int = Field(12, ge=3, le=30)


class CaseFilingPackResponse(BaseModel):
    case_id: UUID
    case_ref: str
    generated_by: str | None = None
    generated_at: datetime
    summary: list[str] = Field(default_factory=list)
    ai_summary: str | None = None
    risk_factors: list[str] = Field(default_factory=list)
    sar: SarReportDetail | None = None
    workflow: CaseWorkflowStateResponse | None = None
    filing_readiness: FilingReadinessResponse
    grounding_mode: str | None = None
    used_evidence: list[GroundedEvidenceItem] = Field(default_factory=list)
    filing_evidence: list[GroundedEvidenceItem] = Field(default_factory=list)
    supporting_evidence: list[GroundedEvidenceItem] = Field(default_factory=list)
    notes: list[CaseNoteItem] = Field(default_factory=list)
    tasks: list[CaseTaskItem] = Field(default_factory=list)


class CaseWorkspaceResponse(BaseModel):
    case: CaseDetail
    events: list[CaseEventItem] = Field(default_factory=list)
    sar: SarReportDetail | None = None
    context: CaseContextResponse | None = None
    graph: GraphDrilldownResponse | None = None
    tasks: list[CaseTaskItem] = Field(default_factory=list)
    notes: list[CaseNoteItem] = Field(default_factory=list)
    feedback: list[DecisionFeedbackItem] = Field(default_factory=list)
    workflow: CaseWorkflowStateResponse
    pinned_evidence: list[CaseEvidenceItem] = Field(default_factory=list)
    filing_readiness: FilingReadinessResponse
    playbook: CasePlaybookState | None = None
