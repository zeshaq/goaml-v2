"""
goAML-V2 Pydantic models for alerts, cases, and screening.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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


class SarWorkflowRequest(BaseModel):
    action: SarWorkflowAction
    actor: str | None = None
    note: str | None = None


class SarFileRequest(BaseModel):
    filed_by: str | None = None
    filing_ref: str | None = None
    approved_by: str | None = None
    reviewed_by: str | None = None


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
    created_at: datetime
    updated_at: datetime


class SarQueueResponse(BaseModel):
    queue: str
    counts: SarQueueCounts
    items: list[SarQueueItem] = Field(default_factory=list)


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


class CaseTaskCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    description: str | None = None
    assigned_to: str | None = None
    created_by: str | None = None
    priority: CaseTaskPriority = CaseTaskPriority.medium
    note: str | None = None
    due_at: datetime | None = None


class CaseTaskUpdate(BaseModel):
    status: CaseTaskStatus | None = None
    assigned_to: str | None = None
    note: str | None = None
    actor: str | None = None


class CaseNoteItem(BaseModel):
    id: UUID
    author: str | None = None
    text: str
    created_at: datetime


class CaseNoteCreate(BaseModel):
    author: str | None = None
    text: str = Field(..., min_length=2, max_length=4000)
