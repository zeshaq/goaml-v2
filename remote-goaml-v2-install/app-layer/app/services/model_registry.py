"""
MLflow-backed scorer registry and deployment metadata helpers.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import httpx

from core.config import settings
from core.database import get_pool


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_tags(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(k): str(v) for k, v in value.items()}
    if isinstance(value, list):
        output: dict[str, str] = {}
        for item in value:
            if isinstance(item, dict):
                key = item.get("key")
                if key is None:
                    continue
                output[str(key)] = str(item.get("value", ""))
        return output
    return {}


def _normalize_timestamp(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        raw = float(value)
    except (TypeError, ValueError):
        return None
    if raw > 10_000_000_000:
        raw = raw / 1000.0
    return datetime.fromtimestamp(raw, tz=timezone.utc).isoformat()


def _titleize(value: str) -> str:
    return str(value or "").replace("_", " ").title()


def _normalize_version_item(record: dict[str, Any]) -> dict[str, Any]:
    tags = _normalize_tags(record.get("tags"))
    aliases = record.get("aliases")
    if not isinstance(aliases, list):
        aliases = []
    return {
        "name": record.get("name") or settings.SCORER_REGISTERED_MODEL_NAME,
        "version": str(record.get("version") or ""),
        "stage": record.get("current_stage") or record.get("stage") or "None",
        "status": record.get("status"),
        "run_id": record.get("run_id"),
        "source": record.get("source"),
        "description": record.get("description"),
        "tags": tags,
        "aliases": aliases,
        "created_at": _normalize_timestamp(record.get("creation_timestamp")),
        "updated_at": _normalize_timestamp(record.get("last_updated_timestamp")),
    }


def _default_eval_thresholds() -> dict[str, float]:
    return {
        "auc": float(settings.SCORER_EVAL_MIN_AUC),
        "precision_at_10": float(settings.SCORER_EVAL_MIN_PRECISION_AT_10),
        "recall_at_10": float(settings.SCORER_EVAL_MIN_RECALL_AT_10),
        "false_positive_rate": float(settings.SCORER_EVAL_MAX_FALSE_POSITIVE_RATE),
    }


def _coerce_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _build_eval_gate_results(
    metrics: dict[str, float | None],
    thresholds: dict[str, float],
) -> tuple[dict[str, Any], str]:
    gate_results: dict[str, Any] = {}
    overall_pass = True
    for name, threshold in thresholds.items():
        measured = metrics.get(name)
        if name == "false_positive_rate":
            passed = measured is not None and float(measured) <= float(threshold)
            comparator = "<="
        else:
            passed = measured is not None and float(measured) >= float(threshold)
            comparator = ">="
        gate_results[name] = {
            "measured": measured,
            "threshold": float(threshold),
            "comparator": comparator,
            "passed": bool(passed),
        }
        if not passed:
            overall_pass = False
    return gate_results, "passed" if overall_pass else "failed"


async def _mlflow_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    base = settings.MLFLOW_TRACKING_URI.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(f"{base}{path}", params=params)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


async def _mlflow_post(path: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    base = settings.MLFLOW_TRACKING_URI.rstrip("/")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(f"{base}{path}", json=payload)
    if response.status_code == 409:
        try:
            return response.json()
        except Exception:
            return {"message": "conflict"}
    response.raise_for_status()
    try:
        return response.json()
    except Exception:
        return {}


async def _scorer_post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    base = settings.SCORER_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=settings.SCORER_ADMIN_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{base}{path}", json=payload)
    response.raise_for_status()
    return response.json()


async def _set_model_version_tag(name: str, version: str, key: str, value: str) -> None:
    await _mlflow_post(
        "/api/2.0/mlflow/model-versions/set-tag",
        {"name": name, "version": str(version), "key": key, "value": value},
    )


async def _latest_evaluation_record(version: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM model_evaluations
            WHERE registered_model_name = $1 AND version = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            str(version),
        )
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "registered_model_name": row["registered_model_name"],
        "version": row["version"],
        "evaluation_type": row["evaluation_type"],
        "evaluator": row["evaluator"],
        "dataset_label": row["dataset_label"],
        "summary": row["summary"],
        "notes": row["notes"],
        "metrics": _coerce_json(row["metrics"]),
        "thresholds": _coerce_json(row["thresholds"]),
        "gate_results": _coerce_json(row["gate_results"]),
        "overall_status": row["overall_status"],
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def _latest_approval_record(version: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM model_approval_requests
            WHERE registered_model_name = $1 AND version = $2
            ORDER BY submitted_at DESC
            LIMIT 1
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            str(version),
        )
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "registered_model_name": row["registered_model_name"],
        "version": row["version"],
        "target_stage": row["target_stage"],
        "status": row["status"],
        "submitted_by": row["submitted_by"],
        "submitted_notes": row["submitted_notes"],
        "reviewer": row["reviewer"],
        "review_notes": row["review_notes"],
        "evaluation_id": str(row["evaluation_id"]) if row["evaluation_id"] else None,
        "submitted_at": row["submitted_at"].isoformat() if row["submitted_at"] else None,
        "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
    }


async def _record_deployment_event(
    version: str,
    *,
    stage: str | None,
    action: str,
    actor: str | None,
    notes: str | None,
    previous_version: str | None,
    previous_stage: str | None,
    run_id: str | None,
    source_uri: str | None,
    metadata: dict[str, Any] | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO model_deployment_events (
                registered_model_name,
                version,
                stage,
                action,
                actor,
                notes,
                previous_version,
                previous_stage,
                run_id,
                source_uri,
                metadata
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11::jsonb)
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            str(version),
            stage,
            action,
            actor,
            notes,
            previous_version,
            previous_stage,
            run_id,
            source_uri,
            json.dumps(metadata or {}),
        )


async def _governance_records(limit: int = 12) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        evaluation_rows = await conn.fetch(
            """
            SELECT *
            FROM model_evaluations
            WHERE registered_model_name = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            limit,
        )
        approval_rows = await conn.fetch(
            """
            SELECT *
            FROM model_approval_requests
            WHERE registered_model_name = $1
            ORDER BY submitted_at DESC
            LIMIT $2
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            limit,
        )
        deployment_rows = await conn.fetch(
            """
            SELECT *
            FROM model_deployment_events
            WHERE registered_model_name = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            limit,
        )

    evaluations = [
        {
            "id": str(row["id"]),
            "version": row["version"],
            "evaluation_type": row["evaluation_type"],
            "evaluator": row["evaluator"],
            "dataset_label": row["dataset_label"],
            "summary": row["summary"],
            "notes": row["notes"],
            "metrics": _coerce_json(row["metrics"]),
            "thresholds": _coerce_json(row["thresholds"]),
            "gate_results": _coerce_json(row["gate_results"]),
            "overall_status": row["overall_status"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in evaluation_rows
    ]
    approvals = [
        {
            "id": str(row["id"]),
            "version": row["version"],
            "target_stage": row["target_stage"],
            "status": row["status"],
            "submitted_by": row["submitted_by"],
            "submitted_notes": row["submitted_notes"],
            "reviewer": row["reviewer"],
            "review_notes": row["review_notes"],
            "evaluation_id": str(row["evaluation_id"]) if row["evaluation_id"] else None,
            "submitted_at": row["submitted_at"].isoformat() if row["submitted_at"] else None,
            "reviewed_at": row["reviewed_at"].isoformat() if row["reviewed_at"] else None,
        }
        for row in approval_rows
    ]
    deployments = [
        {
            "id": str(row["id"]),
            "version": row["version"],
            "stage": row["stage"],
            "action": row["action"],
            "actor": row["actor"],
            "notes": row["notes"],
            "previous_version": row["previous_version"],
            "previous_stage": row["previous_stage"],
            "run_id": row["run_id"],
            "source_uri": row["source_uri"],
            "metadata": _coerce_json(row["metadata"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in deployment_rows
    ]
    return evaluations, approvals, deployments


async def _ensure_version_governance_ready(version: str, target_stage: str) -> tuple[dict[str, Any], dict[str, Any]]:
    evaluation, approval = await asyncio.gather(
        _latest_evaluation_record(version),
        _latest_approval_record(version),
    )
    if not evaluation:
        raise RuntimeError(
            f"Version {version} has no recorded evaluation. Run a scorer evaluation before promoting to {target_stage}."
        )
    if str(evaluation.get("overall_status", "")).lower() != "passed":
        raise RuntimeError(
            f"Version {version} failed the latest evaluation gate. Review the evaluation results before promoting."
        )
    if not approval:
        raise RuntimeError(
            f"Version {version} has no approval request on record. Submit and approve a promotion request first."
        )
    if str(approval.get("status", "")).lower() != "approved":
        raise RuntimeError(
            f"Version {version} is not approved for {target_stage}. Current approval status is {approval.get('status') or 'unknown'}."
        )
    return evaluation, approval


async def fetch_registered_model(name: str | None = None) -> dict[str, Any] | None:
    model_name = name or settings.SCORER_REGISTERED_MODEL_NAME
    response = await _mlflow_get(
        "/api/2.0/mlflow/registered-models/get",
        params={"name": model_name},
    )
    if not response:
        return None
    model = response.get("registered_model") or {}
    return {
        "name": model.get("name") or model_name,
        "description": model.get("description"),
        "tags": _normalize_tags(model.get("tags")),
        "creation_timestamp": model.get("creation_timestamp"),
        "last_updated_timestamp": model.get("last_updated_timestamp"),
        "created_at": _normalize_timestamp(model.get("creation_timestamp")),
        "updated_at": _normalize_timestamp(model.get("last_updated_timestamp")),
        "latest_versions": [_normalize_version_item(item) for item in model.get("latest_versions", [])],
    }


async def fetch_registered_model_versions(name: str | None = None) -> list[dict[str, Any]]:
    model_name = name or settings.SCORER_REGISTERED_MODEL_NAME
    response = await _mlflow_get(
        "/api/2.0/mlflow/model-versions/search",
        params={"filter": f"name='{model_name}'"},
    )
    if not response:
        return []
    return [
        _normalize_version_item(item)
        for item in response.get("model_versions", []) or []
    ]


async def ensure_registered_model_exists(
    actor: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    model_name = settings.SCORER_REGISTERED_MODEL_NAME
    existing = await fetch_registered_model(model_name)
    created = False
    if not existing:
        await _mlflow_post(
            "/api/2.0/mlflow/registered-models/create",
            {
                "name": model_name,
                "description": description
                or "goAML XGBoost transaction risk scorer managed through Model Ops.",
            },
        )
        created = True
    tags_to_set = {
        "system": "goaml-v2",
        "model_type": "xgboost-transaction-scorer",
        "deployment_target": "goaml-scorer",
        "managed_by": "model-ops-api",
        "last_registry_sync_at": _utc_now_iso(),
    }
    if actor:
        tags_to_set["last_registry_sync_by"] = actor
    for key, value in tags_to_set.items():
        await _mlflow_post(
            "/api/2.0/mlflow/registered-models/set-tag",
            {"name": model_name, "key": key, "value": value},
        )
    summary = await get_scorer_model_ops_summary()
    summary["ensure_result"] = {
        "created": created,
        "actor": actor,
        "description": description,
        "completed_at": _utc_now_iso(),
    }
    return summary


async def evaluate_scorer_version(
    version: str,
    *,
    actor: str | None = None,
    evaluation_type: str = "pre_promotion",
    dataset_label: str | None = None,
    notes: str | None = None,
    metrics: dict[str, float | None] | None = None,
    thresholds_override: dict[str, float] | None = None,
) -> dict[str, Any]:
    metrics = metrics or {}
    thresholds = {**_default_eval_thresholds(), **(thresholds_override or {})}
    gate_results, overall_status = _build_eval_gate_results(metrics, thresholds)
    summary_text = (
        f"Evaluation {overall_status} for version {version}"
        + (f" on {dataset_label}" if dataset_label else "")
    )
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO model_evaluations (
                registered_model_name,
                version,
                evaluation_type,
                evaluator,
                dataset_label,
                summary,
                notes,
                metrics,
                thresholds,
                gate_results,
                overall_status
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10::jsonb,$11)
            RETURNING id, created_at
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            str(version),
            evaluation_type,
            actor,
            dataset_label,
            summary_text,
            notes,
            json.dumps(metrics),
            json.dumps(thresholds),
            json.dumps(gate_results),
            overall_status,
        )
    await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "evaluation_status", overall_status)
    await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "last_evaluated_at", _utc_now_iso())
    if actor:
        await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "last_evaluated_by", actor)
    if dataset_label:
        await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "evaluation_dataset", dataset_label)
    summary = await get_scorer_model_ops_summary()
    summary["evaluation_result"] = {
        "id": str(row["id"]),
        "version": str(version),
        "overall_status": overall_status,
        "metrics": metrics,
        "thresholds": thresholds,
        "gate_results": gate_results,
        "actor": actor,
        "dataset_label": dataset_label,
        "notes": notes,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }
    return summary


async def submit_scorer_approval_request(
    version: str,
    *,
    actor: str | None = None,
    notes: str | None = None,
    target_stage: str = "Production",
) -> dict[str, Any]:
    latest_evaluation = await _latest_evaluation_record(version)
    if not latest_evaluation:
        raise RuntimeError(f"Version {version} has no evaluation on record. Evaluate it before requesting approval.")
    if str(latest_evaluation.get("overall_status", "")).lower() != "passed":
        raise RuntimeError(f"Version {version} did not pass its latest evaluation and cannot be submitted for approval.")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO model_approval_requests (
                registered_model_name,
                version,
                target_stage,
                status,
                submitted_by,
                submitted_notes,
                evaluation_id
            ) VALUES ($1,$2,$3,'pending',$4,$5,$6)
            RETURNING id, submitted_at
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            str(version),
            target_stage,
            actor,
            notes,
            latest_evaluation["id"],
        )
    await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "approval_status", "pending")
    await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "approval_requested_at", _utc_now_iso())
    if actor:
        await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "approval_requested_by", actor)
    summary = await get_scorer_model_ops_summary()
    summary["approval_submit_result"] = {
        "id": str(row["id"]),
        "version": str(version),
        "status": "pending",
        "target_stage": target_stage,
        "actor": actor,
        "notes": notes,
        "submitted_at": row["submitted_at"].isoformat() if row["submitted_at"] else None,
    }
    return summary


