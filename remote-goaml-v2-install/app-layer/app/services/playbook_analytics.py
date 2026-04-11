"""
Playbook compliance and typology outcome analytics for Reporting Studio and Manager Console.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID

from core.database import get_pool
from services.case_playbooks import get_case_playbook_state, infer_case_typology


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


def _bucket_label(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d")


async def _fetch_cases(range_days: int) -> list[dict[str, Any]]:
    pool = get_pool()
    since = _utcnow() - timedelta(days=range_days)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.id,
                c.case_ref,
                c.priority,
                c.status,
                c.metadata,
                c.sar_id,
                c.primary_entity_id,
                c.created_at,
                c.updated_at,
                c.ai_summary,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT a.alert_type), NULL) AS alert_types,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT a.status), NULL) AS alert_statuses
            FROM cases c
            LEFT JOIN case_alerts ca ON ca.case_id = c.id
            LEFT JOIN alerts a ON a.id = ca.alert_id
            WHERE c.created_at >= $1
            GROUP BY c.id
            ORDER BY c.created_at DESC
            """,
            since,
        )
    return [dict(row) for row in rows]


def _rate(numerator: int | float, denominator: int | float) -> float:
    if not denominator:
        return 0.0
    return round(float(numerator) / float(denominator), 4)


async def get_playbook_analytics(*, range_days: int = 180, top_steps: int = 12) -> dict[str, Any]:
    cases = await _fetch_cases(range_days)

    typology_stats: dict[str, dict[str, Any]] = {}
    missed_steps: dict[tuple[str, str], dict[str, Any]] = {}
    team_stats: dict[str, dict[str, Any]] = {}
    region_stats: dict[str, dict[str, Any]] = {}
    step_heatmap: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    blocked_trends: dict[str, dict[str, int]] = defaultdict(lambda: {"blocked_case_count": 0, "blocked_step_total": 0, "missing_evidence_total": 0})

    processed_case_count = 0
    false_positive_cases = 0
    sar_cases = 0

    for case_row in cases:
        metadata = _normalize_json_dict(case_row.get("metadata"))
        routing = _normalize_json_dict(metadata.get("routing"))
        typology = (
            _normalize_json_dict(metadata.get("playbook")).get("typology")
            or metadata.get("typology")
            or infer_case_typology(metadata=metadata, alert_types=[str(item) for item in (case_row.get("alert_types") or []) if str(item).strip()])
        )
        if not typology:
            continue

        playbook = await get_case_playbook_state(UUID(str(case_row["id"])), case_row=case_row)
        if not playbook:
            continue

        processed_case_count += 1
        display_name = str(playbook.get("display_name") or str(typology).replace("_", " ").title())
        bucket = _bucket_label(_safe_datetime(case_row.get("created_at")) or _utcnow())
        alert_statuses = [str(item or "").lower() for item in (case_row.get("alert_statuses") or []) if str(item or "").strip()]
        has_false_positive = "false_positive" in alert_statuses
        has_sar = bool(case_row.get("sar_id"))
        filed_sar = str(case_row.get("status") or "").lower() == "sar_filed"
        blocked_steps = [str(item) for item in (playbook.get("blocked_steps") or []) if str(item).strip()]
        required_evidence_missing = [str(item) for item in (playbook.get("required_evidence_missing") or []) if str(item).strip()]
        checklist = [item for item in (playbook.get("checklist") or []) if isinstance(item, dict)]
        team_key = str(routing.get("team_key") or metadata.get("team_key") or "unassigned_team")
        team_label = str(routing.get("team_label") or metadata.get("team_label") or team_key.replace("_", " ").title())
        region_key = str(routing.get("region_key") or metadata.get("region_key") or "global")
        region_label = str(routing.get("region_label") or metadata.get("region_label") or region_key.replace("_", " ").title())

        stat = typology_stats.setdefault(
            typology,
            {
                "typology": typology,
                "display_name": display_name,
                "case_count": 0,
                "completion_sum": 0.0,
                "avg_progress_sum": 0.0,
                "fully_completed_cases": 0,
                "blocked_cases": 0,
                "false_positive_cases": 0,
                "sar_cases": 0,
                "filed_sar_cases": 0,
                "missing_evidence_cases": 0,
            },
        )
        stat["case_count"] += 1
        stat["completion_sum"] += _rate(playbook.get("checklist_completed_count", 0), playbook.get("checklist_total_count", 0))
        stat["avg_progress_sum"] += float(playbook.get("checklist_progress", 0) or 0)
        stat["fully_completed_cases"] += 1 if not blocked_steps and not required_evidence_missing and int(playbook.get("checklist_progress", 0) or 0) >= 100 else 0
        stat["blocked_cases"] += 1 if blocked_steps else 0
        stat["false_positive_cases"] += 1 if has_false_positive else 0
        stat["sar_cases"] += 1 if has_sar else 0
        stat["filed_sar_cases"] += 1 if filed_sar else 0
        stat["missing_evidence_cases"] += 1 if required_evidence_missing else 0

        false_positive_cases += 1 if has_false_positive else 0
        sar_cases += 1 if has_sar else 0

        for scope_type, scope_key, scope_label, scope_store in (
            ("team", team_key, team_label, team_stats),
            ("region", region_key, region_label, region_stats),
        ):
            scope_stat = scope_store.setdefault(
                scope_key,
                {
                    "scope_key": scope_key,
                    "scope_label": scope_label,
                    "case_count": 0,
                    "typologies": set(),
                    "progress_sum": 0.0,
                    "blocked_cases": 0,
                    "missing_evidence_cases": 0,
                    "false_positive_cases": 0,
                    "sar_cases": 0,
                    "filed_sar_cases": 0,
                },
            )
            scope_stat["case_count"] += 1
            scope_stat["typologies"].add(typology)
            scope_stat["progress_sum"] += float(playbook.get("checklist_progress", 0) or 0)
            scope_stat["blocked_cases"] += 1 if blocked_steps else 0
            scope_stat["missing_evidence_cases"] += 1 if required_evidence_missing else 0
            scope_stat["false_positive_cases"] += 1 if has_false_positive else 0
            scope_stat["sar_cases"] += 1 if has_sar else 0
            scope_stat["filed_sar_cases"] += 1 if filed_sar else 0

        if blocked_steps:
            blocked_trends[bucket]["blocked_case_count"] += 1
            blocked_trends[bucket]["blocked_step_total"] += len(blocked_steps)
        if required_evidence_missing:
            blocked_trends[bucket]["missing_evidence_total"] += len(required_evidence_missing)

        for item in checklist:
            status = str(item.get("status") or "").lower()
            if status == "done":
                continue
            key = (typology, str(item.get("key") or item.get("label") or "step"))
            metric = missed_steps.setdefault(
                key,
                {
                    "typology": typology,
                    "display_name": display_name,
                    "step_key": str(item.get("key") or "step"),
                    "step_label": str(item.get("label") or item.get("key") or "Step"),
                    "missed_count": 0,
                    "blocking": bool(item.get("blocking", True)),
                    "evidence_related": bool(item.get("evidence_related")),
                },
            )
            metric["missed_count"] += 1
            if status != "done":
                for scope_type, scope_key, scope_label in (
                    ("team", team_key, team_label),
                    ("region", region_key, region_label),
                ):
                    heatmap_key = (scope_type, scope_key, typology, metric["step_key"])
                    heatmap_metric = step_heatmap.setdefault(
                        heatmap_key,
                        {
                            "scope_type": scope_type,
                            "scope_key": scope_key,
                            "scope_label": scope_label,
                            "typology": typology,
                            "display_name": display_name,
                            "step_key": metric["step_key"],
                            "step_label": metric["step_label"],
                            "affected_case_count": 0,
                            "blocking_case_count": 0,
                            "evidence_gap_case_count": 0,
                        },
                    )
                    heatmap_metric["affected_case_count"] += 1
                    heatmap_metric["blocking_case_count"] += 1 if bool(item.get("blocking", True)) else 0
                    heatmap_metric["evidence_gap_case_count"] += 1 if bool(item.get("evidence_related")) else 0

    typology_items = []
    for stat in sorted(typology_stats.values(), key=lambda item: (item["case_count"], item["avg_progress_sum"]), reverse=True):
        case_count = stat["case_count"]
        typology_items.append(
            {
                "typology": stat["typology"],
                "display_name": stat["display_name"],
                "case_count": case_count,
                "checklist_completion_rate": _rate(stat["completion_sum"], case_count),
                "fully_completed_case_rate": _rate(stat["fully_completed_cases"], case_count),
                "avg_progress": round(stat["avg_progress_sum"] / case_count, 1) if case_count else 0.0,
                "blocked_case_rate": _rate(stat["blocked_cases"], case_count),
                "false_positive_rate": _rate(stat["false_positive_cases"], case_count),
                "sar_conversion_rate": _rate(stat["sar_cases"], case_count),
                "filed_sar_rate": _rate(stat["filed_sar_cases"], case_count),
                "missing_evidence_case_rate": _rate(stat["missing_evidence_cases"], case_count),
            }
        )

    most_missed = sorted(
        (
            {
                **item,
                "affected_case_rate": _rate(item["missed_count"], typology_stats.get(item["typology"], {}).get("case_count", 0)),
            }
            for item in missed_steps.values()
        ),
        key=lambda item: (item["missed_count"], item["affected_case_rate"]),
        reverse=True,
    )[:top_steps]

    trend_items = [
        {
            "bucket": bucket,
            **values,
        }
        for bucket, values in sorted(blocked_trends.items(), key=lambda item: item[0])[-14:]
    ]

    def _scope_items(scope_store: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for stat in sorted(scope_store.values(), key=lambda item: (item["case_count"], item["blocked_cases"], item["missing_evidence_cases"]), reverse=True):
            case_count = stat["case_count"]
            items.append(
                {
                    "scope_key": stat["scope_key"],
                    "scope_label": stat["scope_label"],
                    "case_count": case_count,
                    "typology_count": len(stat["typologies"]),
                    "avg_progress": round(stat["progress_sum"] / case_count, 1) if case_count else 0.0,
                    "blocked_case_rate": _rate(stat["blocked_cases"], case_count),
                    "missing_evidence_case_rate": _rate(stat["missing_evidence_cases"], case_count),
                    "false_positive_rate": _rate(stat["false_positive_cases"], case_count),
                    "sar_conversion_rate": _rate(stat["sar_cases"], case_count),
                    "filed_sar_rate": _rate(stat["filed_sar_cases"], case_count),
                }
            )
        return items

    team_items = _scope_items(team_stats)
    region_items = _scope_items(region_stats)
    heatmap_items = sorted(
        (
            {
                **item,
                "affected_case_rate": _rate(
                    item["affected_case_count"],
                    (team_stats if item["scope_type"] == "team" else region_stats).get(item["scope_key"], {}).get("case_count", 0),
                ),
            }
            for item in step_heatmap.values()
        ),
        key=lambda item: (item["affected_case_count"], item["blocking_case_count"], item["affected_case_rate"]),
        reverse=True,
    )[: max(top_steps, 10)]

    summary = [
        f"{processed_case_count} playbook-tagged cases were analyzed across {len(typology_items)} typologies.",
        f"{sum(1 for item in typology_items if item['blocked_case_rate'] > 0)} typologies currently have blocking checklist steps.",
        f"SAR conversion is currently highest in {typology_items[0]['display_name'] if typology_items else 'n/a'}." if typology_items else "No typology analytics are available yet.",
    ]
    if team_items:
        summary.append(f"Most pressured team: {team_items[0]['scope_label']} with {team_items[0]['case_count']} cases and {round(team_items[0]['blocked_case_rate'] * 100)}% blocked.")
    if region_items:
        summary.append(f"Most pressured region: {region_items[0]['scope_label']} with {region_items[0]['case_count']} cases and {round(region_items[0]['missing_evidence_case_rate'] * 100)}% evidence gaps.")

    return {
        "generated_at": _utcnow(),
        "range_days": range_days,
        "totals": {
            "case_count": processed_case_count,
            "typology_count": len(typology_items),
            "false_positive_cases": false_positive_cases,
            "sar_cases": sar_cases,
            "blocked_cases": sum(1 for item in typology_items if item["blocked_case_rate"] > 0),
        },
        "typologies": typology_items,
        "most_missed_steps": most_missed,
        "blocked_step_trends": trend_items,
        "team_breakdown": team_items,
        "region_breakdown": region_items,
        "worst_offending_steps": heatmap_items,
        "summary": summary,
    }
