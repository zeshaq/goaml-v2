"""
Model operations endpoints for MLflow-backed scorer lifecycle visibility.
"""

from fastapi import APIRouter, Depends, HTTPException

from models.analyst_ops import ModelOutcomeAnalyticsResponse, ModelTuningHandoffResponse, ModelTuningSummaryResponse
from models.model_ops import (
    CaptureScorerDriftRequest,
    EvaluateScorerVersionRequest,
    EvaluateScorerChallengerRequest,
    DeployScorerRequest,
    EnsureRegisteredModelRequest,
    PromoteScorerVersionRequest,
    RegisterCurrentScorerRequest,
    ReviewScorerApprovalRequest,
    RollbackScorerRequest,
    ScorerTuningHandoffRequest,
    SubmitScorerApprovalRequest,
)
from services.model_monitoring import (
    capture_scorer_drift_snapshot,
    evaluate_scorer_challenger,
    get_scorer_monitoring_summary,
)
from services.model_registry import (
    evaluate_scorer_version,
    deploy_scorer_from_registry,
    ensure_registered_model_exists,
    fetch_scorer_runtime_metadata,
    get_scorer_outcome_analytics,
    get_scorer_model_ops_summary,
    promote_registered_model_version,
    register_current_scorer_model,
    review_scorer_approval_request,
    rollback_scorer_deployment,
    submit_scorer_approval_request,
)
from services.maturity_features import get_model_tuning_summary, submit_model_tuning_handoff
from services.auth import AuthenticatedUser, require_permissions, resolve_request_actor

router = APIRouter()


@router.get("/model-ops/scorer", summary="Get scorer model registry and deployment summary")
async def get_scorer_model_ops(current_user: AuthenticatedUser = Depends(require_permissions("view_model_ops"))):
    return await get_scorer_model_ops_summary()


@router.get("/model-ops/scorer/runtime", summary="Get deployed scorer runtime metadata")
async def get_scorer_runtime(current_user: AuthenticatedUser = Depends(require_permissions("view_model_ops"))):
    return await fetch_scorer_runtime_metadata()


@router.get("/model-ops/scorer/monitoring", summary="Get scorer monitoring summary, history, and drift state")
async def get_scorer_monitoring(current_user: AuthenticatedUser = Depends(require_permissions("view_model_ops"))):
    return await get_scorer_monitoring_summary()


@router.get("/model-ops/scorer/outcomes", response_model=ModelOutcomeAnalyticsResponse, summary="Get scorer business outcome analytics by model version")
async def get_scorer_outcomes(
    days: int = 30,
    current_user: AuthenticatedUser = Depends(require_permissions("view_model_ops")),
):
    return ModelOutcomeAnalyticsResponse(**(await get_scorer_outcome_analytics(days=days)))


@router.get("/model-ops/scorer/tuning", response_model=ModelTuningSummaryResponse, summary="Get tuning recommendations and governance handoff support for the scorer")
async def get_scorer_tuning_summary(
    days: int = 90,
    current_user: AuthenticatedUser = Depends(require_permissions("view_model_ops")),
):
    return ModelTuningSummaryResponse(**(await get_model_tuning_summary(days=days)))


@router.post("/model-ops/scorer/tuning/handoff", response_model=ModelTuningHandoffResponse, summary="Submit a model tuning recommendation into the governance handoff lane")
async def post_scorer_tuning_handoff(
    payload: ScorerTuningHandoffRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    return ModelTuningHandoffResponse(
        **(
            await submit_model_tuning_handoff(
                actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
                version=payload.version,
                recommendation_key=payload.recommendation_key,
                target_stage=payload.target_stage,
                notes=payload.notes,
            )
        )
    )


@router.post("/model-ops/scorer/registry/ensure", summary="Ensure the scorer registered model exists in MLflow")
async def post_ensure_scorer_registry(
    payload: EnsureRegisteredModelRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    payload = payload or EnsureRegisteredModelRequest()
    return await ensure_registered_model_exists(
        actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
        description=payload.description,
    )


@router.post("/model-ops/scorer/promote", summary="Promote a scorer model version in MLflow")
async def post_promote_scorer_version(
    payload: PromoteScorerVersionRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    try:
        return await promote_registered_model_version(
            version=payload.version,
            stage=payload.stage,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            notes=payload.notes,
            archive_existing_versions=payload.archive_existing_versions,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model-ops/scorer/register-current", summary="Register the currently deployed scorer model into MLflow")
async def post_register_current_scorer(
    payload: RegisterCurrentScorerRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    payload = payload or RegisterCurrentScorerRequest()
    try:
        return await register_current_scorer_model(
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            description=payload.description,
            force_bootstrap_if_missing=payload.force_bootstrap_if_missing,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model-ops/scorer/evaluate", summary="Record evaluation metrics and gate results for a scorer version")
async def post_evaluate_scorer_version(
    payload: EvaluateScorerVersionRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    try:
        return await evaluate_scorer_version(
            version=payload.version,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            evaluation_type=payload.evaluation_type,
            dataset_label=payload.dataset_label,
            notes=payload.notes,
            metrics={
                "auc": payload.auc,
                "precision_at_10": payload.precision_at_10,
                "recall_at_10": payload.recall_at_10,
                "false_positive_rate": payload.false_positive_rate,
            },
            thresholds_override=payload.thresholds,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model-ops/scorer/challenger/evaluate", summary="Run a champion/challenger comparison against recent production transactions")
async def post_evaluate_scorer_challenger(
    payload: EvaluateScorerChallengerRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    payload = payload or EvaluateScorerChallengerRequest()
    try:
        return await evaluate_scorer_challenger(
            challenger_version=payload.challenger_version,
            champion_version=payload.champion_version,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            sample_size=payload.sample_size,
            lookback_hours=payload.lookback_hours,
            notes=payload.notes,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model-ops/scorer/drift/capture", summary="Capture a scorer drift snapshot against the stored monitoring baseline")
async def post_capture_scorer_drift(
    payload: CaptureScorerDriftRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    payload = payload or CaptureScorerDriftRequest()
    try:
        return await capture_scorer_drift_snapshot(
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            sample_size=payload.sample_size,
            lookback_hours=payload.lookback_hours,
            notes=payload.notes,
            reset_baseline=payload.reset_baseline,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model-ops/scorer/approval/submit", summary="Submit a scorer version for governance approval")
async def post_submit_scorer_approval(
    payload: SubmitScorerApprovalRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    try:
        return await submit_scorer_approval_request(
            version=payload.version,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            notes=payload.notes,
            target_stage=payload.target_stage,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model-ops/scorer/approval/review", summary="Approve or reject a pending scorer promotion request")
async def post_review_scorer_approval(
    payload: ReviewScorerApprovalRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    try:
        return await review_scorer_approval_request(
            version=payload.version,
            decision=payload.decision,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            notes=payload.notes,
            request_id=payload.request_id,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model-ops/scorer/deploy", summary="Deploy a promoted MLflow scorer version into goaml-scorer")
async def post_deploy_scorer(
    payload: DeployScorerRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    payload = payload or DeployScorerRequest()
    try:
        return await deploy_scorer_from_registry(
            version=payload.version,
            stage=payload.stage,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            notes=payload.notes,
            reload_after_deploy=payload.reload_after_deploy,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/model-ops/scorer/rollback", summary="Rollback goaml-scorer to the previous or selected approved model version")
async def post_rollback_scorer(
    payload: RollbackScorerRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_models")),
):
    payload = payload or RollbackScorerRequest()
    try:
        return await rollback_scorer_deployment(
            target_version=payload.target_version,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            notes=payload.notes,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
