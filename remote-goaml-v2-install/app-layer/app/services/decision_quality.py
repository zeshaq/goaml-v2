"""
Decision-quality analytics and closed-loop feedback capture.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from core.database import get_pool


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _safe_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


def _hours_between(start: datetime | None, end: datetime | None) -> float | None:
    if not start or not end:
        return None
    return max(0.0, round((end - start).total_seconds() / 3600.0, 2))


def _period_bounds(granularity: str, reference: datetime | None = None) -> tuple[datetime, datetime, str]:
    ref = (reference or _utcnow()).astimezone(timezone.utc)
    key = str(granularity or "daily").lower()
    if key == "monthly":
        start = ref.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start.month == 12:
            next_start = start.replace(year=start.year + 1, month=1)
        else:
            next_start = start.replace(month=start.month + 1)
        end = next_start - timedelta(microseconds=1)
        label = start.strftime("%Y-%m")
        return start, end, label
    if key == "weekly":
        start = (ref - timedelta(days=ref.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=7) - timedelta(microseconds=1)
        label = f"{start.strftime('%Y-%m-%d')} to {(start + timedelta(days=6)).strftime('%Y-%m-%d')}"
        return start, end, label
    start = ref.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1) - timedelta(microseconds=1)
    label = start.strftime("%Y-%m-%d")
    return start, end, label


def _titleize(value: str) -> str:
    return str(value or "").replace("_", " ").title()


FEEDBACK_DEFINITIONS: dict[str, dict[str, Any]] = {
    "good_alert": {
        "label": "Good alert",
        "sentiment": "positive",
        "rating": 1,
        "summary": "Alert was considered useful and relevant.",
    },
    "noisy_alert": {
        "label": "Noisy alert",
        "sentiment": "negative",
        "rating": -1,
        "summary": "Alert was considered noisy or low-value.",
    },
    "weak_sar_draft": {
        "label": "Weak SAR draft",
        "sentiment": "negative",
        "rating": -1,
        "summary": "SAR draft quality needs improvement before review.",
    },
    "missing_evidence": {
        "label": "Missing evidence",
        "sentiment": "negative",
        "rating": -1,
        "summary": "Case lacked required evidence at the decision point.",
    },
    "strong_evidence": {
        "label": "Strong evidence",
        "sentiment": "positive",
        "rating": 1,
        "summary": "Evidence pack was strong and supported the decision well.",
    },
    "high_quality_case": {
        "label": "High-quality case",
        "sentiment": "positive",
        "rating": 1,
        "summary": "Investigation quality was strong and decision-ready.",
    },
}


def _normalize_feedback_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["metadata"] = _normalize_json_dict(item.get("metadata"))
    created = item.get("created_at")
    if isinstance(created, datetime) and not created.tzinfo:
        item["created_at"] = created.replace(tzinfo=timezone.utc)
    return item


async def list_decision_feedback(subject_type: str, subject_id: UUID, *, limit: int = 20) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM decision_feedback
            WHERE subject_type = $1 AND subject_id = $2
            ORDER BY created_at DESC
            LIMIT $3
            """,
            subject_type,
            subject_id,
            limit,
        )
    return [_normalize_feedback_row(dict(row)) for row in rows]