async def review_scorer_approval_request(
    version: str,
    *,
    decision: str,
    actor: str | None = None,
    notes: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    normalized_decision = decision.strip().lower()
    if normalized_decision not in {"approve", "approved", "reject", "rejected"}:
        raise RuntimeError("Decision must be approve or reject.")
    target_status = "approved" if normalized_decision.startswith("approve") else "rejected"
    pool = get_pool()
    async with pool.acquire() as conn:
        if request_id:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM model_approval_requests
                WHERE id = $1
                """,
                request_id,
            )
        else:
            row = await conn.fetchrow(
                """
                SELECT *
                FROM model_approval_requests
                WHERE registered_model_name = $1 AND version = $2 AND status = 'pending'
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                settings.SCORER_REGISTERED_MODEL_NAME,
                str(version),
            )
        if not row:
            raise RuntimeError(f"No pending approval request found for version {version}.")
        await conn.execute(
            """
            UPDATE model_approval_requests
            SET status = $1,
                reviewer = $2,
                review_notes = $3,
                reviewed_at = NOW()
            WHERE id = $4
            """,
            target_status,
            actor,
            notes,
            row["id"],
        )
        reviewed = await conn.fetchrow(
            "SELECT * FROM model_approval_requests WHERE id = $1",
            row["id"],
        )
    await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "approval_status", target_status)
    await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "approval_reviewed_at", _utc_now_iso())
    if actor:
        await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(version), "approval_reviewed_by", actor)
    summary = await get_scorer_model_ops_summary()
    summary["approval_review_result"] = {
        "id": str(reviewed["id"]),
        "version": str(version),
        "status": target_status,
        "reviewer": actor,
        "notes": notes,
        "reviewed_at": reviewed["reviewed_at"].isoformat() if reviewed["reviewed_at"] else None,
    }
    return summary


