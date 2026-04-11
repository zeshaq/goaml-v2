"""
Manager-focused queue console, backlog analytics, and reassignment controls.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID

from core.config import settings
from core.database import get_pool
from models.analyst_ops import BulkAlertActionRequest, BulkSarActionRequest
from services.alerts import run_bulk_alert_actions
from services.cases import list_sar_queue, run_bulk_sar_queue_actions
from services.routing import analyst_directory, region_label


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


def _directory_map() -> dict[str, dict[str, Any]]:
    return {str(item.get("name")): item for item in analyst_directory() if str(item.get("name") or "").strip()}


def _routing_context(*, metadata: dict[str, Any] | None, owner: str | None, directory: dict[str, dict[str, Any]]) -> dict[str, Any]:
    routing = _normalize_json_dict((metadata or {}).get("routing"))
    profile = directory.get(str(owner or "")) or {}
    team_key = str(routing.get("team_key") or profile.get("team_key") or settings.OPS_ALERT_DEFAULT_TEAM)
    team_label = str(routing.get("team_label") or profile.get("team_label") or team_key.replace("_", " ").title())
    region_key = str(
        routing.get("region_key")
        or (profile.get("regions") or [settings.OPS_ALERT_DEFAULT_REGION])[0]
        or settings.OPS_ALERT_DEFAULT_REGION
    )
    return {
        "team_key": team_key,
        "team_label": team_label,
        "region_key": region_key,
        "region_label": str(routing.get("region_label") or region_label(region_key)),
    }


async def _fetch_manager_alerts(limit: int) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                a.id,
                a.alert_ref,
                a.alert_type,
                a.status,
                a.severity,
                a.title,
                a.assigned_to,
                a.case_id,
                a.created_at,
                a.metadata,
                c.case_ref,
                c.metadata AS case_metadata
            FROM alerts a
            LEFT JOIN cases c ON c.id = a.case_id
            WHERE a.status IN ('open', 'reviewing', 'escalated')
            ORDER BY
                CASE WHEN a.severity = 'critical' THEN 0 WHEN a.severity = 'high' THEN 1 WHEN a.severity = 'medium' THEN 2 ELSE 3 END,
                a.created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(row) for row in rows]


async def _case_typology_map(case_ids: list[UUID]) -> dict[str, list[str]]:
    if not case_ids:
        return {}
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                ca.case_id,
                ARRAY_REMOVE(ARRAY_AGG(DISTINCT a.alert_type), NULL) AS typologies
            FROM case_alerts ca
            JOIN alerts a ON a.id = ca.alert_id
            WHERE ca.case_id = ANY($1::uuid[])
            GROUP BY ca.case_id
            """,
            case_ids,
        )
    return {str(row["case_id"]): [str(item) for item in (row["typologies"] or []) if str(item).strip()] for row in rows}


def _filter_alert_item(item: dict[str, Any], filters: dict[str, Any]) -> bool:
    if filters.get("team_key") and item.get("team_key") != filters["team_key"]:
        return False
    if filters.get("region_key") and item.get("region_key") != filters["region_key"]:
        return False
    if filters.get("typology") and item.get("alert_type") != filters["typology"]:
        return False
    if filters.get("owner") and (item.get("assigned_to") or "") != filters["owner"]:
        return False
    return True


def _filter_sar_item(item: dict[str, Any], filters: dict[str, Any]) -> bool:
    if filters.get("team_key") and item.get("team_key") != filters["team_key"]:
        return False
    if filters.get("region_key") and item.get("region_key") != filters["region_key"]:
        return False
    if filters.get("owner") and (item.get("queue_owner") or item.get("assigned_to") or "") != filters["owner"]:
        return False
    if filters.get("sla_status") and (item.get("sla_status") or "") != filters["sla_status"]:
        return False
    if filters.get("typology"):
        typologies = item.get("typologies") or []
        if filters["typology"] not in typologies:
            return False
    return True


