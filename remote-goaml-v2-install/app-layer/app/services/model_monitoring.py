"""
Champion/challenger and drift monitoring for the MLflow-managed scorer.
"""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from core.config import settings
from core.database import get_pool
from services.model_registry import fetch_registered_model_versions


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


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


def _mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def _median(values: list[float]) -> float:
    return float(statistics.median(values)) if values else 0.0


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * max(0.0, min(1.0, percentile))
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return float(ordered[lower])
    weight = rank - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_datetime(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _bounded_int(value: int, *, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


async def _scorer_compare_models(payload: dict[str, Any]) -> dict[str, Any]:
    base = settings.SCORER_URL.rstrip("/")
    async with httpx.AsyncClient(timeout=settings.SCORER_ADMIN_TIMEOUT_SECONDS) as client:
        response = await client.post(f"{base}/admin/champion-challenger", json=payload)
    response.raise_for_status()
    return response.json()


def _vector_from_features(feature_payload: dict[str, Any]) -> list[float] | None:
    if not isinstance(feature_payload, dict):
        return None
    amount_usd = _safe_float(feature_payload.get("amount_usd"), default=None)
    if amount_usd is None:
        return None
    is_international = _safe_float(feature_payload.get("is_international"))
    is_cash = _safe_float(feature_payload.get("is_cash"))
    is_crypto = _safe_float(feature_payload.get("is_crypto"))
    hour_of_day = _safe_float(feature_payload.get("hour_of_day"))
    day_of_week = _safe_float(feature_payload.get("day_of_week"))
    sender_country = str(feature_payload.get("sender_country") or "").upper()
    receiver_country = str(feature_payload.get("receiver_country") or "").upper()
    country_pair_diff = 1.0 if sender_country and receiver_country and sender_country != receiver_country else is_international
    return [
        float(amount_usd),
        float(is_international),
        float(is_cash),
        float(is_crypto),
        float(hour_of_day),
        float(day_of_week),
        float(country_pair_diff),
    ]


async def _recent_transaction_sample(
    *,
    sample_size: int,
    lookback_hours: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sample_size = _bounded_int(
        sample_size,
        minimum=25,
        maximum=settings.SCORER_MONITORING_MAX_SAMPLE_SIZE,
    )
    lookback_hours = max(1, int(lookback_hours))
    cutoff = _utc_now() - timedelta(hours=lookback_hours)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, transaction_ref, risk_score, risk_level, transacted_at, ml_features
            FROM transactions
            WHERE transacted_at >= $1
              AND ml_features IS NOT NULL
              AND ml_features ? 'amount_usd'
              AND ml_features ? 'sender_country'
              AND ml_features ? 'receiver_country'
            ORDER BY transacted_at DESC
            LIMIT $2
            """,
            cutoff,
            sample_size,
        )

    sample: list[dict[str, Any]] = []
    timestamps: list[datetime] = []
    for row in rows:
        feature_payload = _coerce_json(row["ml_features"])
        vector = _vector_from_features(feature_payload)
        if not vector:
            continue
        transacted_at = row["transacted_at"]
        if transacted_at:
            timestamps.append(transacted_at)
        sample.append(
            {
                "transaction_id": str(row["id"]),
                "transaction_ref": row["transaction_ref"],
                "features": feature_payload,
                "vector": vector,
                "persisted_score": _safe_float(row["risk_score"]),
                "persisted_risk_level": row["risk_level"],
                "transacted_at": transacted_at.isoformat() if transacted_at else None,
            }
        )

    window = {
        "requested_hours": lookback_hours,
        "requested_sample_size": sample_size,
        "window_start": min(timestamps).isoformat() if timestamps else cutoff.isoformat(),
        "window_end": max(timestamps).isoformat() if timestamps else _utc_now_iso(),
        "sample_size": len(sample),
    }
    if len(sample) < 25:
        raise RuntimeError(
            "Not enough recent transactions with scorer features are available for monitoring. "
            "Try a larger lookback window after more traffic is ingested."
        )
    return sample, window


def _sort_versions(versions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def _stage_rank(item: dict[str, Any]) -> int:
        stage = str(item.get("stage", "")).lower()
        if stage == "production":
            return 0
        if stage == "staging":
            return 1
        return 2

    def _version_rank(item: dict[str, Any]) -> int:
        version = str(item.get("version") or "")
        return int(version) if version.isdigit() else -1

    return sorted(versions, key=lambda item: (_stage_rank(item), -_version_rank(item)))


async def _resolve_monitoring_versions(
    *,
    champion_version: str | None = None,
    challenger_version: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    versions = _sort_versions(await fetch_registered_model_versions(settings.SCORER_REGISTERED_MODEL_NAME))
    if not versions:
        raise RuntimeError("No MLflow scorer versions are available for monitoring.")

    champion = None
    if champion_version:
        champion = next((item for item in versions if str(item.get("version")) == str(champion_version)), None)
    if champion is None:
        champion = next((item for item in versions if str(item.get("stage", "")).lower() == "production"), None)
    if champion is None:
        champion = versions[0]

    challenger = None
    if challenger_version:
        challenger = next((item for item in versions if str(item.get("version")) == str(challenger_version)), None)
        if challenger is None:
            raise RuntimeError(f"Could not find challenger version {challenger_version} in MLflow.")
    else:
        staging = next(
            (
                item
                for item in versions
                if str(item.get("stage", "")).lower() == "staging"
                and str(item.get("version")) != str(champion.get("version"))
            ),
            None,
        )
        challenger = staging or next(
            (item for item in versions if str(item.get("version")) != str(champion.get("version"))),
            None,
        )
    if challenger is None:
        raise RuntimeError("No challenger version is available. Register another scorer version first.")
    if str(challenger.get("version")) == str(champion.get("version")):
        raise RuntimeError("Champion and challenger versions must be different.")
    return champion, challenger, versions


async def _record_monitoring_snapshot(
    *,
    snapshot_type: str,
    primary_version: str | None,
    secondary_version: str | None,
    actor: str | None,
    status: str,
    sample_size: int,
    window_start: str | None,
    window_end: str | None,
    summary: dict[str, Any],
    metrics: dict[str, Any],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO model_monitoring_snapshots (
                registered_model_name,
                snapshot_type,
                primary_version,
                secondary_version,
                actor,
                status,
                sample_size,
                window_start,
                window_end,
                summary,
                metrics,
                metadata
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11::jsonb,$12::jsonb)
            RETURNING id, created_at
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            snapshot_type,
            primary_version,
            secondary_version,
            actor,
            status,
            sample_size,
            _as_datetime(window_start),
            _as_datetime(window_end),
            json.dumps(summary),
            json.dumps(metrics),
            json.dumps(metadata),
        )
    return {
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


def _bucketize(values: list[float], edges: list[float]) -> list[float]:
    if not values:
        return [0.0 for _ in range(len(edges) - 1)]
    counts = [0 for _ in range(len(edges) - 1)]
    for value in values:
        placed = False
        for index in range(len(edges) - 1):
            lower = edges[index]
            upper = edges[index + 1]
            upper_inclusive = index == len(edges) - 2
            if value >= lower and (value < upper or (upper_inclusive and value <= upper)):
                counts[index] += 1
                placed = True
                break
        if not placed and counts:
            counts[-1] += 1
    total = float(len(values))
    return [count / total for count in counts]


def _population_stability_index(current: list[float], baseline: list[float]) -> float:
    psi = 0.0
    for current_ratio, baseline_ratio in zip(current, baseline):
        current_ratio = max(current_ratio, 1e-6)
        baseline_ratio = max(baseline_ratio, 1e-6)
        psi += (current_ratio - baseline_ratio) * math.log(current_ratio / baseline_ratio)
    return float(round(psi, 6))


def _distribution_snapshot(
    sample: list[dict[str, Any]],
    *,
    score_values: list[float] | None = None,
) -> dict[str, Any]:
    amounts = [_safe_float(item["features"].get("amount_usd")) for item in sample]
    scores = score_values if score_values is not None else [_safe_float(item.get("persisted_score")) for item in sample]
    feature_flags = {
        "international_rate": _mean([_safe_float(item["features"].get("is_international")) for item in sample]),
        "cash_rate": _mean([_safe_float(item["features"].get("is_cash")) for item in sample]),
        "crypto_rate": _mean([_safe_float(item["features"].get("is_crypto")) for item in sample]),
        "odd_hour_rate": _mean([1.0 if _safe_float(item["features"].get("hour_of_day")) < 5 else 0.0 for item in sample]),
    }
    risk_rates = {
        "medium_or_higher_rate": _mean([1.0 if score >= 0.45 else 0.0 for score in scores]),
        "high_risk_rate": _mean([1.0 if score >= 0.75 else 0.0 for score in scores]),
    }
    amount_edges = [0.0, 1000.0, 5000.0, 10000.0, 25000.0, 50000.0, 100000.0, 1_000_000_000.0]
    score_edges = [0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 1.01]
    return {
        "sample_size": len(sample),
        "amount_usd": {
            "mean": round(_mean(amounts), 6),
            "median": round(_median(amounts), 6),
            "p95": round(_percentile(amounts, 0.95), 6),
            "distribution": _bucketize(amounts, amount_edges),
            "bucket_edges": amount_edges,
        },
        "score": {
            "mean": round(_mean(scores), 6),
            "median": round(_median(scores), 6),
            "p95": round(_percentile(scores, 0.95), 6),
            "distribution": _bucketize(scores, score_edges),
            "bucket_edges": score_edges,
        },
        "feature_rates": {key: round(value, 6) for key, value in feature_flags.items()},
        "risk_rates": {key: round(value, 6) for key, value in risk_rates.items()},
    }


def _drift_severity(
    *,
    amount_psi: float,
    score_psi: float,
    max_rate_delta: float,
) -> tuple[str, str]:
    if (
        amount_psi >= settings.SCORER_DRIFT_PSI_CRITICAL
        or score_psi >= settings.SCORER_DRIFT_PSI_CRITICAL
        or max_rate_delta >= settings.SCORER_DRIFT_RATE_CRITICAL
    ):
        return "critical", "critical"
    if (
        amount_psi >= settings.SCORER_DRIFT_PSI_WARNING
        or score_psi >= settings.SCORER_DRIFT_PSI_WARNING
        or max_rate_delta >= settings.SCORER_DRIFT_RATE_WARNING
    ):
        return "warning", "warning"
    return "stable", "completed"


async def evaluate_scorer_challenger(
    *,
    challenger_version: str | None = None,
    champion_version: str | None = None,
    actor: str | None = None,
    sample_size: int | None = None,
    lookback_hours: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    champion, challenger, _ = await _resolve_monitoring_versions(
        champion_version=champion_version,
        challenger_version=challenger_version,
    )
    sample, window = await _recent_transaction_sample(
        sample_size=sample_size or settings.SCORER_MONITORING_DEFAULT_SAMPLE_SIZE,
        lookback_hours=lookback_hours or settings.SCORER_MONITORING_DEFAULT_LOOKBACK_HOURS,
    )
    comparison = await _scorer_compare_models(
        {
            "registered_model_name": settings.SCORER_REGISTERED_MODEL_NAME,
            "champion_version": str(champion.get("version") or ""),
            "challenger_version": str(challenger.get("version") or ""),
            "actor": actor,
            "feature_rows": [item["vector"] for item in sample],
            "transactions": [
                {
                    "transaction_ref": item["transaction_ref"],
                    "transacted_at": item["transacted_at"],
                    "persisted_score": item["persisted_score"],
                    "persisted_risk_level": item["persisted_risk_level"],
                }
                for item in sample
            ],
            "notes": notes,
            "sample_window": window,
        }
    )
    summary = _coerce_json(comparison.get("summary"))
    metrics = _coerce_json(comparison.get("metrics"))
    sample_count = int(summary.get("sample_size") or len(sample))
    snapshot = await _record_monitoring_snapshot(
        snapshot_type="champion_challenger",
        primary_version=str(challenger.get("version") or ""),
        secondary_version=str(champion.get("version") or ""),
        actor=actor,
        status="completed",
        sample_size=sample_count,
        window_start=summary.get("window_start") or window["window_start"],
        window_end=summary.get("window_end") or window["window_end"],
        summary=summary,
        metrics=metrics,
        metadata={
            "notes": notes,
            "window": window,
            "comparison": comparison,
        },
    )
    monitoring = await get_scorer_monitoring_summary()
    monitoring["challenger_evaluation_result"] = {
        **summary,
        "id": snapshot["id"],
        "created_at": snapshot["created_at"],
    }
    return monitoring


async def _latest_snapshot(snapshot_type: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM model_monitoring_snapshots
            WHERE registered_model_name = $1 AND snapshot_type = $2
            ORDER BY created_at DESC
            LIMIT 1
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            snapshot_type,
        )
    if not row:
        return None
    return {
        "id": str(row["id"]),
        "snapshot_type": row["snapshot_type"],
        "primary_version": row["primary_version"],
        "secondary_version": row["secondary_version"],
        "actor": row["actor"],
        "status": row["status"],
        "sample_size": row["sample_size"],
        "window_start": row["window_start"].isoformat() if row["window_start"] else None,
        "window_end": row["window_end"].isoformat() if row["window_end"] else None,
        "summary": _coerce_json(row["summary"]),
        "metrics": _coerce_json(row["metrics"]),
        "metadata": _coerce_json(row["metadata"]),
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
    }


async def capture_scorer_drift_snapshot(
    *,
    actor: str | None = None,
    sample_size: int | None = None,
    lookback_hours: int | None = None,
    notes: str | None = None,
    reset_baseline: bool = False,
) -> dict[str, Any]:
    versions = _sort_versions(await fetch_registered_model_versions(settings.SCORER_REGISTERED_MODEL_NAME))
    production = next((item for item in versions if str(item.get("stage", "")).lower() == "production"), None)
    current_version = str(production.get("version") or "") if production else None
    sample, window = await _recent_transaction_sample(
        sample_size=sample_size or settings.SCORER_MONITORING_DEFAULT_SAMPLE_SIZE,
        lookback_hours=lookback_hours or settings.SCORER_MONITORING_DEFAULT_LOOKBACK_HOURS,
    )
    current_distribution = _distribution_snapshot(sample)

    baseline_snapshot = None if reset_baseline else await _latest_snapshot("drift_baseline")
    if not baseline_snapshot:
        summary = {
            "status": "baseline_initialized",
            "severity": "baseline",
            "model_version": current_version,
            "sample_size": len(sample),
            "window_start": window["window_start"],
            "window_end": window["window_end"],
            "notes": notes,
        }
        snapshot = await _record_monitoring_snapshot(
            snapshot_type="drift_baseline",
            primary_version=current_version,
            secondary_version=None,
            actor=actor,
            status="baseline",
            sample_size=len(sample),
            window_start=window["window_start"],
            window_end=window["window_end"],
            summary=summary,
            metrics=current_distribution,
            metadata={"notes": notes, "window": window},
        )
        monitoring = await get_scorer_monitoring_summary()
        monitoring["drift_capture_result"] = {
            **summary,
            "id": snapshot["id"],
            "created_at": snapshot["created_at"],
            "baseline_snapshot_id": snapshot["id"],
        }
        return monitoring

    baseline_metrics = baseline_snapshot.get("metrics") or {}
    amount_psi = _population_stability_index(
        current_distribution["amount_usd"]["distribution"],
        baseline_metrics.get("amount_usd", {}).get("distribution") or current_distribution["amount_usd"]["distribution"],
    )
    score_psi = _population_stability_index(
        current_distribution["score"]["distribution"],
        baseline_metrics.get("score", {}).get("distribution") or current_distribution["score"]["distribution"],
    )
    current_rates = {
        **current_distribution.get("feature_rates", {}),
        **current_distribution.get("risk_rates", {}),
    }
    baseline_rates = {
        **(baseline_metrics.get("feature_rates") or {}),
        **(baseline_metrics.get("risk_rates") or {}),
    }
    rate_deltas = {
        key: round(current_rates.get(key, 0.0) - baseline_rates.get(key, 0.0), 6)
        for key in sorted(set(current_rates) | set(baseline_rates))
    }
    max_rate_delta = max((abs(value) for value in rate_deltas.values()), default=0.0)
    severity, status = _drift_severity(
        amount_psi=amount_psi,
        score_psi=score_psi,
        max_rate_delta=max_rate_delta,
    )
    summary = {
        "status": status,
        "severity": severity,
        "model_version": current_version,
        "baseline_snapshot_id": baseline_snapshot["id"],
        "baseline_created_at": baseline_snapshot["created_at"],
        "baseline_version": baseline_snapshot.get("primary_version"),
        "sample_size": len(sample),
        "window_start": window["window_start"],
        "window_end": window["window_end"],
        "amount_psi": round(amount_psi, 6),
        "score_psi": round(score_psi, 6),
        "max_rate_delta": round(max_rate_delta, 6),
        "notes": notes,
    }
    metrics = {
        "current": current_distribution,
        "baseline": baseline_metrics,
        "rate_deltas": rate_deltas,
        "psi": {
            "amount_usd": round(amount_psi, 6),
            "score": round(score_psi, 6),
        },
    }
    snapshot = await _record_monitoring_snapshot(
        snapshot_type="drift_observation",
        primary_version=current_version,
        secondary_version=baseline_snapshot.get("primary_version"),
        actor=actor,
        status=status,
        sample_size=len(sample),
        window_start=window["window_start"],
        window_end=window["window_end"],
        summary=summary,
        metrics=metrics,
        metadata={
            "notes": notes,
            "window": window,
            "baseline_snapshot_id": baseline_snapshot["id"],
        },
    )
    monitoring = await get_scorer_monitoring_summary()
    monitoring["drift_capture_result"] = {
        **summary,
        "id": snapshot["id"],
        "created_at": snapshot["created_at"],
    }
    return monitoring


async def get_scorer_monitoring_summary(limit: int = 8) -> dict[str, Any]:
    versions = _sort_versions(await fetch_registered_model_versions(settings.SCORER_REGISTERED_MODEL_NAME))
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM model_monitoring_snapshots
            WHERE registered_model_name = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            settings.SCORER_REGISTERED_MODEL_NAME,
            limit * 3,
        )
    snapshots = [
        {
            "id": str(row["id"]),
            "snapshot_type": row["snapshot_type"],
            "primary_version": row["primary_version"],
            "secondary_version": row["secondary_version"],
            "actor": row["actor"],
            "status": row["status"],
            "sample_size": row["sample_size"],
            "window_start": row["window_start"].isoformat() if row["window_start"] else None,
            "window_end": row["window_end"].isoformat() if row["window_end"] else None,
            "summary": _coerce_json(row["summary"]),
            "metrics": _coerce_json(row["metrics"]),
            "metadata": _coerce_json(row["metadata"]),
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        }
        for row in rows
    ]
    challenger_history = [item for item in snapshots if item["snapshot_type"] == "champion_challenger"][:limit]
    drift_history = [item for item in snapshots if item["snapshot_type"] == "drift_observation"][:limit]
    drift_baseline = next((item for item in snapshots if item["snapshot_type"] == "drift_baseline"), None)
    latest_challenger = challenger_history[0] if challenger_history else None
    latest_drift = drift_history[0] if drift_history else None
    candidate_versions = [
        {
            "version": item.get("version"),
            "stage": item.get("stage"),
            "status": item.get("status"),
        }
        for item in versions
        if str(item.get("stage", "")).lower() != "production"
    ]
    return {
        "generated_at": _utc_now_iso(),
        "registered_model_name": settings.SCORER_REGISTERED_MODEL_NAME,
        "candidate_versions": candidate_versions,
        "champion_challenger_history": challenger_history,
        "latest_champion_challenger": latest_challenger,
        "drift_history": drift_history,
        "latest_drift": latest_drift,
        "drift_baseline": drift_baseline,
        "summary": {
            "latest_challenger_disagreement_rate": latest_challenger.get("summary", {}).get("disagreement_rate")
            if latest_challenger
            else None,
            "latest_mean_abs_delta": latest_challenger.get("summary", {}).get("mean_abs_delta")
            if latest_challenger
            else None,
            "latest_drift_severity": latest_drift.get("summary", {}).get("severity") if latest_drift else None,
            "latest_drift_status": latest_drift.get("summary", {}).get("status") if latest_drift else None,
            "baseline_version": drift_baseline.get("primary_version") if drift_baseline else None,
            "has_baseline": drift_baseline is not None,
        },
    }