async def promote_registered_model_version(
    version: str,
    stage: str,
    actor: str | None = None,
    notes: str | None = None,
    archive_existing_versions: bool = True,
) -> dict[str, Any]:
    model_name = settings.SCORER_REGISTERED_MODEL_NAME
    if str(stage).lower() == "production":
        await _ensure_version_governance_ready(version, stage)
    await _mlflow_post(
        "/api/2.0/mlflow/model-versions/transition-stage",
        {
            "name": model_name,
            "version": str(version),
            "stage": stage,
            "archive_existing_versions": archive_existing_versions,
        },
    )
    version_tags = {
        "last_promoted_at": _utc_now_iso(),
        "last_promoted_stage": stage,
    }
    if actor:
        version_tags["last_promoted_by"] = actor
    if notes:
        version_tags["promotion_notes"] = notes
    for key, value in version_tags.items():
        await _mlflow_post(
            "/api/2.0/mlflow/model-versions/set-tag",
            {"name": model_name, "version": str(version), "key": key, "value": value},
        )
    summary = await get_scorer_model_ops_summary()
    summary["promotion_result"] = {
        "version": str(version),
        "stage": stage,
        "actor": actor,
        "notes": notes,
        "completed_at": _utc_now_iso(),
    }
    return summary


async def register_current_scorer_model(
    actor: str | None = None,
    description: str | None = None,
    force_bootstrap_if_missing: bool = False,
) -> dict[str, Any]:
    await ensure_registered_model_exists(actor=actor, description=description)
    payload = {
        "registered_model_name": settings.SCORER_REGISTERED_MODEL_NAME,
        "experiment_name": settings.MLFLOW_EXPERIMENT_NAME,
        "actor": actor,
        "description": description,
        "force_bootstrap_if_missing": force_bootstrap_if_missing,
    }
    deploy_result = await _scorer_post("/admin/register-current", payload)
    summary = await get_scorer_model_ops_summary()
    summary["register_result"] = deploy_result
    return summary