async def record_decision_feedback(
    *,
    subject_type: str,
    subject_id: UUID,
    actor: str,
    actor_role: str | None,
    feedback_key: str,
    note: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    definition = FEEDBACK_DEFINITIONS.get(str(feedback_key or "").strip().lower())
    if not definition:
        raise ValueError("Unsupported feedback key")

    pool = get_pool()
    metadata = dict(metadata or {})
    subject_type = str(subject_type or "").strip().lower()
    if subject_type not in {"case", "alert"}:
        raise ValueError("Unsupported feedback subject")

    async with pool.acquire() as conn:
        async with conn.transaction():
            case_id: UUID | None = None
            alert_id: UUID | None = None
            detail_text = definition["summary"]
            if subject_type == "case":
                case_row = await conn.fetchrow(
                    "SELECT id, case_ref FROM cases WHERE id = $1 FOR UPDATE",
                    subject_id,
                )
                if not case_row:
                    raise ValueError("Case not found")
                case_id = UUID(str(case_row["id"]))
                detail_text = f"{definition['label']} recorded for {case_row['case_ref']}."
            else:
                alert_row = await conn.fetchrow(
                    """
                    SELECT id, alert_ref, case_id
                    FROM alerts
                    WHERE id = $1
                    FOR UPDATE
                    """,
                    subject_id,
                )
                if not alert_row:
                    raise ValueError("Alert not found")
                alert_id = UUID(str(alert_row["id"]))
                case_id = UUID(str(alert_row["case_id"])) if alert_row["case_id"] else None
                detail_text = f"{definition['label']} recorded for {alert_row['alert_ref']}."

            row = await conn.fetchrow(
                """
                INSERT INTO decision_feedback (
                    subject_type,
                    subject_id,
                    case_id,
                    alert_id,
                    actor,
                    actor_role,
                    feedback_key,
                    label,
                    sentiment,
                    rating,
                    note,
                    metadata
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb
                )
                RETURNING *
                """,
                subject_type,
                subject_id,
                case_id,
                alert_id,
                actor,
                actor_role,
                feedback_key,
                definition["label"],
                definition["sentiment"],
                int(definition["rating"]),
                note,
                json.dumps(metadata),
            )

            if case_id:
                await conn.execute(
                    """
                    INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                    VALUES ($1, 'decision_feedback_added', $2, $3, $4::jsonb)
                    """,
                    case_id,
                    actor,
                    detail_text,
                    json.dumps(
                        {
                            "subject_type": subject_type,
                            "subject_id": str(subject_id),
                            "feedback_key": feedback_key,
                            "label": definition["label"],
                            "sentiment": definition["sentiment"],
                        }
                    ),
                )

    return _normalize_feedback_row(dict(row))


async def get_decision_quality_analytics(*, range_days: int = 180) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        case_rows = await conn.fetch(
            """
            SELECT
                c.id,
                c.case_ref,
                c.status,
                c.priority,
                c.assigned_to,
                c.created_at,
                c.updated_at,
                c.metadata,
                s.status::text AS sar_status,
                s.drafted_by,
                s.drafted_at,
                s.reviewed_by,
                s.reviewed_at,
                s.approved_by,
                s.approved_at,
                s.filed_at,
                COALESCE(ce.evidence_count, 0) AS evidence_count,
                COALESCE(ce.included_evidence_count, 0) AS included_evidence_count,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT a.alert_type), NULL) AS alert_types,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT COALESCE(t.ml_features->'scorer_metadata'->>'model_version', 'unknown')), NULL) AS model_versions
            FROM cases c
            LEFT JOIN sar_reports s ON s.case_id = c.id
            LEFT JOIN case_alerts ca ON ca.case_id = c.id
            LEFT JOIN alerts a ON a.id = ca.alert_id
            LEFT JOIN transactions t ON t.id = a.transaction_id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) AS evidence_count,
                    COUNT(*) FILTER (WHERE include_in_sar = TRUE) AS included_evidence_count
                FROM case_evidence cex
                WHERE cex.case_id = c.id
            ) ce ON TRUE
            WHERE c.created_at >= NOW() - make_interval(days => $1::int)
            GROUP BY c.id, s.id, ce.evidence_count, ce.included_evidence_count
            ORDER BY c.created_at DESC
            """,
            range_days,
        )
        alert_rows = await conn.fetch(
            """
            SELECT
                a.id,
                a.alert_ref,
                a.alert_type,
                a.status,
                a.created_at,
                a.case_id,
                a.metadata,
                COALESCE(t.ml_features->'scorer_metadata'->>'model_version', 'unknown') AS model_version
            FROM alerts a
            LEFT JOIN transactions t ON t.id = a.transaction_id
            WHERE a.created_at >= NOW() - make_interval(days => $1::int)
            ORDER BY a.created_at DESC
            """,
            range_days,
        )
        feedback_rows = await conn.fetch(
            """
            SELECT *
            FROM decision_feedback
            WHERE created_at >= NOW() - make_interval(days => $1::int)
            ORDER BY created_at DESC
            """,
            range_days,
        )

    alert_feedback = defaultdict(list)
    case_feedback = defaultdict(list)
    feedback_by_key = Counter()
    for row in feedback_rows:
        item = _normalize_feedback_row(dict(row))
        feedback_by_key[str(item.get("feedback_key") or "unknown")] += 1
        if item.get("alert_id"):
            alert_feedback[str(item["alert_id"])].append(item)
        if item.get("case_id"):
            case_feedback[str(item["case_id"])].append(item)

    precision_stats: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "good": 0, "noisy": 0, "false_positive": 0})
    for row in alert_rows:
        item = dict(row)
        typology = str(item.get("alert_type") or "unknown")
        stats = precision_stats[typology]
        stats["count"] += 1
        if str(item.get("status") or "").lower() == "false_positive":
            stats["false_positive"] += 1
        for feedback in alert_feedback.get(str(item["id"]), []):
            key = str(feedback.get("feedback_key") or "")
            if key == "good_alert":
                stats["good"] += 1
            elif key == "noisy_alert":
                stats["noisy"] += 1

    alert_precision_by_typology = []
    for typology, stats in sorted(precision_stats.items(), key=lambda pair: pair[1]["count"], reverse=True)[:8]:
        metric = _rate(stats["good"] + max(0, stats["count"] - stats["false_positive"] - stats["noisy"]), stats["count"])
        alert_precision_by_typology.append(
            {
                "scope_key": typology,
                "scope_label": _titleize(typology),
                "metric": metric,
                "count": stats["count"],
                "secondary_metric": _rate(stats["false_positive"] + stats["noisy"], stats["count"]),
                "note": f"{stats['good']} positive and {stats['false_positive'] + stats['noisy']} noisy/false-positive signals.",
            }
        )

    escalation_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "filed": 0, "weak": 0, "missing": 0, "strong": 0, "cycle_sum": 0.0, "cycle_count": 0}
    )
    drafter_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"drafted": 0, "rejected": 0, "rework": 0, "evidence_complete": 0, "review_lag_sum": 0.0, "review_lag_count": 0}
    )
    team_approval_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "lag_sum": 0.0, "lag_count": 0, "filed": 0}
    )
    typology_approval_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "lag_sum": 0.0, "lag_count": 0, "filed": 0}
    )
    model_trends: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"count": 0, "positive": 0, "false_positive": 0, "filed": 0})
    workflow_trends: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"count": 0, "positive": 0, "false_positive": 0, "filed": 0})
    for row in case_rows:
        item = dict(row)
        metadata = _normalize_json_dict(item.get("metadata"))
        playbook = _normalize_json_dict(metadata.get("playbook"))
        typology = str(playbook.get("typology") or metadata.get("typology") or ((item.get("alert_types") or [None])[0] or "unknown"))
        team_key = str(_normalize_json_dict(metadata.get("routing")).get("team_key") or metadata.get("team_key") or "unassigned_team")
        stats = escalation_stats[typology]
        stats["count"] += 1
        filed = str(item.get("status") or "").lower() == "sar_filed" or str(item.get("sar_status") or "").lower() == "filed"
        if filed:
            stats["filed"] += 1
        created_at = _safe_datetime(item.get("created_at"))
        updated_at = _safe_datetime(item.get("updated_at"))
        drafted_at = _safe_datetime(item.get("drafted_at"))
        reviewed_at = _safe_datetime(item.get("reviewed_at"))
        approved_at = _safe_datetime(item.get("approved_at"))
        filed_at = _safe_datetime(item.get("filed_at"))
        review_lag_hours = _hours_between(drafted_at or created_at, reviewed_at)
        filing_lag_hours = _hours_between(approved_at or reviewed_at or drafted_at or created_at, filed_at)
        evidence_count = int(item.get("evidence_count") or 0)
        included_evidence_count = int(item.get("included_evidence_count") or 0)
        required_evidence_min = 2 if filed or str(item.get("sar_status") or "").lower() in {"draft", "pending_review", "approved", "filed", "rejected"} else 1
        if created_at and updated_at:
            stats["cycle_sum"] += max(0.0, (updated_at - created_at).total_seconds() / 3600.0)
            stats["cycle_count"] += 1
        case_id_key = str(item["id"])
        feedback_items = case_feedback.get(case_id_key, [])
        for feedback in feedback_items:
            key = str(feedback.get("feedback_key") or "")
            if key == "weak_sar_draft":
                stats["weak"] += 1
            elif key == "missing_evidence":
                stats["missing"] += 1
            elif key in {"strong_evidence", "high_quality_case"}:
                stats["strong"] += 1
        drafter = str(item.get("drafted_by") or item.get("assigned_to") or "unassigned")
        drafter_slot = drafter_stats[drafter]
        drafter_slot["drafted"] += 1
        if str(item.get("sar_status") or "").lower() == "rejected":
            drafter_slot["rejected"] += 1
        if any(str(f.get("feedback_key") or "") == "weak_sar_draft" for f in feedback_items):
            drafter_slot["rework"] += 1
        if included_evidence_count >= required_evidence_min or evidence_count >= required_evidence_min:
            drafter_slot["evidence_complete"] += 1
        if review_lag_hours is not None:
            drafter_slot["review_lag_sum"] += float(review_lag_hours)
            drafter_slot["review_lag_count"] += 1

        team_slot = team_approval_stats[team_key]
        team_slot["count"] += 1
        if filing_lag_hours is not None:
            team_slot["lag_sum"] += float(filing_lag_hours)
            team_slot["lag_count"] += 1
        if filed:
            team_slot["filed"] += 1

        typology_slot = typology_approval_stats[typology]
        typology_slot["count"] += 1
        if filing_lag_hours is not None:
            typology_slot["lag_sum"] += float(filing_lag_hours)
            typology_slot["lag_count"] += 1
        if filed:
            typology_slot["filed"] += 1
        bucket = (created_at or _utcnow()).astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        model_versions = [str(v or "unknown") for v in (item.get("model_versions") or []) if str(v or "").strip()] or ["unknown"]
        workflow_key = "playbook_automation" if str(playbook.get("typology") or "").strip() else "standard_casework"
        positive = filed or any(str(f.get("feedback_key") or "") in {"strong_evidence", "high_quality_case"} for f in feedback_items)
        false_positive = any(str(f.get("feedback_key") or "") == "noisy_alert" for f in feedback_items)
        for version in model_versions:
            slot = model_trends[(bucket, version)]
            slot["count"] += 1
            slot["positive"] += 1 if positive else 0
            slot["false_positive"] += 1 if false_positive else 0
            slot["filed"] += 1 if filed else 0
        wf = workflow_trends[(bucket, workflow_key)]
        wf["count"] += 1
        wf["positive"] += 1 if positive else 0
        wf["false_positive"] += 1 if false_positive else 0
        wf["filed"] += 1 if filed else 0

    case_escalation_quality = []
    sar_quality_proxies = []
    for typology, stats in sorted(escalation_stats.items(), key=lambda pair: pair[1]["count"], reverse=True)[:8]:
        case_escalation_quality.append(
            {
                "scope_key": typology,
                "scope_label": _titleize(typology),
                "metric": _rate(stats["filed"], stats["count"]),
                "count": stats["count"],
                "secondary_metric": round(stats["cycle_sum"] / stats["cycle_count"], 2) if stats["cycle_count"] else None,
                "note": f"{stats['filed']} filed SAR outcomes from {stats['count']} cases.",
            }
        )
        proxy_denom = max(1, stats["count"])
        sar_quality_proxies.append(
            {
                "scope_key": typology,
                "scope_label": _titleize(typology),
                "metric": _rate(stats["strong"], proxy_denom),
                "count": stats["count"],
                "secondary_metric": _rate(stats["weak"] + stats["missing"], proxy_denom),
                "note": f"Weak draft signals {stats['weak']}, missing evidence signals {stats['missing']}.",
            }
        )

    true_positive_trends = []
    for (bucket, version), stats in sorted(model_trends.items()):
        true_positive_trends.append(
            {
                "bucket": bucket,
                "dimension_type": "model_version",
                "dimension_key": version,
                "dimension_label": f"Model v{version}",
                "true_positive_rate": _rate(stats["positive"], stats["count"]),
                "false_positive_rate": _rate(stats["false_positive"], stats["count"]),
                "filed_sar_rate": _rate(stats["filed"], stats["count"]),
                "count": stats["count"],
            }
        )
    for (bucket, workflow_key), stats in sorted(workflow_trends.items()):
        true_positive_trends.append(
            {
                "bucket": bucket,
                "dimension_type": "workflow",
                "dimension_key": workflow_key,
                "dimension_label": _titleize(workflow_key),
                "true_positive_rate": _rate(stats["positive"], stats["count"]),
                "false_positive_rate": _rate(stats["false_positive"], stats["count"]),
                "filed_sar_rate": _rate(stats["filed"], stats["count"]),
                "count": stats["count"],
            }
        )

    feedback_signals = [
        {
            "scope_key": key,
            "scope_label": FEEDBACK_DEFINITIONS.get(key, {}).get("label", _titleize(key)),
            "metric": 0.0,
            "count": count,
            "secondary_metric": None,
            "note": FEEDBACK_DEFINITIONS.get(key, {}).get("summary"),
        }
        for key, count in feedback_by_key.most_common(8)
    ]

    reviewer_quality = {
        "drafter_rejection": [
            {
                "scope_key": actor,
                "scope_label": actor,
                "metric": _rate(stats["rejected"], stats["drafted"]),
                "count": stats["drafted"],
                "secondary_metric": _rate(stats["rework"], stats["drafted"]),
                "note": (
                    f"Evidence completeness {round(_rate(stats['evidence_complete'], stats['drafted']) * 100)}% · "
                    f"Avg review lag {round(stats['review_lag_sum'] / stats['review_lag_count'], 2) if stats['review_lag_count'] else 'n/a'}h"
                ),
            }
            for actor, stats in sorted(drafter_stats.items(), key=lambda pair: (pair[1]["rejected"], pair[1]["rework"], pair[1]["drafted"]), reverse=True)
            if stats["drafted"] > 0
        ][:8],
        "team_approval_lag": [
            {
                "scope_key": key,
                "scope_label": _titleize(key),
                "metric": round(stats["lag_sum"] / stats["lag_count"], 2) if stats["lag_count"] else 0.0,
                "count": stats["count"],
                "secondary_metric": _rate(stats["filed"], stats["count"]),
                "note": f"{stats['filed']} filed SAR case(s).",
            }
            for key, stats in sorted(team_approval_stats.items(), key=lambda pair: (pair[1]["lag_sum"] / pair[1]["lag_count"]) if pair[1]["lag_count"] else 0, reverse=True)
        ][:8],
        "typology_approval_lag": [
            {
                "scope_key": key,
                "scope_label": _titleize(key),
                "metric": round(stats["lag_sum"] / stats["lag_count"], 2) if stats["lag_count"] else 0.0,
                "count": stats["count"],
                "secondary_metric": _rate(stats["filed"], stats["count"]),
                "note": f"{stats['filed']} filed SAR case(s).",
            }
            for key, stats in sorted(typology_approval_stats.items(), key=lambda pair: (pair[1]["lag_sum"] / pair[1]["lag_count"]) if pair[1]["lag_count"] else 0, reverse=True)
        ][:8],
    }

    tuning_recommendations: list[dict[str, Any]] = []
    for item in sorted(alert_precision_by_typology, key=lambda row: (float(row.get("secondary_metric") or 0), row.get("count", 0)), reverse=True)[:4]:
        noisy_rate = float(item.get("secondary_metric") or 0)
        if noisy_rate >= 0.3:
            tuning_recommendations.append(
                {
                    "recommendation_key": f"quality_tune_alerts::{item['scope_key']}",
                    "title": f"Tune alert thresholds for {_titleize(item['scope_key'])}",
                    "priority": "high" if noisy_rate >= 0.45 else "medium",
                    "action_type": "playbook_review",
                    "rationale": f"{round(noisy_rate * 100)}% noisy or false-positive posture suggests this typology needs tighter tuning.",
                    "target_scope": "typology",
                    "target_key": item["scope_key"],
                    "deep_link": "/#reports",
                    "metadata": {"metric": "decision_alert_precision", "typology": item["scope_key"]},
                }
            )
    for item in sorted(sar_quality_proxies, key=lambda row: (float(row.get("secondary_metric") or 0), row.get("count", 0)), reverse=True)[:4]:
        weak_rate = float(item.get("secondary_metric") or 0)
        if weak_rate >= 0.2:
            tuning_recommendations.append(
                {
                    "recommendation_key": f"quality_tune_sar::{item['scope_key']}",
                    "title": f"Strengthen SAR drafting for {_titleize(item['scope_key'])}",
                    "priority": "high" if weak_rate >= 0.35 else "medium",
                    "action_type": "review_guidance",
                    "rationale": f"{round(weak_rate * 100)}% of cases in this typology show weak-draft or missing-evidence feedback before filing.",
                    "target_scope": "typology",
                    "target_key": item["scope_key"],
                    "deep_link": "/#reports",
                    "metadata": {"metric": "decision_sar_quality", "typology": item["scope_key"]},
                }
            )
    for item in reviewer_quality["drafter_rejection"][:4]:
        rejection_rate = float(item.get("metric") or 0)
        rework_rate = float(item.get("secondary_metric") or 0)
        if rejection_rate >= 0.2 or rework_rate >= 0.25:
            tuning_recommendations.append(
                {
                    "recommendation_key": f"quality_coaching::{item['scope_key']}",
                    "title": f"Coach {item['scope_label']} on draft quality",
                    "priority": "medium",
                    "action_type": "manager_console",
                    "rationale": f"{round(rejection_rate * 100)}% rejection and {round(rework_rate * 100)}% rework indicates a coaching or review-guidance opportunity.",
                    "target_scope": "drafter",
                    "target_key": item["scope_key"],
                    "deep_link": "/#manager-console",
                    "metadata": {"metric": "reviewer_quality", "actor": item["scope_key"]},
                }
            )

    summary = [
        f"Decision quality tracked across {len(alert_precision_by_typology)} alert typologies and {len(case_escalation_quality)} case typologies.",
        f"{sum(item['count'] for item in feedback_signals)} closed-loop feedback signals were captured in the selected window." if feedback_signals else "No closed-loop feedback has been recorded yet.",
        f"{len(tuning_recommendations)} quality-tuning recommendation(s) are currently available.",
    ]

    return {
        "generated_at": _utcnow(),
        "range_days": range_days,
        "alert_precision_by_typology": alert_precision_by_typology,
        "case_escalation_quality": case_escalation_quality,
        "sar_quality_proxies": sar_quality_proxies,
        "true_positive_trends": true_positive_trends,
        "feedback_signals": feedback_signals,
        "quality_tuning_recommendations": tuning_recommendations,
        "reviewer_quality": reviewer_quality,
        "summary": summary,
    }