async def get_manager_console(
    *,
    team_key: str | None,
    region_key: str | None,
    typology: str | None,
    sla_status: str | None,
    owner: str | None,
    limit: int,
) -> dict[str, Any]:
    filters = {
        "team_key": team_key or "",
        "region_key": region_key or "",
        "typology": typology or "",
        "sla_status": sla_status or "",
        "owner": owner or "",
    }
    directory = _directory_map()
    alert_rows = await _fetch_manager_alerts(limit=max(limit * 4, 120))
    sar_queue = await list_sar_queue(queue="all", limit=max(limit * 4, 120), offset=0)
    sar_items = list(sar_queue.get("items", []))
    typology_map = await _case_typology_map([UUID(str(item["case_id"])) for item in sar_items if item.get("case_id")])

    manager_alerts: list[dict[str, Any]] = []
    for row in alert_rows:
        metadata = _normalize_json_dict(row.get("metadata"))
        case_metadata = _normalize_json_dict(row.get("case_metadata"))
        routing = _routing_context(metadata=metadata or case_metadata, owner=row.get("assigned_to"), directory=directory)
        item = {
            "id": row["id"],
            "alert_ref": row["alert_ref"],
            "alert_type": row["alert_type"],
            "status": row["status"],
            "severity": row["severity"],
            "title": row["title"],
            "assigned_to": row.get("assigned_to"),
            "case_id": row.get("case_id"),
            "case_ref": row.get("case_ref"),
            "created_at": row["created_at"],
            **routing,
        }
        if _filter_alert_item(item, filters):
            manager_alerts.append(item)

    manager_sars: list[dict[str, Any]] = []
    for item in sar_items:
        case_metadata = _normalize_json_dict(item.get("case_metadata"))
        routing = _routing_context(metadata=case_metadata, owner=item.get("queue_owner") or item.get("assigned_to"), directory=directory)
        queue_key = str(item.get("sar_status") or "").lower()
        normalized = {
            "case_id": item["case_id"],
            "case_ref": item["case_ref"],
            "case_title": item["case_title"],
            "case_priority": item["case_priority"],
            "case_status": item["case_status"],
            "sar_id": item.get("sar_id"),
            "sar_ref": item.get("sar_ref"),
            "sar_status": item.get("sar_status"),
            "queue": queue_key,
            "queue_owner": item.get("queue_owner"),
            "assigned_to": item.get("assigned_to"),
            "sla_status": item.get("sla_status"),
            "age_hours": item.get("age_hours"),
            "subject_name": item.get("subject_name"),
            "typologies": typology_map.get(str(item["case_id"]), []),
            **routing,
        }
        if _filter_sar_item(normalized, filters):
            manager_sars.append(normalized)

    heatmap_map: dict[tuple[str, str], dict[str, Any]] = {}
    for item in manager_alerts:
        key = (item["team_key"], item["team_label"])
        slot = heatmap_map.setdefault(
            key,
            {
                "team_key": item["team_key"],
                "team_label": item["team_label"],
                "backlog_count": 0,
                "breached_count": 0,
                "critical_count": 0,
                "alert_count": 0,
                "sar_count": 0,
            },
        )
        slot["backlog_count"] += 1
        slot["alert_count"] += 1
        if str(item.get("severity") or "").lower() == "critical":
            slot["critical_count"] += 1

    for item in manager_sars:
        key = (item["team_key"], item["team_label"])
        slot = heatmap_map.setdefault(
            key,
            {
                "team_key": item["team_key"],
                "team_label": item["team_label"],
                "backlog_count": 0,
                "breached_count": 0,
                "critical_count": 0,
                "alert_count": 0,
                "sar_count": 0,
            },
        )
        slot["backlog_count"] += 1
        slot["sar_count"] += 1
        if item.get("sla_status") == "breached":
            slot["breached_count"] += 1
        if str(item.get("case_priority") or "").lower() == "critical":
            slot["critical_count"] += 1

    workload_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "owner": "unassigned",
            "team_key": None,
            "team_label": None,
            "region_key": None,
            "region_label": None,
            "alert_count": 0,
            "high_alert_count": 0,
            "sar_active_count": 0,
            "sar_breached_count": 0,
            "combined_backlog": 0,
        }
    )
    for item in manager_alerts:
        owner_key = item.get("assigned_to") or "unassigned"
        slot = workload_map[owner_key]
        slot["owner"] = owner_key
        slot["team_key"] = slot["team_key"] or item.get("team_key")
        slot["team_label"] = slot["team_label"] or item.get("team_label")
        slot["region_key"] = slot["region_key"] or item.get("region_key")
        slot["region_label"] = slot["region_label"] or item.get("region_label")
        slot["alert_count"] += 1
        slot["combined_backlog"] += 1
        if str(item.get("severity") or "").lower() in {"high", "critical"}:
            slot["high_alert_count"] += 1
    for item in manager_sars:
        owner_key = item.get("queue_owner") or item.get("assigned_to") or "unassigned"
        slot = workload_map[owner_key]
        slot["owner"] = owner_key
        slot["team_key"] = slot["team_key"] or item.get("team_key")
        slot["team_label"] = slot["team_label"] or item.get("team_label")
        slot["region_key"] = slot["region_key"] or item.get("region_key")
        slot["region_label"] = slot["region_label"] or item.get("region_label")
        slot["sar_active_count"] += 1
        slot["combined_backlog"] += 1
        if item.get("sla_status") == "breached":
            slot["sar_breached_count"] += 1

    teams = {(item["team_key"], item["team_label"]) for item in manager_alerts}
    teams.update((item["team_key"], item["team_label"]) for item in manager_sars)
    if not teams:
        teams = {
            (
                str(item.get("team_key") or settings.OPS_ALERT_DEFAULT_TEAM),
                str(item.get("team_label") or item.get("team_key") or settings.OPS_ALERT_DEFAULT_TEAM).replace("_", " ").title(),
            )
            for item in analyst_directory()
        }
    regions = {(item["region_key"], item["region_label"]) for item in manager_alerts}
    regions.update((item["region_key"], item["region_label"]) for item in manager_sars)
    if not regions:
        regions = {(settings.OPS_ALERT_DEFAULT_REGION, region_label(settings.OPS_ALERT_DEFAULT_REGION))}
    typologies = {str(item["alert_type"]) for item in manager_alerts}
    for item in manager_sars:
        typologies.update(item.get("typologies") or [])
    owners = {str(item.get("assigned_to") or "") for item in manager_alerts if item.get("assigned_to")}
    owners.update(str(item.get("queue_owner") or item.get("assigned_to") or "") for item in manager_sars if item.get("queue_owner") or item.get("assigned_to"))

    heatmap = sorted(heatmap_map.values(), key=lambda item: (-item["backlog_count"], -item["breached_count"], item["team_label"]))
    workload_board = sorted(workload_map.values(), key=lambda item: (-item["combined_backlog"], -item["sar_breached_count"], item["owner"]))

    counts = {
        "alert_backlog": len(manager_alerts),
        "sar_backlog": len(manager_sars),
        "breached_sars": sum(1 for item in manager_sars if item.get("sla_status") == "breached"),
        "critical_alerts": sum(1 for item in manager_alerts if str(item.get("severity") or "").lower() == "critical"),
        "high_alerts": sum(1 for item in manager_alerts if str(item.get("severity") or "").lower() in {"high", "critical"}),
        "teams_in_scope": len(heatmap),
        "owners_in_scope": sum(1 for item in workload_board if item["owner"] != "unassigned"),
    }
    summary = [
        f"{counts['alert_backlog']} active alerts and {counts['sar_backlog']} active SAR items are currently in manager scope.",
        f"{counts['breached_sars']} SAR items are breached and {counts['critical_alerts']} alerts are critical.",
        (f"Top workload owner is {workload_board[0]['owner']} with {workload_board[0]['combined_backlog']} items." if workload_board else "No current workload owners are in scope."),
    ]

    options = {
        "teams": [{"value": key, "label": label} for key, label in sorted(teams, key=lambda item: item[1])],
        "regions": [{"value": key, "label": label} for key, label in sorted(regions, key=lambda item: item[1])],
        "typologies": [{"value": value, "label": value.replace("_", " ").title()} for value in sorted(typologies)],
        "owners": [{"value": value, "label": value} for value in sorted(owner for owner in owners if owner)],
        "analysts": [
            {
                "value": str(item.get("name") or ""),
                "label": " · ".join(
                    part
                    for part in [
                        str(item.get("name") or ""),
                        str(item.get("team_label") or item.get("team_key") or "").replace("_", " ").title(),
                        region_label(str((item.get("regions") or [settings.OPS_ALERT_DEFAULT_REGION])[0])),
                    ]
                    if part
                ),
            }
            for item in sorted(
                analyst_directory(),
                key=lambda entry: (
                    str(entry.get("team_label") or entry.get("team_key") or ""),
                    str(entry.get("name") or ""),
                ),
            )
            if str(item.get("name") or "").strip()
        ],
        "sla_states": [
            {"value": "breached", "label": "Breached"},
            {"value": "due_soon", "label": "Due soon"},
            {"value": "within_sla", "label": "Within SLA"},
        ],
    }

    return {
        "generated_at": _utcnow(),
        "filters": filters,
        "options": options,
        "counts": counts,
        "summary": summary,
        "alert_backlog": manager_alerts[:limit],
        "sar_backlog": manager_sars[:limit],
        "backlog_heatmap": heatmap[:12],
        "workload_board": workload_board[:12],
    }


async def run_manager_mass_reassign(
    *,
    actor: str,
    assigned_to: str,
    alert_ids: list[UUID],
    case_ids: list[UUID],
    note: str | None,
) -> dict[str, Any]:
    if not alert_ids and not case_ids:
        raise ValueError("Select at least one alert or SAR case for reassignment.")

    alert_result = None
    sar_result = None
    summary: list[str] = []

    if alert_ids:
        alert_result = await run_bulk_alert_actions(
            BulkAlertActionRequest(
                alert_ids=alert_ids,
                action="assign",
                actor=actor,
                assigned_to=assigned_to,
                note=note,
            )
        )
        summary.extend(alert_result.get("summary") or [])
    if case_ids:
        sar_result = await run_bulk_sar_queue_actions(
            BulkSarActionRequest(
                case_ids=case_ids,
                action="assign_owner",
                actor=actor,
                assigned_to=assigned_to,
                note=note,
            )
        )
        summary.extend(sar_result.get("summary") or [])

    return {
        "actor": actor,
        "assigned_to": assigned_to,
        "alert_result": alert_result,
        "sar_result": sar_result,
        "summary": summary or [f"Reassignment completed for {assigned_to}."],
        "generated_at": _utcnow(),
    }