async def deploy_scorer_from_registry(
    version: str | None = None,
    stage: str = "Production",
    actor: str | None = None,
    notes: str | None = None,
    reload_after_deploy: bool = True,
    *,
    action: str = "deploy",
) -> dict[str, Any]:
    current_runtime = await fetch_scorer_runtime_metadata()
    if action != "rollback":
        versions = await fetch_registered_model_versions(settings.SCORER_REGISTERED_MODEL_NAME)
        resolved = None
        if version:
            resolved = next((item for item in versions if str(item.get("version")) == str(version)), None)
        elif str(stage).lower() == "production":
            resolved = next((item for item in versions if str(item.get("stage", "")).lower() == "production"), None)
        elif str(stage).lower() == "staging":
            resolved = next((item for item in versions if str(item.get("stage", "")).lower() == "staging"), None)
        if str(stage).lower() == "production":
            if not resolved:
                raise RuntimeError("No Production model version is available to deploy.")
            if str(resolved.get("stage", "")).lower() != "production":
                raise RuntimeError(
                    f"Version {resolved.get('version')} is not in Production. Promote and approve it before deployment."
                )
    payload = {
        "registered_model_name": settings.SCORER_REGISTERED_MODEL_NAME,
        "version": version,
        "stage": stage,
        "actor": actor,
        "notes": notes,
        "reload_after_deploy": reload_after_deploy,
    }
    deploy_result = await _scorer_post("/admin/deploy", payload)
    await _record_deployment_event(
        str(deploy_result.get("version") or version or ""),
        stage=deploy_result.get("stage") or stage,
        action=action,
        actor=actor,
        notes=notes,
        previous_version=current_runtime.get("model_version"),
        previous_stage=current_runtime.get("model_stage"),
        run_id=_coerce_json(deploy_result.get("metadata")).get("run_id") if isinstance(deploy_result.get("metadata"), str) else (deploy_result.get("metadata") or {}).get("run_id"),
        source_uri=_coerce_json(deploy_result.get("metadata")).get("registry_source_uri") if isinstance(deploy_result.get("metadata"), str) else (deploy_result.get("metadata") or {}).get("registry_source_uri"),
        metadata=deploy_result,
    )
    summary = await get_scorer_model_ops_summary()
    summary["deploy_result"] = deploy_result
    return summary


async def rollback_scorer_deployment(
    *,
    target_version: str | None = None,
    actor: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    runtime, versions, governance = await asyncio.gather(
        fetch_scorer_runtime_metadata(),
        fetch_registered_model_versions(settings.SCORER_REGISTERED_MODEL_NAME),
        _governance_records(limit=20),
    )
    _, _, deployments = governance
    current_version = str(runtime.get("model_version") or "").strip() or None
    resolved_target = target_version
    if not resolved_target:
        resolved_target = _rollback_target_version(deployments, current_version)
    if not resolved_target:
        for item in deployments:
            candidate = str(item.get("version") or "").strip()
            if candidate and candidate != current_version:
                resolved_target = candidate
                break
    if not resolved_target:
        for item in versions:
            candidate = str(item.get("version") or "").strip()
            if candidate and candidate != current_version:
                resolved_target = candidate
                break
    if not resolved_target:
        raise RuntimeError("No rollback target version is available.")
    await _mlflow_post(
        "/api/2.0/mlflow/model-versions/transition-stage",
        {
            "name": settings.SCORER_REGISTERED_MODEL_NAME,
            "version": str(resolved_target),
            "stage": "Production",
            "archive_existing_versions": True,
        },
    )
    await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(resolved_target), "rollback_promoted_at", _utc_now_iso())
    if actor:
        await _set_model_version_tag(settings.SCORER_REGISTERED_MODEL_NAME, str(resolved_target), "rollback_promoted_by", actor)
    summary = await deploy_scorer_from_registry(
        version=str(resolved_target),
        stage="Production",
        actor=actor,
        notes=notes or f"Rollback to version {resolved_target}",
        reload_after_deploy=True,
        action="rollback",
    )
    summary["rollback_result"] = {
        "target_version": str(resolved_target),
        "previous_version": current_version,
        "actor": actor,
        "notes": notes,
        "completed_at": _utc_now_iso(),
    }
    return summary


async def fetch_scorer_runtime_metadata() -> dict[str, Any]:
    base = settings.SCORER_URL.rstrip("/")
    metadata_url = f"{base}/metadata"
    health_url = f"{base}/health"
    runtime: dict[str, Any] = {
        "service_url": base,
        "metadata_url": metadata_url,
        "health_url": health_url,
        "reachable": False,
        "health_status": "unknown",
        "metadata_available": False,
        "model_name": settings.SCORER_DEPLOYED_MODEL_NAME,
        "registered_model_name": settings.SCORER_REGISTERED_MODEL_NAME,
        "model_version": None,
        "model_stage": None,
        "model_path": "/models/aml_scorer.json",
        "model_path_exists": None,
        "request_contract": "unknown",
        "scoring_mode": "unknown",
        "warnings": [],
    }
    try:
        async with httpx.AsyncClient(timeout=settings.SCORER_METADATA_TIMEOUT_SECONDS) as client:
            health_response = await client.get(health_url)
            if health_response.is_success:
                runtime["reachable"] = True
                health_payload = health_response.json()
                runtime["health_status"] = health_payload.get("status", "ok")
                runtime["scoring_mode"] = health_payload.get("mode") or runtime["scoring_mode"]
            metadata_response = await client.get(metadata_url)
            if metadata_response.is_success:
                payload = metadata_response.json()
                runtime.update(
                    {
                        "metadata_available": True,
                        "reachable": True,
                        "model_name": payload.get("model_name") or runtime["model_name"],
                        "registered_model_name": payload.get("registered_model_name")
                        or runtime["registered_model_name"],
                        "model_version": payload.get("model_version"),
                        "model_stage": payload.get("model_stage"),
                        "model_path": payload.get("model_path") or runtime["model_path"],
                        "model_path_exists": payload.get("model_path_exists"),
                        "request_contract": payload.get("request_contract") or "unknown",
                        "scoring_mode": payload.get("scoring_mode") or runtime["scoring_mode"],
                        "loaded_at": payload.get("loaded_at"),
                        "admin_capabilities": payload.get("admin_capabilities") or [],
                        "metadata": payload,
                    }
                )
                warnings = payload.get("warnings")
                if isinstance(warnings, list):
                    runtime["warnings"] = [str(item) for item in warnings]
            elif metadata_response.status_code == 404:
                runtime["warnings"].append("The scorer runtime does not yet expose /metadata.")
    except Exception as exc:
        runtime["warnings"].append(f"Could not reach scorer runtime: {str(exc)}")
        return runtime

    if runtime.get("model_path_exists") is False:
        runtime["warnings"].append("The scorer model file is not present on the GPU host.")
    if not runtime.get("model_version"):
        runtime["warnings"].append("The deployed scorer does not currently advertise an MLflow version.")
    return runtime