def _quality_snapshot_metrics(quality: dict[str, Any]) -> dict[str, Any]:
    alert_rows = list(quality.get("alert_precision_by_typology") or [])
    sar_rows = list(quality.get("sar_quality_proxies") or [])
    reviewer = quality.get("reviewer_quality") or {}
    top_noisy = max(alert_rows, key=lambda item: float(item.get("secondary_metric") or 0.0), default=None)
    top_weak = max(sar_rows, key=lambda item: float(item.get("secondary_metric") or 0.0), default=None)
    top_drafter = max(list(reviewer.get("drafter_rejection") or []), key=lambda item: float(item.get("metric") or 0.0), default=None)
    return {
        "feedback_signal_count": int(sum(int(item.get("count") or 0) for item in (quality.get("feedback_signals") or []))),
        "tuning_recommendation_count": int(len(quality.get("quality_tuning_recommendations") or [])),
        "top_noisy_typology": top_noisy.get("scope_key") if top_noisy else None,
        "top_noisy_rate": round(float(top_noisy.get("secondary_metric") or 0.0), 4) if top_noisy else 0.0,
        "top_weak_typology": top_weak.get("scope_key") if top_weak else None,
        "top_weak_rate": round(float(top_weak.get("secondary_metric") or 0.0), 4) if top_weak else 0.0,
        "top_drafter": top_drafter.get("scope_key") if top_drafter else None,
        "top_drafter_rejection_rate": round(float(top_drafter.get("metric") or 0.0), 4) if top_drafter else 0.0,
        "top_drafter_rework_rate": round(float(top_drafter.get("secondary_metric") or 0.0), 4) if top_drafter else 0.0,
    }


