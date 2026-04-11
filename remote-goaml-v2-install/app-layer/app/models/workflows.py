"""
Workflow and automation request models.
"""

from pydantic import BaseModel, Field


class SlaNotificationRequest(BaseModel):
    triggered_by: str | None = None
    channels: list[str] = Field(default_factory=lambda: ["slack", "email"])
    breached_only: bool = True
    include_due_soon: bool | None = None


class ModelMonitoringNotificationRequest(BaseModel):
    triggered_by: str | None = None
    channels: list[str] = Field(default_factory=lambda: ["slack", "email"])
    include_stable: bool = False
    force: bool = False


class PlaybookAutomationRequest(BaseModel):
    triggered_by: str | None = None
    stuck_hours: float | None = Field(None, ge=1, le=168)
    evidence_gap_warning_hours: float | None = Field(None, ge=1, le=72)
    cooldown_hours: float | None = Field(None, ge=1, le=168)
    limit: int | None = Field(None, ge=1, le=200)
    force: bool = False


class ReportingAlertRequest(BaseModel):
    triggered_by: str | None = None
    channels: list[str] = Field(default_factory=lambda: ["slack", "email", "app"])
    snapshot_scope: str = Field("manager", pattern="^(manager|executive|compliance|board)$")
    range_days: int = Field(180, ge=30, le=365)
    force: bool = False


class DecisionQualityAutomationRequest(BaseModel):
    triggered_by: str | None = None
    lookback_hours: int = Field(168, ge=12, le=24 * 30)
    noisy_threshold: int = Field(2, ge=1, le=50)
    weak_sar_threshold: int = Field(1, ge=1, le=20)
    missing_evidence_threshold: int = Field(1, ge=1, le=20)
    cooldown_hours: float = Field(12, ge=1, le=168)
    limit: int = Field(60, ge=1, le=300)
    force: bool = False


class DecisionQualityRecommendationAutomationRequest(BaseModel):
    triggered_by: str | None = None
    range_days: int = Field(180, ge=30, le=365)
    recurring_periods: int = Field(2, ge=2, le=6)
    noisy_threshold: float = Field(0.3, ge=0, le=1)
    drafter_rejection_threshold: float = Field(0.2, ge=0, le=1)
    cooldown_hours: float = Field(24, ge=1, le=168)
    force: bool = False


class WorkflowExceptionActionRequest(BaseModel):
    actor: str | None = None
    case_id: str | None = None
    action: str = Field(..., min_length=2, max_length=64)
    note: str | None = None