def _alignment_summary(
    deployed: dict[str, Any],
    versions: list[dict[str, Any]],
) -> tuple[str, list[str], dict[str, Any] | None, dict[str, Any] | None]:
    warnings: list[str] = list(deployed.get("warnings") or [])
    production_version = next(
        (item for item in versions if str(item.get("stage", "")).lower() == "production"),
        None,
    )
    staging_version = next(
        (item for item in versions if str(item.get("stage", "")).lower() == "staging"),
        None,
    )
    if not versions:
        warnings.append("MLflow has no registered scorer versions yet.")
        return "registry_empty", warnings, production_version, staging_version
    if not production_version:
        warnings.append("No scorer version is currently promoted to Production in MLflow.")
        return "no_production_version", warnings, production_version, staging_version
    deployed_version = str(deployed.get("model_version") or "").strip()
    if not deployed_version:
        warnings.append("The deployed scorer version is unknown, so alignment cannot be confirmed.")
        return "deployment_version_unknown", warnings, production_version, staging_version
    if deployed_version == str(production_version.get("version")):
        return "aligned", warnings, production_version, staging_version
    warnings.append(
        f"MLflow Production is version {production_version.get('version')}, but the deployed scorer reports version {deployed_version}."
    )
    return "drift_detected", warnings, production_version, staging_version


