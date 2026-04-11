"""
Model lifecycle and registry request models.
"""

from pydantic import BaseModel, Field


class EnsureRegisteredModelRequest(BaseModel):
    actor: str | None = None
    description: str | None = None


class PromoteScorerVersionRequest(BaseModel):
    version: str = Field(..., min_length=1)
    stage: str = Field(default="Production", min_length=1)
    actor: str | None = None
    notes: str | None = None
    archive_existing_versions: bool = True


class RegisterCurrentScorerRequest(BaseModel):
    actor: str | None = None
    description: str | None = None
    force_bootstrap_if_missing: bool = False


class EvaluateScorerVersionRequest(BaseModel):
    version: str = Field(..., min_length=1)
    actor: str | None = None
    evaluation_type: str = Field(default="pre_promotion", min_length=1)
    dataset_label: str | None = None
    notes: str | None = None
    auc: float | None = None
    precision_at_10: float | None = None
    recall_at_10: float | None = None
    false_positive_rate: float | None = None
    thresholds: dict[str, float] = Field(default_factory=dict)


class SubmitScorerApprovalRequest(BaseModel):
    version: str = Field(..., min_length=1)
    actor: str | None = None
    notes: str | None = None
    target_stage: str = Field(default="Production", min_length=1)


class ReviewScorerApprovalRequest(BaseModel):
    version: str = Field(..., min_length=1)
    decision: str = Field(..., min_length=1)
    actor: str | None = None
    notes: str | None = None
    request_id: str | None = None


class DeployScorerRequest(BaseModel):
    version: str | None = None
    stage: str = Field(default="Production", min_length=1)
    actor: str | None = None
    notes: str | None = None
    reload_after_deploy: bool = True


class RollbackScorerRequest(BaseModel):
    target_version: str | None = None
    actor: str | None = None
    notes: str | None = None


class EvaluateScorerChallengerRequest(BaseModel):
    challenger_version: str | None = None
    champion_version: str | None = None
    actor: str | None = None
    sample_size: int = Field(default=200, ge=25, le=500)
    lookback_hours: int = Field(default=168, ge=1, le=24 * 90)
    notes: str | None = None


class CaptureScorerDriftRequest(BaseModel):
    actor: str | None = None
    sample_size: int = Field(default=200, ge=25, le=500)
    lookback_hours: int = Field(default=168, ge=1, le=24 * 90)
    notes: str | None = None
    reset_baseline: bool = False


class ScorerTuningHandoffRequest(BaseModel):
    actor: str | None = None
    version: str | None = None
    target_stage: str = Field(default="Staging", min_length=1)
    recommendation_key: str | None = None
    notes: str | None = None