def _quality_period_over_period(points: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(points) < 2:
        return []
    latest = points[0].get("summary_metrics") or {}
    previous = points[1].get("summary_metrics") or {}
    metrics = [
        ("feedback_signal_count", "Feedback signals"),
        ("tuning_recommendation_count", "Tuning recommendations"),
        ("top_noisy_rate", "Top noisy typology rate"),
        ("top_weak_rate", "Top weak-draft typology rate"),
        ("top_drafter_rejection_rate", "Top drafter rejection rate"),
    ]
    rows = []
    for key, label in metrics:
        latest_value = float(latest.get(key) or 0.0)
        previous_value = float(previous.get(key) or 0.0)
        delta = round(latest_value - previous_value, 4)
        delta_pct = round((delta / previous_value) * 100, 2) if previous_value else None
        rows.append(
            {
                "key": key,
                "label": label,
                "latest_value": latest_value,
                "previous_value": previous_value,
                "delta": delta,
                "delta_pct": delta_pct,
                "status": "up" if delta > 0 else "down" if delta < 0 else "flat",
                "latest_period": points[0].get("period_label"),
                "previous_period": points[1].get("period_label"),
            }
        )
    return rows


async def capture_decision_quality_snapshot(
    *,
    actor: str | None,
    snapshot_granularity: str = "daily",
    range_days: int = 180,
    source: str = "manual",
    reference_time: datetime | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    period_start, period_end, period_label = _period_bounds(snapshot_granularity, reference_time)
    quality = await get_decision_quality_analytics(range_days=range_days)
    summary_metrics = _quality_snapshot_metrics(quality)
    summary_metrics.update({"period_label": period_label, "snapshot_granularity": snapshot_granularity})
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO decision_quality_snapshots (
                snapshot_granularity, range_days, period_start, period_end, period_label,
                captured_by, source, summary_metrics, snapshot, metadata
            )
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9::jsonb,$10::jsonb)
            RETURNING id, captured_at, period_start, period_end, period_label
            """,
            snapshot_granularity,
            range_days,
            period_start,
            period_end,
            period_label,
            actor,
            source,
            json.dumps(summary_metrics),
            json.dumps(quality, default=str),
            json.dumps((metadata or {}) | {"period_label": period_label}),
        )
    return {
        "captured": True,
        "snapshot_granularity": snapshot_granularity,
        "range_days": range_days,
        "snapshot_id": row["id"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "period_label": row["period_label"],
        "captured_at": row["captured_at"],
        "summary": [
            f"Captured {snapshot_granularity} decision-quality snapshot for {range_days} days.",
            f"{summary_metrics.get('feedback_signal_count', 0)} feedback signals and {summary_metrics.get('tuning_recommendation_count', 0)} tuning recommendations were present.",
        ],
    }


async def get_decision_quality_snapshots(
    *,
    snapshot_granularity: str = "daily",
    range_days: int = 180,
    limit: int = 30,
    auto_capture: bool = False,
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, snapshot_granularity, range_days, period_start, period_end, period_label,
                   captured_at, captured_by, source, summary_metrics, metadata
            FROM decision_quality_snapshots
            WHERE snapshot_granularity = $1 AND range_days = $2
            ORDER BY period_end DESC NULLS LAST, captured_at DESC
            LIMIT $3
            """,
            snapshot_granularity,
            range_days,
            limit,
        )
    if not rows and auto_capture:
        await capture_decision_quality_snapshot(
            actor="quality-auto-capture",
            snapshot_granularity=snapshot_granularity,
            range_days=range_days,
            source="auto_bootstrap",
            metadata={"auto_capture": True},
        )
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, snapshot_granularity, range_days, period_start, period_end, period_label,
                       captured_at, captured_by, source, summary_metrics, metadata
                FROM decision_quality_snapshots
                WHERE snapshot_granularity = $1 AND range_days = $2
                ORDER BY period_end DESC NULLS LAST, captured_at DESC
                LIMIT $3
                """,
                snapshot_granularity,
                range_days,
                limit,
            )
    points = [
        {
            "id": row["id"],
            "snapshot_granularity": row["snapshot_granularity"] or "daily",
            "range_days": row["range_days"],
            "period_start": row["period_start"],
            "period_end": row["period_end"],
            "period_label": row["period_label"],
            "captured_at": row["captured_at"],
            "captured_by": row["captured_by"],
            "source": row["source"],
            "summary_metrics": _normalize_json_dict(row["summary_metrics"]),
            "metadata": _normalize_json_dict(row["metadata"]),
        }
        for row in rows
    ]
    latest = points[0] if points else None
    period_over_period = _quality_period_over_period(points)
    return {
        "generated_at": _utcnow(),
        "snapshot_granularity": snapshot_granularity,
        "range_days": range_days,
        "total_points": len(points),
        "points": points,
        "period_over_period": period_over_period,
        "summary": [
            f"{len(points)} persisted {snapshot_granularity} decision-quality snapshot(s) available.",
            (
                f"Latest period {latest.get('period_label') or latest['captured_at'].isoformat()} captured with {latest['summary_metrics'].get('feedback_signal_count', 0)} feedback signal(s)."
                if latest
                else "No decision-quality snapshots captured yet."
            ),
        ],
    }


async def get_decision_quality_drilldown(
    *,
    metric_key: str,
    range_days: int = 180,
    typology: str | None = None,
    team_key: str | None = None,
    region_key: str | None = None,
    feedback_key: str | None = None,
    limit: int = 40,
) -> dict[str, Any]:
    metric = str(metric_key or "decision_feedback_signal").strip().lower()
    normalized_typology = str(typology or "").strip().lower() or None
    normalized_team = str(team_key or "").strip().lower() or None
    normalized_region = str(region_key or "").strip().lower() or None
    normalized_feedback_key = str(feedback_key or "").strip().lower() or None
    pool = get_pool()
    async with pool.acquire() as conn:
        case_rows = await conn.fetch(
            """
            SELECT
                c.id,
                c.case_ref,
                c.status,
                c.priority,
                c.assigned_to,
                c.created_at,
                c.updated_at,
                c.metadata,
                s.status::text AS sar_status,
                COALESCE(ce.evidence_count, 0) AS evidence_count,
                COALESCE(ce.included_evidence_count, 0) AS included_evidence_count,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT a.alert_type), NULL) AS alert_types,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT a.status), NULL) AS alert_statuses,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT a.id), NULL) AS alert_ids,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT COALESCE(t.ml_features->'scorer_metadata'->>'model_version', 'unknown')), NULL) AS model_versions
            FROM cases c
            LEFT JOIN sar_reports s ON s.case_id = c.id
            LEFT JOIN case_alerts ca ON ca.case_id = c.id
            LEFT JOIN alerts a ON a.id = ca.alert_id
            LEFT JOIN transactions t ON t.id = a.transaction_id
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*) AS evidence_count,
                    COUNT(*) FILTER (WHERE include_in_sar = TRUE) AS included_evidence_count
                FROM case_evidence cex
                WHERE cex.case_id = c.id
            ) ce ON TRUE
            WHERE c.created_at >= NOW() - ($1::int * INTERVAL '1 day')
            GROUP BY c.id, s.id, ce.evidence_count, ce.included_evidence_count
            ORDER BY c.created_at DESC
            """,
            range_days,
        )
        feedback_rows = await conn.fetch(
            """
            SELECT
                df.id,
                df.subject_type,
                df.subject_id,
                df.case_id,
                df.alert_id,
                df.feedback_key,
                df.label,
                df.sentiment,
                df.note,
                df.created_at,
                c.metadata AS case_metadata,
                a.alert_type,
                a.status AS alert_status
            FROM decision_feedback df
            LEFT JOIN cases c ON c.id = COALESCE(df.case_id, CASE WHEN df.subject_type = 'case' THEN df.subject_id ELSE NULL END)
            LEFT JOIN alerts a ON a.id = COALESCE(df.alert_id, CASE WHEN df.subject_type = 'alert' THEN df.subject_id ELSE NULL END)
            WHERE df.created_at >= NOW() - ($1::int * INTERVAL '1 day')
            ORDER BY df.created_at DESC
            """,
            range_days,
        )

    feedback_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in feedback_rows:
        item = dict(raw)
        item["case_metadata"] = _normalize_json_dict(item.get("case_metadata"))
        case_id = item.get("case_id")
        if case_id:
            feedback_by_case[str(case_id)].append(item)

    cases: list[dict[str, Any]] = []
    for raw_case in case_rows:
        case = dict(raw_case)
        metadata = _normalize_json_dict(case.get("metadata"))
        routing = _normalize_json_dict(metadata.get("routing"))
        case_typology = str(
            _normalize_json_dict(metadata.get("playbook")).get("typology")
            or metadata.get("typology")
            or ((case.get("alert_types") or [None])[0] or "unknown")
        ).lower()
        if normalized_typology and case_typology != normalized_typology:
            continue

        case_team = str(routing.get("team_key") or metadata.get("team_key") or "unassigned_team").lower()
        case_region = str(routing.get("region_key") or metadata.get("region_key") or "global").lower()
        if normalized_team and case_team != normalized_team:
            continue
        if normalized_region and case_region != normalized_region:
            continue

        case_feedback = feedback_by_case.get(str(case["id"]), [])
        feedback_keys = [str(item.get("feedback_key") or "").lower() for item in case_feedback]
        if normalized_feedback_key and normalized_feedback_key not in feedback_keys:
            continue

        alert_statuses = [str(item or "").lower() for item in (case.get("alert_statuses") or [])]
        has_sar = bool(case.get("sar_status"))
        included_evidence_count = int(case.get("included_evidence_count") or 0)
        evidence_count = int(case.get("evidence_count") or 0)
        required_evidence_min = 2 if has_sar else 1
        missing_evidence_count = max(0, required_evidence_min - included_evidence_count)
        created_at = _safe_datetime(case.get("created_at"))
        updated_at = _safe_datetime(case.get("updated_at"))
        workflow_delay_hours = None
        if created_at and updated_at:
            workflow_delay_hours = round(max(0.0, (updated_at - created_at).total_seconds() / 3600.0), 2)
        model_version = next((str(v) for v in (case.get("model_versions") or []) if str(v).strip()), None)
        positive_signals = sum(1 for key in feedback_keys if key in {"good_alert", "strong_evidence", "high_quality_case"})
        negative_signals = sum(1 for key in feedback_keys if key in {"noisy_alert", "missing_evidence", "weak_sar_draft"})

        include = False
        recommended_desk = "case-command"
        if metric == "decision_alert_precision":
            include = "false_positive" in alert_statuses or any(key in {"good_alert", "noisy_alert"} for key in feedback_keys)
            recommended_desk = "alert-desk"
        elif metric == "decision_case_escalation":
            include = positive_signals > 0 or negative_signals > 0 or str(case.get("status") or "").lower() in {"reviewing", "pending_sar", "pending_review", "approved"}
        elif metric == "decision_sar_quality":
            include = has_sar or any(key in {"weak_sar_draft", "strong_evidence", "missing_evidence"} for key in feedback_keys)
            recommended_desk = "sar-queue" if has_sar else "case-command"
        elif metric == "decision_feedback_signal":
            include = bool(case_feedback)
        else:
            include = bool(case_feedback)

        if not include:
            continue

        cases.append(
            {
                "case_id": case["id"],
                "case_ref": case.get("case_ref"),
                "status": case.get("status"),
                "priority": case.get("priority"),
                "assigned_to": case.get("assigned_to"),
                "team_key": routing.get("team_key") or metadata.get("team_key") or "unassigned_team",
                "team_label": routing.get("team_label") or metadata.get("team_label") or _titleize(case_team),
                "region_key": routing.get("region_key") or metadata.get("region_key") or "global",
                "region_label": routing.get("region_label") or metadata.get("region_label") or _titleize(case_region),
                "typology": case_typology,
                "model_version": model_version,
                "sar_status": case.get("sar_status"),
                "has_sar": has_sar,
                "false_positive": "false_positive" in alert_statuses,
                "workflow_delay_hours": workflow_delay_hours,
                "review_lag_hours": None,
                "approval_lag_hours": None,
                "filing_lag_hours": None,
                "audit_trail_completeness": 0.0,
                "evidence_pack_completeness": round(min(1.0, included_evidence_count / max(1, required_evidence_min)), 4),
                "evidence_count": evidence_count,
                "included_evidence_count": included_evidence_count,
                "missing_evidence_count": missing_evidence_count,
                "progress": float(_normalize_json_dict(metadata.get("playbook")).get("checklist_progress") or 0.0),
                "created_at": created_at,
                "case_deep_link": f"/#case-command?case={case['id']}",
                "recommended_desk": recommended_desk,
                "primary_alert_id": str((case.get("alert_ids") or [None])[0]) if (case.get("alert_ids") or []) else None,
                "decision_feedback_count": len(case_feedback),
                "positive_signal_count": positive_signals,
                "negative_signal_count": negative_signals,
            }
        )

    cases.sort(
        key=lambda item: (
            item.get("negative_signal_count", 0),
            item.get("missing_evidence_count", 0),
            item.get("workflow_delay_hours") or 0.0,
        ),
        reverse=True,
    )
    visible = cases[:limit]
    drill_path = ["Decision Quality", metric.replace("_", " ").title()]
    if normalized_typology:
        drill_path.append(_titleize(normalized_typology))
    if normalized_feedback_key:
        drill_path.append(_titleize(normalized_feedback_key))
    return {
        "generated_at": _utcnow(),
        "metric_key": metric,
        "filters": {
            "range_days": range_days,
            "typology": normalized_typology,
            "team_key": normalized_team,
            "region_key": normalized_region,
            "feedback_key": normalized_feedback_key,
            "limit": limit,
        },
        "counts": {
            "matched_cases": len(cases),
            "returned_cases": len(visible),
            "cases_with_sar": sum(1 for item in visible if item.get("has_sar")),
            "cases_with_negative_signals": sum(1 for item in visible if item.get("negative_signal_count", 0) > 0),
        },
        "drill_path": drill_path,
        "snapshot_id": None,
        "period_label": None,
        "summary": [
            f"{len(cases)} case(s) matched decision-quality metric {metric}.",
            (
                f"Feedback filter {normalized_feedback_key} was applied."
                if normalized_feedback_key
                else "Includes recent feedback and decision-outcome signals."
            ),
        ],
        "cases": visible,
    }