async def _recent_scoring_activity(limit: int = 8) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT transaction_ref, risk_score, risk_level, transacted_at, ml_features
            FROM transactions
            ORDER BY transacted_at DESC
            LIMIT $1
            """,
            limit,
        )
    activity: list[dict[str, Any]] = []
    for row in rows:
        ml_features = row.get("ml_features") or {}
        if isinstance(ml_features, str):
            try:
                import json

                ml_features = json.loads(ml_features)
            except Exception:
                ml_features = {}
        scorer_metadata = {}
        if isinstance(ml_features, dict):
            scorer_metadata = ml_features.get("scorer_metadata") or {}
        activity.append(
            {
                "transaction_ref": row.get("transaction_ref"),
                "risk_score": float(row.get("risk_score") or 0.0),
                "risk_level": row.get("risk_level"),
                "transacted_at": row.get("transacted_at").isoformat() if row.get("transacted_at") else None,
                "scoring_mode": scorer_metadata.get("scoring_mode") or "unknown",
                "registered_model_name": scorer_metadata.get("registered_model_name"),
                "model_name": scorer_metadata.get("model_name"),
                "model_version": scorer_metadata.get("model_version"),
                "model_stage": scorer_metadata.get("model_stage"),
            }
        )
    return activity


async def get_scorer_outcome_analytics(days: int = 30) -> dict[str, Any]:
    range_days = max(7, min(180, int(days or 30)))
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            WITH tx AS (
                SELECT
                    t.id,
                    DATE_TRUNC('day', t.transacted_at) AS bucket,
                    COALESCE(t.ml_features->'scorer_metadata'->>'model_version', 'unknown') AS version,
                    COALESCE(t.ml_features->'scorer_metadata'->>'model_stage', 'Unknown') AS stage,
                    t.risk_score
                FROM transactions t
                WHERE t.transacted_at >= NOW() - make_interval(days => $1::int)
            )
            SELECT
                tx.bucket,
                tx.version,
                tx.stage,
                COUNT(*)::int AS score_count,
                ROUND(AVG(tx.risk_score)::numeric, 6) AS avg_score,
                ROUND(AVG(CASE WHEN tx.risk_score >= 0.75 THEN 1 ELSE 0 END)::numeric, 6) AS high_risk_rate,
                ROUND(AVG(CASE WHEN alert_stats.has_alert THEN 1 ELSE 0 END)::numeric, 6) AS alert_rate,
                ROUND(AVG(CASE WHEN case_stats.has_case THEN 1 ELSE 0 END)::numeric, 6) AS case_conversion_rate,
                ROUND(AVG(CASE WHEN alert_stats.is_false_positive THEN 1 ELSE 0 END)::numeric, 6) AS false_positive_rate,
                ROUND(AVG(CASE WHEN alert_stats.is_escalated THEN 1 ELSE 0 END)::numeric, 6) AS escalated_rate,
                ROUND(AVG(CASE WHEN sar_stats.has_sar THEN 1 ELSE 0 END)::numeric, 6) AS sar_conversion_rate
            FROM tx
            LEFT JOIN LATERAL (
                SELECT
                    TRUE AS has_alert,
                    BOOL_OR(a.status = 'false_positive') AS is_false_positive,
                    BOOL_OR(a.status = 'escalated') AS is_escalated
                FROM alerts a
                WHERE a.transaction_id = tx.id
            ) alert_stats ON TRUE
            LEFT JOIN LATERAL (
                SELECT TRUE AS has_case
                FROM alerts a
                JOIN case_alerts ca ON ca.alert_id = a.id
                WHERE a.transaction_id = tx.id
                LIMIT 1
            ) case_stats ON TRUE
            LEFT JOIN LATERAL (
                SELECT TRUE AS has_sar
                FROM alerts a
                JOIN case_alerts ca ON ca.alert_id = a.id
                JOIN sar_reports s ON s.case_id = ca.case_id
                WHERE a.transaction_id = tx.id
                LIMIT 1
            ) sar_stats ON TRUE
            GROUP BY tx.bucket, tx.version, tx.stage
            ORDER BY tx.bucket ASC, tx.version ASC
            """,
            range_days,
        )
        case_rows = await conn.fetch(
            """
            WITH linked AS (
                SELECT
                    c.id AS case_id,
                    c.case_ref,
                    c.status AS case_status,
                    c.priority,
                    c.created_at,
                    c.updated_at,
                    ARRAY_REMOVE(ARRAY_AGG(DISTINCT a.alert_type), NULL) AS alert_types,
                    ARRAY_REMOVE(ARRAY_AGG(DISTINCT COALESCE(t.ml_features->'scorer_metadata'->>'model_version', 'unknown')), NULL) AS model_versions,
                    COUNT(DISTINCT a.id)::int AS alert_count,
                    COALESCE(MAX(s.status::text), '') AS sar_status,
                    COALESCE(MAX(cev.event_count), 0)::int AS event_count
                FROM cases c
                LEFT JOIN case_alerts ca ON ca.case_id = c.id
                LEFT JOIN alerts a ON a.id = ca.alert_id
                LEFT JOIN transactions t ON t.id = a.transaction_id
                LEFT JOIN sar_reports s ON s.case_id = c.id
                LEFT JOIN LATERAL (
                    SELECT COUNT(*)::int AS event_count
                    FROM case_events ce
                    WHERE ce.case_id = c.id
                ) cev ON TRUE
                WHERE c.created_at >= NOW() - make_interval(days => $1::int)
                GROUP BY c.id
            )
            SELECT *
            FROM linked
            """,
            range_days,
        )

    versions = await fetch_registered_model_versions(settings.SCORER_REGISTERED_MODEL_NAME)
    stage_by_version = {str(item.get("version") or ""): item.get("stage") for item in versions}
    version_totals: dict[str, dict[str, Any]] = {}
    trends: list[dict[str, Any]] = []
    total_scores = 0
    total_alert_rate = 0.0
    case_impact: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "case_count": 0,
            "filed_count": 0,
            "cycle_sum": 0.0,
            "cycle_count": 0,
            "event_sum": 0.0,
            "event_count": 0,
            "typologies": Counter(),
        }
    )

    for row in rows:
        bucket = row["bucket"].isoformat() if row["bucket"] else None
        version = str(row["version"] or "unknown")
        stage = row["stage"] or stage_by_version.get(version) or "Unknown"
        point = {
            "bucket": bucket,
            "version": version,
            "score_count": int(row["score_count"] or 0),
            "avg_score": float(row["avg_score"]) if row["avg_score"] is not None else None,
            "alert_rate": float(row["alert_rate"]) if row["alert_rate"] is not None else None,
            "high_risk_rate": float(row["high_risk_rate"]) if row["high_risk_rate"] is not None else None,
            "case_conversion_rate": float(row["case_conversion_rate"]) if row["case_conversion_rate"] is not None else None,
            "sar_conversion_rate": float(row["sar_conversion_rate"]) if row["sar_conversion_rate"] is not None else None,
            "false_positive_rate": float(row["false_positive_rate"]) if row["false_positive_rate"] is not None else None,
            "filed_sar_rate": None,
        }
        trends.append(point)
        stats = version_totals.setdefault(
            version,
            {
                "version": version,
                "stage": stage,
                "score_count": 0,
                "weighted_score_sum": 0.0,
                "weighted_alert_sum": 0.0,
                "weighted_high_sum": 0.0,
                "weighted_case_sum": 0.0,
                "weighted_fp_sum": 0.0,
                "weighted_escalated_sum": 0.0,
                "weighted_sar_sum": 0.0,
                "filed_case_sum": 0.0,
                "cycle_hours_sum": 0.0,
                "cycle_hours_count": 0,
                "event_sum": 0.0,
                "event_count": 0,
                "typologies": Counter(),
            },
        )
        score_count = int(row["score_count"] or 0)
        stats["stage"] = stage
        stats["score_count"] += score_count
        stats["weighted_score_sum"] += float(row["avg_score"] or 0.0) * score_count
        stats["weighted_alert_sum"] += float(row["alert_rate"] or 0.0) * score_count
        stats["weighted_high_sum"] += float(row["high_risk_rate"] or 0.0) * score_count
        stats["weighted_case_sum"] += float(row["case_conversion_rate"] or 0.0) * score_count
        stats["weighted_fp_sum"] += float(row["false_positive_rate"] or 0.0) * score_count
        stats["weighted_escalated_sum"] += float(row["escalated_rate"] or 0.0) * score_count
        stats["weighted_sar_sum"] += float(row["sar_conversion_rate"] or 0.0) * score_count
        total_scores += score_count
        total_alert_rate += float(row["alert_rate"] or 0.0) * score_count

    for row in case_rows:
        model_versions = [str(item or "unknown") for item in (row["model_versions"] or []) if str(item or "").strip()]
        if not model_versions:
            model_versions = ["unknown"]
        created_at = row["created_at"]
        updated_at = row["updated_at"]
        cycle_hours = None
        if created_at and updated_at:
            cycle_hours = max(0.0, round((updated_at - created_at).total_seconds() / 3600.0, 4))
        filed = str(row["case_status"] or "").lower() == "sar_filed" or str(row["sar_status"] or "").lower() == "filed"
        typologies = [str(item or "unknown") for item in (row["alert_types"] or []) if str(item or "").strip()] or ["unknown"]
        for version in model_versions:
            bucket = case_impact[version]
            bucket["case_count"] += 1
            bucket["filed_count"] += 1 if filed else 0
            if cycle_hours is not None:
                bucket["cycle_sum"] += cycle_hours
                bucket["cycle_count"] += 1
            bucket["event_sum"] += float(row["event_count"] or 0)
            bucket["event_count"] += 1
            for typology in typologies:
                bucket["typologies"][typology] += 1

    trend_index: dict[tuple[str, str], dict[str, Any]] = {(str(item["bucket"]), str(item["version"])): item for item in trends if item.get("bucket")}
    for row in case_rows:
        model_versions = [str(item or "unknown") for item in (row["model_versions"] or []) if str(item or "").strip()]
        if not model_versions:
            model_versions = ["unknown"]
        created_at = row["created_at"]
        if not created_at:
            continue
        bucket_key = created_at.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        filed = str(row["case_status"] or "").lower() == "sar_filed" or str(row["sar_status"] or "").lower() == "filed"
        for version in model_versions:
            point = trend_index.get((bucket_key, version))
            if point is None:
                point = {
                    "bucket": bucket_key,
                    "version": version,
                    "score_count": 0,
                    "avg_score": None,
                    "alert_rate": None,
                    "high_risk_rate": None,
                    "case_conversion_rate": None,
                    "sar_conversion_rate": None,
                    "false_positive_rate": None,
                    "filed_sar_rate": None,
                }
                trend_index[(bucket_key, version)] = point
                trends.append(point)
            point["_filed_case_count"] = int(point.get("_filed_case_count") or 0) + (1 if filed else 0)
            point["_case_count"] = int(point.get("_case_count") or 0) + 1

    version_items: list[dict[str, Any]] = []
    for item in version_totals.values():
        count = max(1, int(item["score_count"] or 0))
        case_bucket = case_impact.get(item["version"], {})
        case_count = int(case_bucket.get("case_count") or 0)
        dominant_typology = None
        if case_bucket.get("typologies"):
            dominant_typology = _titleize(case_bucket["typologies"].most_common(1)[0][0])
        version_items.append(
            {
                "version": item["version"],
                "stage": item["stage"],
                "score_count": int(item["score_count"] or 0),
                "avg_score": round(item["weighted_score_sum"] / count, 4) if item["score_count"] else None,
                "high_risk_rate": round(item["weighted_high_sum"] / count, 4) if item["score_count"] else None,
                "alert_rate": round(item["weighted_alert_sum"] / count, 4) if item["score_count"] else None,
                "case_conversion_rate": round(item["weighted_case_sum"] / count, 4) if item["score_count"] else None,
                "false_positive_rate": round(item["weighted_fp_sum"] / count, 4) if item["score_count"] else None,
                "escalated_rate": round(item["weighted_escalated_sum"] / count, 4) if item["score_count"] else None,
                "sar_conversion_rate": round(item["weighted_sar_sum"] / count, 4) if item["score_count"] else None,
                "filed_sar_rate": round((int(case_bucket.get("filed_count") or 0) / max(1, case_count)), 4) if case_count else None,
                "avg_case_cycle_hours": round((float(case_bucket.get("cycle_sum") or 0.0) / max(1, int(case_bucket.get("cycle_count") or 0))), 2) if int(case_bucket.get("cycle_count") or 0) else None,
                "avg_case_event_count": round((float(case_bucket.get("event_sum") or 0.0) / max(1, int(case_bucket.get("event_count") or 0))), 2) if int(case_bucket.get("event_count") or 0) else None,
                "dominant_typology": dominant_typology,
            }
        )
    version_items.sort(
        key=lambda item: (
            0 if str(item.get("stage") or "").lower() == "production" else 1,
            -int(item.get("score_count") or 0),
            -int(item.get("version") or 0) if str(item.get("version") or "").isdigit() else 0,
        )
    )
    summary = [
        f"Tracked scorer outcomes across {len(version_items)} model versions for the last {range_days} days.",
        f"{total_scores} scored transactions are included in the outcome window.",
    ]
    if version_items:
        leader = version_items[0]
        summary.append(
            f"Version {leader['version']} ({leader.get('stage') or 'Unknown'}) handled {leader['score_count']} scored transactions."
        )
    for item in trends:
        case_count = int(item.pop("_case_count", 0) or 0)
        filed_count = int(item.pop("_filed_case_count", 0) or 0)
        item["filed_sar_rate"] = round(filed_count / max(1, case_count), 4) if case_count else None
    trends.sort(key=lambda item: (str(item.get("bucket") or ""), str(item.get("version") or "")))

    impact_summary: list[dict[str, Any]] = []
    if version_items:
        highest_alert = max(version_items, key=lambda item: float(item.get("alert_rate") or 0.0))
        highest_sar = max(version_items, key=lambda item: float(item.get("sar_conversion_rate") or 0.0))
        lowest_fp = min(
            [item for item in version_items if item.get("false_positive_rate") is not None] or version_items,
            key=lambda item: float(item.get("false_positive_rate") or 0.0),
        )
        impact_summary = [
            {
                "key": "highest_alert_capture",
                "title": "Highest alert capture",
                "version": highest_alert.get("version"),
                "stage": highest_alert.get("stage"),
                "metric_value": highest_alert.get("alert_rate"),
                "note": f"{highest_alert.get('score_count', 0)} scored transactions with dominant typology {highest_alert.get('dominant_typology') or 'n/a'}.",
            },
            {
                "key": "best_sar_conversion",
                "title": "Best SAR conversion",
                "version": highest_sar.get("version"),
                "stage": highest_sar.get("stage"),
                "metric_value": highest_sar.get("sar_conversion_rate"),
                "note": f"Filed SAR rate {highest_sar.get('filed_sar_rate') if highest_sar.get('filed_sar_rate') is not None else 'n/a'} with average case cycle {highest_sar.get('avg_case_cycle_hours') if highest_sar.get('avg_case_cycle_hours') is not None else 'n/a'} hours.",
            },
            {
                "key": "lowest_false_positive",
                "title": "Lowest false-positive rate",
                "version": lowest_fp.get("version"),
                "stage": lowest_fp.get("stage"),
                "metric_value": lowest_fp.get("false_positive_rate"),
                "note": f"Average case event count {lowest_fp.get('avg_case_event_count') if lowest_fp.get('avg_case_event_count') is not None else 'n/a'} and dominant typology {lowest_fp.get('dominant_typology') or 'n/a'}.",
            },
        ]

    typology_impact: list[dict[str, Any]] = []
    typology_mix_by_version: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"case_count": 0, "filed_count": 0, "avg_cycle_sum": 0.0, "avg_cycle_count": 0})
    for row in case_rows:
        typologies = [str(item or "unknown") for item in (row["alert_types"] or []) if str(item or "").strip()] or ["unknown"]
        versions_for_row = [str(item or "unknown") for item in (row["model_versions"] or []) if str(item or "").strip()] or ["unknown"]
        filed = str(row["case_status"] or "").lower() == "sar_filed" or str(row["sar_status"] or "").lower() == "filed"
        cycle_hours = None
        if row["created_at"] and row["updated_at"]:
            cycle_hours = max(0.0, round((row["updated_at"] - row["created_at"]).total_seconds() / 3600.0, 4))
        for version in versions_for_row:
            for typology in typologies:
                bucket = typology_mix_by_version[(version, typology)]
                bucket["case_count"] += 1
                bucket["filed_count"] += 1 if filed else 0
                if cycle_hours is not None:
                    bucket["avg_cycle_sum"] += cycle_hours
                    bucket["avg_cycle_count"] += 1
    for (version, typology), item in sorted(typology_mix_by_version.items(), key=lambda pair: pair[1]["case_count"], reverse=True)[:18]:
        typology_impact.append(
            {
                "version": version,
                "typology": typology,
                "display_name": _titleize(typology),
                "case_count": item["case_count"],
                "filed_sar_rate": round(item["filed_count"] / max(1, item["case_count"]), 4) if item["case_count"] else None,
                "avg_case_cycle_hours": round(item["avg_cycle_sum"] / max(1, item["avg_cycle_count"]), 2) if item["avg_cycle_count"] else None,
            }
        )
    return {
        "generated_at": _utc_now_iso(),
        "range_days": range_days,
        "totals": {
            "score_count": total_scores,
            "version_count": len(version_items),
            "avg_alert_rate": round(total_alert_rate / max(1, total_scores), 4) if total_scores else None,
        },
        "versions": version_items,
        "trends": trends,
        "impact_summary": impact_summary,
        "typology_impact": typology_impact,
        "summary": summary,
    }


def _annotate_versions_with_governance(
    versions: list[dict[str, Any]],
    evaluations: list[dict[str, Any]],
    approvals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    evaluation_by_version: dict[str, dict[str, Any]] = {}
    for item in evaluations:
        version = str(item.get("version") or "")
        if version and version not in evaluation_by_version:
            evaluation_by_version[version] = item
    approval_by_version: dict[str, dict[str, Any]] = {}
    for item in approvals:
        version = str(item.get("version") or "")
        if version and version not in approval_by_version:
            approval_by_version[version] = item
    annotated: list[dict[str, Any]] = []
    for item in versions:
        clone = dict(item)
        version = str(item.get("version") or "")
        latest_eval = evaluation_by_version.get(version)
        latest_approval = approval_by_version.get(version)
        promotion_eligible = bool(
            latest_eval
            and str(latest_eval.get("overall_status", "")).lower() == "passed"
            and latest_approval
            and str(latest_approval.get("status", "")).lower() == "approved"
        )
        clone["governance"] = {
            "latest_evaluation": latest_eval,
            "latest_approval": latest_approval,
            "promotion_eligible": promotion_eligible,
        }
        annotated.append(clone)
    return annotated


def _rollback_target_version(
    deployments: list[dict[str, Any]],
    current_version: str | None,
) -> str | None:
    for item in deployments:
        previous_version = str(item.get("previous_version") or "").strip()
        deployed_version = str(item.get("version") or "").strip()
        if previous_version and previous_version != deployed_version:
            return previous_version
    for item in deployments:
        version = str(item.get("version") or "").strip()
        if version and version != current_version:
            return version
    return None


async def get_scorer_model_ops_summary() -> dict[str, Any]:
    registered_model_name = settings.SCORER_REGISTERED_MODEL_NAME
    deployed, registered_model, versions, recent_activity, governance = await asyncio.gather(
        fetch_scorer_runtime_metadata(),
        fetch_registered_model(registered_model_name),
        fetch_registered_model_versions(registered_model_name),
        _recent_scoring_activity(),
        _governance_records(),
    )
    evaluations, approvals, deployments = governance
    versions = sorted(
        versions,
        key=lambda item: (
            0 if str(item.get("stage", "")).lower() == "production" else 1,
            0 if str(item.get("stage", "")).lower() == "staging" else 1,
            -int(item.get("version") or 0) if str(item.get("version") or "").isdigit() else 0,
        ),
    )
    versions = _annotate_versions_with_governance(versions, evaluations, approvals)
    alignment, warnings, production_version, staging_version = _alignment_summary(deployed, versions)
    scorer_modes = {}
    for item in recent_activity:
        mode = str(item.get("scoring_mode") or "unknown")
        scorer_modes[mode] = scorer_modes.get(mode, 0) + 1
    pending_approvals = [item for item in approvals if str(item.get("status", "")).lower() == "pending"]
    current_version = str(deployed.get("model_version") or "").strip() or None
    rollback_target = _rollback_target_version(deployments, current_version)
    return {
        "generated_at": _utc_now_iso(),
        "registered_model_name": registered_model_name,
        "mlflow_tracking_uri": settings.MLFLOW_TRACKING_URI,
        "mlflow_public_url": settings.MLFLOW_PUBLIC_URL,
        "deployed_scorer": deployed,
        "registry": {
            "exists": registered_model is not None,
            "name": registered_model_name,
            "description": registered_model.get("description") if registered_model else None,
            "tags": registered_model.get("tags") if registered_model else {},
            "created_at": registered_model.get("created_at") if registered_model else None,
            "updated_at": registered_model.get("updated_at") if registered_model else None,
        },
        "versions": versions,
        "recent_scoring_activity": recent_activity,
        "governance": {
            "thresholds": _default_eval_thresholds(),
            "latest_evaluations": evaluations,
            "approval_history": approvals,
            "deployment_history": deployments,
            "pending_approvals": pending_approvals,
            "rollback_target_version": rollback_target,
        },
        "summary": {
            "version_count": len(versions),
            "production_version": production_version,
            "staging_version": staging_version,
            "deployment_alignment": alignment,
            "warnings": warnings,
            "can_promote": len(versions) > 0,
            "recent_scoring_modes": scorer_modes,
            "pending_approval_count": len(pending_approvals),
            "rollback_target_version": rollback_target,
        },
    }
