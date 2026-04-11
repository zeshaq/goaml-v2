"""
goAML-V2 case management service.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID
from uuid import uuid4

import httpx

from core.config import settings
from core.database import get_pool
from models.casework import (
    CaseCreate,
    CaseNoteCreate,
    CaseTaskCreate,
    CaseTaskUpdate,
    CaseUpdate,
    SarDraftRequest,
    SarFileRequest,
    SarWorkflowRequest,
)
from services.graph_sync import safe_resync_graph
from services.routing import resolve_case_routing, routing_metadata_payload
from services.workflow_engine import advance_sar_camunda_flow


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


def _normalize_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return []
    return []


def _metadata_tasks(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    values = _normalize_json_list(metadata.get("tasks"))
    return [item for item in values if isinstance(item, dict)]


def _metadata_notes(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    values = _normalize_json_list(metadata.get("notes"))
    return [item for item in values if isinstance(item, dict)]


def _task_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _sar_queue_bucket(status: str | None) -> str:
    status_key = str(status or "").lower()
    if status_key in {"draft", "rejected"}:
        return "draft"
    if status_key == "pending_review":
        return "review"
    if status_key == "approved":
        return "approval"
    if status_key == "filed":
        return "filed"
    return "other"


def _sar_queue_sla_hours(queue_key: str) -> float | None:
    if queue_key == "draft":
        return settings.SAR_DRAFT_SLA_HOURS
    if queue_key == "review":
        return settings.SAR_REVIEW_SLA_HOURS
    if queue_key == "approval":
        return settings.SAR_APPROVAL_SLA_HOURS
    return None


def _workflow_timestamp(metadata: dict[str, Any], *, action: str | None = None, status: str | None = None) -> datetime | None:
    history = _normalize_json_list(metadata.get("workflow_history"))
    for item in reversed(history):
        if not isinstance(item, dict):
            continue
        if action and str(item.get("action") or "") != action:
            continue
        if status and str(item.get("status") or "") != status:
            continue
        parsed = _safe_datetime(item.get("created_at"))
        if parsed:
            return parsed
    return None


def _sar_queue_owner(item: dict[str, Any], queue_key: str) -> str | None:
    owner_candidates: list[Any]
    if queue_key == "approval":
        owner_candidates = [item.get("assigned_to"), item.get("approved_by"), item.get("reviewed_by"), item.get("drafted_by")]
    elif queue_key == "review":
        owner_candidates = [item.get("assigned_to"), item.get("reviewed_by"), item.get("drafted_by")]
    elif queue_key == "draft":
        owner_candidates = [item.get("assigned_to"), item.get("drafted_by"), item.get("reviewed_by")]
    else:
        owner_candidates = [item.get("approved_by"), item.get("reviewed_by"), item.get("assigned_to"), item.get("drafted_by")]

    for candidate in owner_candidates:
        if candidate:
            return str(candidate)
    return None


def _sar_queue_age_reference(item: dict[str, Any], metadata: dict[str, Any], queue_key: str) -> datetime | None:
    if queue_key == "review":
        return (
            _workflow_timestamp(metadata, action="submit_review")
            or _workflow_timestamp(metadata, status="pending_review")
            or _safe_datetime(item.get("updated_at"))
            or _safe_datetime(item.get("drafted_at"))
            or _safe_datetime(item.get("created_at"))
        )
    if queue_key == "approval":
        return (
            _safe_datetime(item.get("approved_at"))
            or _workflow_timestamp(metadata, action="approve")
            or _workflow_timestamp(metadata, status="approved")
            or _safe_datetime(item.get("updated_at"))
            or _safe_datetime(item.get("drafted_at"))
            or _safe_datetime(item.get("created_at"))
        )
    if queue_key == "draft":
        return (
            _workflow_timestamp(metadata, action="reject") if str(item.get("sar_status") or "").lower() == "rejected" else None
        ) or _safe_datetime(item.get("updated_at")) or _safe_datetime(item.get("drafted_at")) or _safe_datetime(item.get("created_at"))
    return _safe_datetime(item.get("filed_at")) or _safe_datetime(item.get("updated_at")) or _safe_datetime(item.get("created_at"))


def _sar_queue_sla_state(age_hours: float | None, sla_hours: float | None) -> str | None:
    if age_hours is None or sla_hours is None:
        return None
    if age_hours > sla_hours:
        return "breached"
    if age_hours >= sla_hours * 0.75:
        return "due_soon"
    return "within_sla"


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _priority_rank(priority: str | None) -> int:
    value = str(priority or "").lower()
    if value == "critical":
        return 4
    if value == "high":
        return 3
    if value == "medium":
        return 2
    if value == "low":
        return 1
    return 0


def _configured_analyst_pool() -> list[str]:
    pool: list[str] = []
    for item in str(settings.SAR_AUTOBALANCE_ANALYST_POOL or "").split(","):
        name = item.strip()
        if name and name.lower() != "unassigned" and name not in pool:
            pool.append(name)
    return pool


def _resolved_analyst_pool(items: list[dict[str, Any]], analyst_pool: list[str] | None = None) -> list[str]:
    pool: list[str] = []
    for item in analyst_pool or []:
        name = str(item).strip()
        if name and name.lower() != "unassigned" and name not in pool:
            pool.append(name)
    for item in _configured_analyst_pool():
        if item not in pool:
            pool.append(item)
    for row in items:
        for candidate in [row.get("assigned_to"), row.get("reviewed_by"), row.get("approved_by"), row.get("drafted_by")]:
            name = str(candidate or "").strip()
            if name and name.lower() != "unassigned" and name not in pool:
                pool.append(name)
    return pool


async def _fetch_sar_queue_items(conn: Any) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT
            c.id AS case_id,
            c.case_ref,
            c.title AS case_title,
            c.status AS case_status,
            c.priority AS case_priority,
            c.assigned_to,
            c.primary_entity_id,
            c.primary_account_id,
            c.metadata AS case_metadata,
            COUNT(DISTINCT ca.alert_id)::int AS alert_count,
            COUNT(DISTINCT ct.transaction_id)::int AS transaction_count,
            s.id AS sar_id,
            s.sar_ref,
            s.status AS sar_status,
            s.subject_name,
            s.subject_type,
            s.subject_account,
            s.activity_type,
            s.activity_amount,
            s.drafted_by,
            s.drafted_at,
            s.reviewed_by,
            s.reviewed_at,
            s.approved_by,
            s.approved_at,
            s.filed_at,
            s.filing_ref,
            s.ai_drafted,
            s.ai_model,
            s.metadata,
            s.created_at,
            s.updated_at
        FROM sar_reports s
        JOIN cases c ON c.id = s.case_id
        LEFT JOIN case_alerts ca ON ca.case_id = c.id
        LEFT JOIN case_transactions ct ON ct.case_id = c.id
        WHERE TRUE
        GROUP BY
            c.id, c.case_ref, c.title, c.status, c.priority, c.assigned_to,
            c.primary_entity_id, c.primary_account_id, c.metadata,
            s.id, s.sar_ref, s.status, s.subject_name, s.subject_type,
            s.subject_account, s.activity_type, s.activity_amount,
            s.drafted_by, s.drafted_at, s.reviewed_by, s.reviewed_at,
            s.approved_by, s.approved_at, s.filed_at, s.filing_ref,
            s.ai_drafted, s.ai_model, s.metadata, s.created_at, s.updated_at
        ORDER BY
            CASE
                WHEN s.status = 'pending_review' THEN 0
                WHEN s.status = 'approved' THEN 1
                WHEN s.status IN ('draft', 'rejected') THEN 2
                WHEN s.status = 'filed' THEN 3
                ELSE 4
            END,
            COALESCE(s.updated_at, s.created_at) DESC,
            c.created_at DESC
        """,
    )
    return [_normalize_sar_queue_item(dict(row)) for row in rows]


def _normalize_task_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    for key in ("created_at", "updated_at", "due_at", "completed_at"):
        value = normalized.get(key)
        if isinstance(value, datetime):
            normalized[key] = value.isoformat()
    return normalized


def _normalize_note_item(item: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(item)
    value = normalized.get("created_at")
    if isinstance(value, datetime):
        normalized["created_at"] = value.isoformat()
    return normalized


async def create_case(payload: CaseCreate) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            workflow_type = "watchlist" if payload.metadata.get("entity_workflow") == "watchlist_review" else (
                "alert_investigation" if payload.alert_ids else "general"
            )
            routing = await resolve_case_routing(
                conn,
                workflow_type=workflow_type,
                primary_entity_id=payload.primary_entity_id,
                primary_account_id=payload.primary_account_id,
                alert_ids=payload.alert_ids,
                transaction_ids=payload.transaction_ids,
                preferred_assignee=payload.assigned_to,
                existing_metadata=payload.metadata,
            )
            metadata = dict(payload.metadata)
            metadata["routing"] = routing_metadata_payload(routing, workflow_type=workflow_type, source="create_case")
            row = await conn.fetchrow(
                """
                INSERT INTO cases (
                    title, description, priority, assigned_to, created_by,
                    primary_account_id, primary_entity_id, sar_required, metadata
                ) VALUES ($1, $2, $3::case_priority, $4, $5, $6, $7, $8, $9)
                RETURNING *
                """,
                payload.title,
                payload.description,
                payload.priority.value,
                payload.assigned_to or routing.get("assigned_to"),
                payload.created_by,
                payload.primary_account_id,
                payload.primary_entity_id,
                payload.sar_required,
                json.dumps(metadata),
            )
            case_id = row["id"]

            for alert_id in payload.alert_ids:
                await conn.execute(
                    """
                    INSERT INTO case_alerts (case_id, alert_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                    """,
                    case_id,
                    alert_id,
                )
                await conn.execute(
                    "UPDATE alerts SET case_id = $1 WHERE id = $2",
                    case_id,
                    alert_id,
                )

            for transaction_id in payload.transaction_ids:
                await conn.execute(
                    """
                    INSERT INTO case_transactions (case_id, transaction_id)
                    VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                    """,
                    case_id,
                    transaction_id,
                )

            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, 'created', $2, $3, $4)
                """,
                case_id,
                payload.created_by,
                "Case created",
                json.dumps({
                    "alert_ids": [str(i) for i in payload.alert_ids],
                    "transaction_ids": [str(i) for i in payload.transaction_ids],
                    "routing": metadata.get("routing"),
                }),
            )

    await safe_resync_graph(clear_existing=True)
    return await get_case_detail(case_id)


async def list_cases(limit: int, offset: int, status: str | None) -> list[dict[str, Any]]:
    pool = get_pool()
    args: list[Any] = []
    where = "1=1"
    if status:
        where = "c.status = $1::case_status"
        args.append(status)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                c.id, c.case_ref, c.title, c.status, c.priority, c.assigned_to,
                c.sar_required, c.created_at,
                COUNT(DISTINCT ca.alert_id)::int AS alert_count,
                COUNT(DISTINCT ct.transaction_id)::int AS transaction_count
            FROM cases c
            LEFT JOIN case_alerts ca ON ca.case_id = c.id
            LEFT JOIN case_transactions ct ON ct.case_id = c.id
            WHERE {where}
            GROUP BY c.id
            ORDER BY c.created_at DESC
            LIMIT ${len(args) + 1} OFFSET ${len(args) + 2}
            """,
            *args, limit, offset,
        )
    return [dict(r) for r in rows]


async def get_case_detail(case_id: UUID) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        case_row = await conn.fetchrow("SELECT * FROM cases WHERE id = $1", case_id)
        if not case_row:
            return None

        alert_rows = await conn.fetch(
            "SELECT alert_id FROM case_alerts WHERE case_id = $1 ORDER BY added_at",
            case_id,
        )
        txn_rows = await conn.fetch(
            "SELECT transaction_id FROM case_transactions WHERE case_id = $1 ORDER BY added_at",
            case_id,
        )

    result = dict(case_row)
    result["alert_ids"] = [r["alert_id"] for r in alert_rows]
    result["transaction_ids"] = [r["transaction_id"] for r in txn_rows]
    result["ai_risk_factors"] = _normalize_json_list(result.get("ai_risk_factors"))
    result["metadata"] = _normalize_json_dict(result.get("metadata"))
    return result


async def list_case_events(
    case_id: UUID,
    limit: int = 100,
    offset: int = 0,
    order: str = "asc",
) -> list[dict[str, Any]] | None:
    pool = get_pool()
    sort_order = "ASC" if order.lower() == "asc" else "DESC"

    async with pool.acquire() as conn:
        case_exists = await conn.fetchval("SELECT 1 FROM cases WHERE id = $1", case_id)
        if not case_exists:
            return None

        rows = await conn.fetch(
            f"""
            SELECT id, case_id, event_type, actor, detail, metadata, created_at
            FROM case_events
            WHERE case_id = $1
            ORDER BY created_at {sort_order}, id {sort_order}
            LIMIT $2 OFFSET $3
            """,
            case_id,
            limit,
            offset,
        )

    results = [dict(row) for row in rows]
    for row in results:
        row["metadata"] = _normalize_json_dict(row.get("metadata"))
    return results


async def get_case_sar(case_id: UUID) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        case_row = await conn.fetchrow("SELECT sar_id FROM cases WHERE id = $1", case_id)
        if not case_row:
            return None
        if not case_row["sar_id"]:
            return {}

        sar_row = await conn.fetchrow(
            "SELECT * FROM sar_reports WHERE id = $1",
            case_row["sar_id"],
        )
        if not sar_row:
            return {}

    result = dict(sar_row)
    result["metadata"] = _normalize_json_dict(result.get("metadata"))
    result["activity_amount"] = float(result["activity_amount"]) if result.get("activity_amount") is not None else None
    return result


def _normalize_sar_queue_item(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    metadata = _normalize_json_dict(item.pop("metadata", {}))
    item["case_metadata"] = _normalize_json_dict(item.pop("case_metadata", {}))
    item["activity_amount"] = float(item["activity_amount"]) if item.get("activity_amount") is not None else None
    item["latest_workflow_note"] = metadata.get("latest_workflow_note") or metadata.get("latest_rejection_reason")
    item["workflow_step_count"] = len(_normalize_json_list(metadata.get("workflow_history")))
    queue_key = _sar_queue_bucket(item.get("sar_status"))
    queue_owner = _sar_queue_owner(item, queue_key)
    age_reference = _sar_queue_age_reference(item, metadata, queue_key)
    sla_hours = _sar_queue_sla_hours(queue_key)
    age_hours = None
    sla_due_at = None
    if age_reference:
        now = datetime.now(timezone.utc)
        age_hours = round(max((now - age_reference).total_seconds(), 0) / 3600, 2)
        if sla_hours is not None:
            sla_due_at = age_reference + timedelta(hours=sla_hours)
    item["queue_owner"] = queue_owner
    item["age_hours"] = age_hours
    item["sla_hours"] = sla_hours
    item["sla_due_at"] = sla_due_at
    item["sla_status"] = _sar_queue_sla_state(age_hours, sla_hours)
    return item


def _build_sar_queue_analytics(items: list[dict[str, Any]]) -> dict[str, Any]:
    generated_at = datetime.now(timezone.utc)
    queue_defs = {
        "draft": "Draft / Rejected",
        "review": "Pending Review",
        "approval": "Approved / Ready to File",
    }

    queue_sla: list[dict[str, Any]] = []
    overall_breached = 0
    overall_due_soon = 0

    for queue_key, label in queue_defs.items():
        queue_items = [item for item in items if _sar_queue_bucket(item.get("sar_status")) == queue_key]
        ages = [float(item["age_hours"]) for item in queue_items if item.get("age_hours") is not None]
        breached_count = sum(1 for item in queue_items if item.get("sla_status") == "breached")
        due_soon_count = sum(1 for item in queue_items if item.get("sla_status") == "due_soon")
        overall_breached += breached_count
        overall_due_soon += due_soon_count
        queue_sla.append(
            {
                "queue": queue_key,
                "label": label,
                "item_count": len(queue_items),
                "breached_count": breached_count,
                "due_soon_count": due_soon_count,
                "avg_age_hours": _average(ages),
                "oldest_age_hours": round(max(ages), 2) if ages else None,
                "sla_hours": _sar_queue_sla_hours(queue_key),
            }
        )

    owner_map: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "owner": "unassigned",
            "display_name": "Unassigned",
            "draft_count": 0,
            "review_count": 0,
            "approval_count": 0,
            "filed_count": 0,
            "breached_count": 0,
            "high_priority_count": 0,
            "_ages": [],
        }
    )

    for item in items:
        queue_key = _sar_queue_bucket(item.get("sar_status"))
        owner = item.get("queue_owner") or "unassigned"
        workload = owner_map[owner]
        workload["owner"] = owner
        workload["display_name"] = "Unassigned" if owner == "unassigned" else owner
        if queue_key == "draft":
            workload["draft_count"] += 1
        elif queue_key == "review":
            workload["review_count"] += 1
        elif queue_key == "approval":
            workload["approval_count"] += 1
        elif queue_key == "filed":
            workload["filed_count"] += 1
        if item.get("sla_status") == "breached":
            workload["breached_count"] += 1
        if str(item.get("case_priority") or "").lower() in {"high", "critical"} and queue_key in {"draft", "review", "approval"}:
            workload["high_priority_count"] += 1
        if item.get("age_hours") is not None and queue_key in {"draft", "review", "approval"}:
            workload["_ages"].append(float(item["age_hours"]))

    owner_items: list[dict[str, Any]] = []
    for value in owner_map.values():
        ages = value.pop("_ages")
        value["avg_age_hours"] = _average(ages)
        value["oldest_age_hours"] = round(max(ages), 2) if ages else None
        owner_items.append(value)

    owner_items.sort(
        key=lambda item: (
            -(item["review_count"] + item["approval_count"] + item["draft_count"]),
            -item["breached_count"],
            -item["high_priority_count"],
            item["display_name"].lower(),
        )
    )

    active_owner_count = sum(
        1 for item in owner_items if (item["review_count"] + item["approval_count"] + item["draft_count"]) > 0
    )
    summary = [
        f"{overall_breached} active SAR items are currently outside SLA.",
        f"{overall_due_soon} active SAR items are due soon against configured thresholds.",
    ]
    if owner_items:
        busiest = owner_items[0]
        active_count = busiest["review_count"] + busiest["approval_count"] + busiest["draft_count"]
        summary.append(f"{busiest['display_name']} currently owns {active_count} active SAR items.")

    return {
        "generated_at": generated_at,
        "overall_breached_count": overall_breached,
        "overall_due_soon_count": overall_due_soon,
        "active_owner_count": active_owner_count,
        "queue_sla": queue_sla,
        "owner_workloads": owner_items[:8],
        "summary": summary,
    }


async def list_sar_queue(
    *,
    queue: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    queue_key = queue.lower()
    if queue_key not in {"draft", "review", "approval", "filed", "all"}:
        raise ValueError(f"Unsupported SAR queue: {queue}")

    pool = get_pool()
    async with pool.acquire() as conn:
        all_items = await _fetch_sar_queue_items(conn)
    counts = {
        "draft": sum(1 for item in all_items if _sar_queue_bucket(item.get("sar_status")) == "draft"),
        "review": sum(1 for item in all_items if _sar_queue_bucket(item.get("sar_status")) == "review"),
        "approval": sum(1 for item in all_items if _sar_queue_bucket(item.get("sar_status")) == "approval"),
        "filed": sum(1 for item in all_items if _sar_queue_bucket(item.get("sar_status")) == "filed"),
        "total": len(all_items),
    }
    if queue_key == "all":
        filtered_items = all_items
    else:
        filtered_items = [item for item in all_items if _sar_queue_bucket(item.get("sar_status")) == queue_key]

    return {
        "queue": queue_key,
        "counts": counts,
        "analytics": _build_sar_queue_analytics(all_items),
        "items": filtered_items[offset : offset + limit],
    }


async def rebalance_sar_queue(
    *,
    actor: str | None,
    queue: str,
    limit: int,
    analyst_pool: list[str] | None = None,
    breached_only: bool = True,
    include_due_soon: bool | None = None,
    max_items_per_owner: int | None = None,
    min_workload_gap: int | None = None,
) -> dict[str, Any]:
    queue_key = queue.lower()
    if queue_key not in {"draft", "review", "approval", "all"}:
        raise ValueError(f"Unsupported SAR rebalance queue: {queue}")

    actor_name = actor or "sar-queue-automation"
    due_soon_enabled = settings.SAR_AUTOBALANCE_INCLUDE_DUE_SOON if include_due_soon is None else include_due_soon
    effective_limit = min(limit, settings.SAR_AUTOBALANCE_BATCH_LIMIT)
    owner_cap = max_items_per_owner or settings.SAR_AUTOBALANCE_MAX_ITEMS_PER_OWNER
    workload_gap = min_workload_gap or settings.SAR_AUTOBALANCE_MIN_WORKLOAD_GAP

    pool = get_pool()
    moved_items: list[dict[str, Any]] = []

    async with pool.acquire() as conn:
        items = await _fetch_sar_queue_items(conn)
        active_queue_keys = {"draft", "review", "approval"} if queue_key == "all" else {queue_key}
        active_items = [item for item in items if _sar_queue_bucket(item.get("sar_status")) in active_queue_keys]
        owner_pool = _resolved_analyst_pool(active_items, analyst_pool)
        if not owner_pool:
            return {
                "queue": queue_key,
                "processed_count": 0,
                "reassigned_count": 0,
                "owner_count": 0,
                "items": [],
                "summary": ["No analyst pool is available for SAR queue rebalancing."],
                "generated_at": datetime.now(timezone.utc),
            }

        workload_map = {owner: 0 for owner in owner_pool}
        for item in active_items:
            owner = item.get("queue_owner")
            if owner in workload_map:
                workload_map[owner] += 1

        def _eligible_for_rebalance(item: dict[str, Any]) -> bool:
            current_queue = _sar_queue_bucket(item.get("sar_status"))
            if current_queue not in active_queue_keys:
                return False
            if item.get("case_status") == "closed":
                return False
            if breached_only:
                if item.get("sla_status") == "breached":
                    return True
                if due_soon_enabled and item.get("sla_status") == "due_soon":
                    return True
                owner = item.get("queue_owner")
                return (not owner) or (owner not in workload_map)
            return True

        candidates = [item for item in active_items if _eligible_for_rebalance(item)]
        candidates.sort(
            key=lambda item: (
                0 if not item.get("queue_owner") or item.get("queue_owner") not in workload_map else 1,
                0 if item.get("sla_status") == "breached" else 1 if item.get("sla_status") == "due_soon" else 2,
                -_priority_rank(item.get("case_priority")),
                -(item.get("age_hours") or 0.0),
                str(item.get("case_ref") or ""),
            )
        )

        async with conn.transaction():
            for item in candidates:
                if len(moved_items) >= effective_limit:
                    break

                previous_owner = item.get("queue_owner")
                routing = await resolve_case_routing(
                    conn,
                    workflow_type="sar_review",
                    primary_entity_id=item.get("primary_entity_id"),
                    primary_account_id=item.get("primary_account_id"),
                    preferred_assignee=item.get("queue_owner") or item.get("assigned_to"),
                    existing_metadata=item.get("case_metadata"),
                )
                target_pool = [owner for owner in routing.get("eligible_analysts", []) if owner in owner_pool] or owner_pool
                previous_count = workload_map.get(previous_owner, owner_cap + workload_gap if previous_owner else 0)
                ranked_targets = sorted(target_pool, key=lambda owner: (workload_map.get(owner, 0), owner.lower()))
                target_owner = ranked_targets[0] if ranked_targets else None
                if not target_owner:
                    break
                target_count = workload_map.get(target_owner, 0)

                should_move = False
                if not previous_owner or previous_owner not in workload_map:
                    should_move = True
                elif target_owner != previous_owner and previous_count > owner_cap:
                    should_move = True
                elif target_owner != previous_owner and previous_count - target_count >= workload_gap:
                    should_move = True
                elif target_owner != previous_owner and item.get("sla_status") == "breached" and previous_count > target_count:
                    should_move = True

                if not should_move or target_owner == previous_owner:
                    continue

                next_case_metadata = dict(item.get("case_metadata") or {})
                next_case_metadata["routing"] = routing_metadata_payload(
                    {
                        **routing,
                        "assigned_to": target_owner,
                    },
                    workflow_type="sar_review",
                    source="sar_rebalance",
                )
                await conn.execute(
                    """
                    UPDATE cases
                    SET assigned_to = $2, metadata = $3::jsonb, updated_at = NOW()
                    WHERE id = $1
                    """,
                    item["case_id"],
                    target_owner,
                    json.dumps(next_case_metadata),
                )
                await conn.execute(
                    """
                    INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                    VALUES ($1, 'sar_workload_rebalanced', $2, $3, $4::jsonb)
                    """,
                    item["case_id"],
                    actor_name,
                    f"SAR workload rebalanced to {target_owner}",
                    json.dumps(
                        {
                            "sar_id": str(item["sar_id"]),
                            "sar_ref": item["sar_ref"],
                            "queue": _sar_queue_bucket(item.get("sar_status")),
                            "previous_owner": previous_owner,
                            "new_owner": target_owner,
                            "sla_status": item.get("sla_status"),
                            "age_hours": item.get("age_hours"),
                            "team_key": routing.get("team_key"),
                            "region_key": routing.get("region_key"),
                        }
                    ),
                )

                if previous_owner in workload_map:
                    workload_map[previous_owner] = max(workload_map[previous_owner] - 1, 0)
                workload_map[target_owner] = workload_map.get(target_owner, 0) + 1
                moved_items.append(
                    {
                        "case_id": item["case_id"],
                        "case_ref": item["case_ref"],
                        "sar_id": item["sar_id"],
                        "sar_ref": item["sar_ref"],
                        "queue": _sar_queue_bucket(item.get("sar_status")),
                        "previous_owner": previous_owner,
                        "new_owner": target_owner,
                        "previous_active_count": previous_count,
                        "new_owner_active_count": workload_map[target_owner],
                        "sla_status": item.get("sla_status"),
                        "case_priority": item.get("case_priority"),
                        "note": f"Reassigned from {previous_owner or 'unassigned'} to {target_owner} for {routing.get('team_label')}.",
                    }
                )

    if moved_items:
        await safe_resync_graph(clear_existing=True)

    summary = [
        f"Processed {len(candidates)} eligible SAR queue items across the {queue_key} queue.",
        f"Reassigned {len(moved_items)} SAR items to rebalance owner workload.",
        f"Analyst pool size: {len(_resolved_analyst_pool(active_items, analyst_pool))}.",
    ]
    if moved_items:
        summary.append(
            f"Most recent reassignment moved {moved_items[-1]['case_ref']} to {moved_items[-1]['new_owner']}."
        )

    return {
        "queue": queue_key,
        "processed_count": len(candidates),
        "reassigned_count": len(moved_items),
        "owner_count": len(_resolved_analyst_pool(active_items, analyst_pool)),
        "items": moved_items,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc),
    }


async def list_case_tasks(case_id: UUID) -> list[dict[str, Any]] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT metadata FROM cases WHERE id = $1", case_id)
        if not row:
            return None
    metadata = _normalize_json_dict(row["metadata"])
    tasks = [_normalize_task_item(item) for item in _metadata_tasks(metadata)]
    tasks.sort(key=lambda item: (item.get("status") == "done", item.get("priority") != "high", item.get("created_at") or ""))
    return tasks


async def add_case_task(case_id: UUID, payload: CaseTaskCreate) -> dict[str, Any] | None:
    pool = get_pool()
    task = {
        "id": str(uuid4()),
        "title": payload.title,
        "description": payload.description,
        "status": "open",
        "priority": payload.priority.value,
        "assigned_to": payload.assigned_to,
        "created_by": payload.created_by,
        "note": payload.note,
        "created_at": _task_now_iso(),
        "updated_at": _task_now_iso(),
        "due_at": payload.due_at.isoformat() if payload.due_at else None,
        "completed_at": None,
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT metadata FROM cases WHERE id = $1 FOR UPDATE", case_id)
            if not row:
                return None
            metadata = _normalize_json_dict(row["metadata"])
            tasks = _metadata_tasks(metadata)
            tasks.append(task)
            metadata["tasks"] = tasks[-100:]
            await conn.execute(
                "UPDATE cases SET metadata = $2::jsonb, updated_at = NOW() WHERE id = $1",
                case_id,
                json.dumps(metadata),
            )
            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, 'task_created', $2, $3, $4)
                """,
                case_id,
                payload.created_by,
                f"Task created: {payload.title}",
                json.dumps({"task_id": task["id"], "assigned_to": payload.assigned_to, "priority": payload.priority.value}),
            )
    return _normalize_task_item(task)


async def update_case_task(case_id: UUID, task_id: UUID, payload: CaseTaskUpdate) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT metadata FROM cases WHERE id = $1 FOR UPDATE", case_id)
            if not row:
                return None
            metadata = _normalize_json_dict(row["metadata"])
            tasks = _metadata_tasks(metadata)
            updated_task = None
            for task in tasks:
                if str(task.get("id")) != str(task_id):
                    continue
                if payload.status is not None:
                    task["status"] = payload.status.value
                    if payload.status.value == "done":
                        task["completed_at"] = _task_now_iso()
                if payload.assigned_to is not None:
                    task["assigned_to"] = payload.assigned_to
                if payload.note is not None:
                    task["note"] = payload.note
                task["updated_at"] = _task_now_iso()
                updated_task = task
                break

            if not updated_task:
                return {}

            metadata["tasks"] = tasks
            await conn.execute(
                "UPDATE cases SET metadata = $2::jsonb, updated_at = NOW() WHERE id = $1",
                case_id,
                json.dumps(metadata),
            )
            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, 'task_updated', $2, $3, $4)
                """,
                case_id,
                payload.actor,
                f"Task updated: {updated_task.get('title')}",
                json.dumps({"task_id": str(task_id), "status": updated_task.get("status"), "assigned_to": updated_task.get("assigned_to")}),
            )

    return _normalize_task_item(updated_task)


async def list_case_notes(case_id: UUID) -> list[dict[str, Any]] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT metadata FROM cases WHERE id = $1", case_id)
        if not row:
            return None
    metadata = _normalize_json_dict(row["metadata"])
    notes = [_normalize_note_item(item) for item in _metadata_notes(metadata)]
    notes.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return notes


async def add_case_note(case_id: UUID, payload: CaseNoteCreate) -> dict[str, Any] | None:
    pool = get_pool()
    note = {
        "id": str(uuid4()),
        "author": payload.author,
        "text": payload.text,
        "created_at": _task_now_iso(),
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT metadata FROM cases WHERE id = $1 FOR UPDATE", case_id)
            if not row:
                return None
            metadata = _normalize_json_dict(row["metadata"])
            notes = _metadata_notes(metadata)
            notes.append(note)
            metadata["notes"] = notes[-150:]
            await conn.execute(
                "UPDATE cases SET metadata = $2::jsonb, updated_at = NOW() WHERE id = $1",
                case_id,
                json.dumps(metadata),
            )
            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, 'note_added', $2, $3, $4)
                """,
                case_id,
                payload.author,
                "Analyst note added",
                json.dumps({"note_id": note["id"]}),
            )

    return _normalize_note_item(note)


async def update_case(case_id: UUID, payload: CaseUpdate) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow("SELECT * FROM cases WHERE id = $1", case_id)
            if not current:
                return None

            metadata = _normalize_json_dict(current["metadata"])
            status_value = payload.status.value if payload.status else current["status"]
            priority_value = payload.priority.value if payload.priority else current["priority"]
            ai_risk_factors = (
                payload.ai_risk_factors
                if payload.ai_risk_factors is not None
                else _normalize_json_list(current["ai_risk_factors"])
            )
            if payload.status and payload.status.value == "closed":
                closed_by = payload.closed_by or current["closed_by"]
            else:
                closed_by = current["closed_by"] if payload.closed_by is None else payload.closed_by

            await conn.execute(
                """
                UPDATE cases
                SET
                    status = $2::case_status,
                    priority = $3::case_priority,
                    assigned_to = COALESCE($4, assigned_to),
                    closed_by = $5,
                    closed_at = CASE WHEN $2::case_status = 'closed' THEN NOW() ELSE NULL END,
                    ai_summary = COALESCE($6, ai_summary),
                    ai_risk_factors = $7,
                    sar_required = COALESCE($8, sar_required),
                    metadata = $9::jsonb
                WHERE id = $1
                """,
                case_id,
                status_value,
                priority_value,
                payload.assigned_to,
                closed_by,
                payload.ai_summary,
                ai_risk_factors,
                payload.sar_required,
                json.dumps({
                    **metadata,
                    "routing": (
                        {
                            **_normalize_json_dict(metadata.get("routing")),
                            "assigned_to": payload.assigned_to,
                        }
                        if payload.assigned_to is not None
                        else metadata.get("routing")
                    ),
                }),
            )

            for alert_id in payload.add_alert_ids:
                await conn.execute(
                    "INSERT INTO case_alerts (case_id, alert_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    case_id,
                    alert_id,
                )
                await conn.execute("UPDATE alerts SET case_id = $1 WHERE id = $2", case_id, alert_id)

            for transaction_id in payload.add_transaction_ids:
                await conn.execute(
                    "INSERT INTO case_transactions (case_id, transaction_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    case_id,
                    transaction_id,
                )

            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, $2, $3, $4, $5)
                """,
                case_id,
                "updated",
                payload.event_actor,
                payload.event_detail or "Case updated",
                json.dumps({
                    "status": payload.status.value if payload.status else None,
                    "priority": payload.priority.value if payload.priority else None,
                    "added_alert_ids": [str(i) for i in payload.add_alert_ids],
                    "added_transaction_ids": [str(i) for i in payload.add_transaction_ids],
                }),
            )

    await safe_resync_graph(clear_existing=True)
    return await get_case_detail(case_id)


async def draft_sar(case_id: UUID, payload: SarDraftRequest) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        case_row = await conn.fetchrow("SELECT * FROM cases WHERE id = $1", case_id)
        if not case_row:
            return None

        txns = await conn.fetch(
            """
            SELECT t.*
            FROM case_transactions ct
            JOIN transactions t ON t.id = ct.transaction_id
            WHERE ct.case_id = $1
            ORDER BY t.transacted_at
            """,
            case_id,
        )
        alerts = await conn.fetch(
            """
            SELECT alert_ref, alert_type, severity, title
            FROM case_alerts ca
            JOIN alerts a ON a.id = ca.alert_id
            WHERE ca.case_id = $1
            ORDER BY a.created_at
            """,
            case_id,
        )

    amount_values = [float(t["amount_usd"] or t["amount"] or 0) for t in txns]
    activity_amount = sum(amount_values) if amount_values else None
    activity_from = txns[0]["transacted_at"] if txns else None
    activity_to = txns[-1]["transacted_at"] if txns else None
    subject_account = payload.subject_account or _first_nonempty([case_row["primary_account_id"]])
    subject_name = payload.subject_name or _guess_subject_name(txns, case_row["title"])
    activity_type = payload.activity_type or _infer_activity_type(txns)

    narrative, ai_drafted, ai_model = await _generate_sar_narrative(case_row, txns, alerts, payload)

    async with pool.acquire() as conn:
        async with conn.transaction():
            sar_ref = _build_sar_ref()
            sar = await conn.fetchrow(
                """
                INSERT INTO sar_reports (
                    sar_ref, case_id, status, subject_name, subject_type, subject_account,
                    narrative, activity_type, activity_amount, activity_from, activity_to,
                    drafted_by, drafted_at, ai_drafted, ai_model, metadata
                ) VALUES (
                    $1, $2, 'draft', $3, $4::entity_type, $5,
                    $6, $7, $8, $9, $10,
                    $11, NOW(), $12, $13, $14
                )
                RETURNING *
                """,
                sar_ref,
                case_id,
                subject_name,
                payload.subject_type or "unknown",
                str(subject_account) if subject_account else None,
                narrative,
                activity_type,
                activity_amount,
                activity_from,
                activity_to,
                payload.drafted_by,
                ai_drafted,
                ai_model,
                json.dumps({
                    "alert_refs": [a["alert_ref"] for a in alerts],
                    "transaction_count": len(txns),
                    "draft_mode": "llm" if ai_drafted else "template_fallback",
                }),
            )

            await conn.execute(
                """
                UPDATE cases
                SET sar_id = $2, sar_required = TRUE, status = 'pending_sar'
                WHERE id = $1
                """,
                case_id,
                sar["id"],
            )

            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, 'sar_drafted', $2, $3, $4)
                """,
                case_id,
                payload.drafted_by,
                "SAR draft created",
                json.dumps({"sar_id": str(sar["id"]), "sar_ref": sar["sar_ref"]}),
            )

    result = dict(sar)
    result["metadata"] = _normalize_json_dict(result.get("metadata"))
    result["activity_amount"] = float(result["activity_amount"]) if result.get("activity_amount") is not None else None
    await safe_resync_graph(clear_existing=True)
    return result


async def advance_sar_workflow(case_id: UUID, payload: SarWorkflowRequest) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            case_row = await conn.fetchrow("SELECT id, case_ref, sar_id FROM cases WHERE id = $1", case_id)
            if not case_row:
                return None
            if not case_row["sar_id"]:
                return None

            sar_row = await conn.fetchrow("SELECT * FROM sar_reports WHERE id = $1 FOR UPDATE", case_row["sar_id"])
            if not sar_row:
                return None

            current_status = str(sar_row["status"])
            actor = payload.actor
            note = (payload.note or "").strip() or None
            metadata = _normalize_json_dict(sar_row["metadata"])
            history = _normalize_json_list(metadata.get("workflow_history"))

            if payload.action.value == "submit_review":
                if current_status not in {"draft", "rejected"}:
                    raise ValueError("Only drafted or rejected SARs can be submitted for review.")
                next_status = "pending_review"
                event_type = "sar_submitted_for_review"
                detail = "SAR submitted for review"
                update_sql = """
                    UPDATE sar_reports
                    SET
                        status = 'pending_review',
                        metadata = $2::jsonb
                    WHERE id = $1
                    RETURNING *
                """
                update_args = [case_row["sar_id"], None]
            elif payload.action.value == "approve":
                if current_status not in {"draft", "pending_review"}:
                    raise ValueError("Only drafted or pending-review SARs can be approved.")
                next_status = "approved"
                event_type = "sar_approved"
                detail = "SAR approved"
                update_sql = """
                    UPDATE sar_reports
                    SET
                        status = 'approved',
                        reviewed_by = COALESCE(reviewed_by, $2),
                        reviewed_at = COALESCE(reviewed_at, CASE WHEN $2 IS NOT NULL THEN NOW() ELSE NULL END),
                        approved_by = $3,
                        approved_at = NOW(),
                        metadata = $4::jsonb
                    WHERE id = $1
                    RETURNING *
                """
                update_args = [case_row["sar_id"], actor, actor, None]
            elif payload.action.value == "reject":
                if current_status not in {"draft", "pending_review", "approved"}:
                    raise ValueError("Only drafted, pending-review, or approved SARs can be rejected.")
                next_status = "rejected"
                event_type = "sar_rejected"
                detail = "SAR rejected for revision"
                update_sql = """
                    UPDATE sar_reports
                    SET
                        status = 'rejected',
                        reviewed_by = COALESCE($2, reviewed_by),
                        reviewed_at = COALESCE(reviewed_at, CASE WHEN $2 IS NOT NULL THEN NOW() ELSE NULL END),
                        approved_by = NULL,
                        approved_at = NULL,
                        metadata = $3::jsonb
                    WHERE id = $1
                    RETURNING *
                """
                update_args = [case_row["sar_id"], actor, None]
            else:
                raise ValueError(f"Unsupported SAR action: {payload.action.value}")

            history.append(
                {
                    "action": payload.action.value,
                    "actor": actor,
                    "note": note,
                    "created_at": _task_now_iso(),
                    "status": next_status,
                }
            )
            metadata["workflow_history"] = history[-40:]
            metadata["latest_workflow_note"] = note
            if payload.action.value == "reject":
                metadata["latest_rejection_reason"] = note
            update_args[-1] = json.dumps(metadata)

            sar = await conn.fetchrow(update_sql, *update_args)
            if not sar:
                return None

            case_status = "reviewing" if payload.action.value == "reject" else "pending_sar"
            await conn.execute(
                "UPDATE cases SET status = $2::case_status, updated_at = NOW() WHERE id = $1",
                case_id,
                case_status,
            )
            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, $2, $3, $4, $5)
                """,
                case_id,
                event_type,
                actor,
                detail,
                json.dumps({"sar_id": str(sar["id"]), "sar_ref": sar["sar_ref"], "note": note, "status": next_status}),
            )

    result = dict(sar)
    result["metadata"] = _normalize_json_dict(result.get("metadata"))
    result["activity_amount"] = float(result["activity_amount"]) if result.get("activity_amount") is not None else None
    await safe_resync_graph(clear_existing=True)
    await advance_sar_camunda_flow(case_id, action=payload.action.value, actor=actor, note=note)
    return result


async def file_sar(case_id: UUID, payload: SarFileRequest) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            case_row = await conn.fetchrow("SELECT id, case_ref, sar_id FROM cases WHERE id = $1", case_id)
            if not case_row:
                return None
            if not case_row["sar_id"]:
                return None

            filing_ref = payload.filing_ref or _build_filing_ref()
            actor = payload.filed_by or payload.approved_by or payload.reviewed_by

            sar = await conn.fetchrow(
                "SELECT * FROM sar_reports WHERE id = $1 FOR UPDATE",
                case_row["sar_id"],
            )
            if not sar:
                return None
            if str(sar["status"]) != "approved":
                raise ValueError("SAR must be approved before it can be filed.")

            metadata = _normalize_json_dict(sar["metadata"])
            history = _normalize_json_list(metadata.get("workflow_history"))
            history.append(
                {
                    "action": "filed",
                    "actor": actor,
                    "note": payload.filing_ref,
                    "created_at": _task_now_iso(),
                    "status": "filed",
                }
            )
            metadata["workflow_history"] = history[-40:]

            sar = await conn.fetchrow(
                """
                UPDATE sar_reports
                SET
                    status = 'filed',
                    reviewed_by = COALESCE($2, reviewed_by),
                    reviewed_at = COALESCE(reviewed_at, CASE WHEN $2 IS NOT NULL THEN NOW() ELSE NULL END),
                    approved_by = COALESCE($3, approved_by),
                    approved_at = COALESCE(approved_at, CASE WHEN $3 IS NOT NULL THEN NOW() ELSE NULL END),
                    filed_at = NOW(),
                    filing_ref = $4,
                    metadata = $5::jsonb
                WHERE id = $1
                RETURNING *
                """,
                case_row["sar_id"],
                payload.reviewed_by,
                payload.approved_by or payload.filed_by,
                filing_ref,
                json.dumps(metadata),
            )
            if not sar:
                return None

            await conn.execute(
                """
                UPDATE cases
                SET status = 'sar_filed', updated_at = NOW()
                WHERE id = $1
                """,
                case_id,
            )

            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, 'sar_filed', $2, $3, $4)
                """,
                case_id,
                actor,
                "SAR filed",
                json.dumps({"sar_id": str(sar["id"]), "sar_ref": sar["sar_ref"], "filing_ref": filing_ref}),
            )

    result = dict(sar)
    result["metadata"] = _normalize_json_dict(result.get("metadata"))
    result["activity_amount"] = float(result["activity_amount"]) if result.get("activity_amount") is not None else None
    await safe_resync_graph(clear_existing=True)
    return result


def _infer_activity_type(txns: list[Any]) -> str | None:
    if not txns:
        return None
    return str(txns[0]["transaction_type"]).replace("_", " ")


def _guess_subject_name(txns: list[Any], case_title: str) -> str | None:
    if txns:
        return txns[0]["sender_name"] or txns[0]["sender_account_ref"]
    return case_title


def _first_nonempty(values: list[Any]) -> Any:
    for value in values:
        if value:
            return value
    return None


def _build_sar_narrative(case_row: Any, txns: list[Any], alerts: list[Any], payload: SarDraftRequest) -> str:
    total_amount = sum(float(t["amount_usd"] or t["amount"] or 0) for t in txns)
    start = txns[0]["transacted_at"] if txns else None
    end = txns[-1]["transacted_at"] if txns else None
    alert_summary = ", ".join(f"{a['alert_ref']} ({a['alert_type']})" for a in alerts) if alerts else "no linked alerts"
    subject = payload.subject_name or _guess_subject_name(txns, case_row["title"]) or "the subject"
    lines = [
        f"This SAR draft relates to case {case_row['case_ref']} concerning {subject}.",
        f"The case is currently categorized as {case_row['priority']} priority with status {case_row['status']}.",
        f"A total of {len(txns)} linked transactions were reviewed, with an aggregate value of ${total_amount:,.2f}.",
    ]
    if start and end:
        lines.append(f"The reviewed activity occurred between {start} and {end}.")
    if alerts:
        lines.append(f"Associated alert activity includes {alert_summary}.")
    lines.append(
        "Based on the available transaction and alert evidence, the activity warrants analyst review for potential suspicious behavior, including unusual transaction patterns, sanctions exposure, or other AML risk indicators."
    )
    return " ".join(lines)


async def _generate_sar_narrative(
    case_row: Any,
    txns: list[Any],
    alerts: list[Any],
    payload: SarDraftRequest,
) -> tuple[str, bool, str]:
    fallback = _build_sar_narrative(case_row, txns, alerts, payload)
    prompt = _build_sar_prompt(case_row, txns, alerts, payload)
    url = f"{settings.LLM_PRIMARY_URL.rstrip('/')}/chat/completions"
    body = {
        "model": settings.LLM_PRIMARY_MODEL,
        "temperature": 0.2,
        "max_tokens": 700,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You draft concise, professional Suspicious Activity Report narratives for AML analysts. "
                    "Write in an objective compliance tone, avoid bullet points, and focus on factual suspicious activity, "
                    "timing, amounts, counterparties, and why the activity warrants filing."
                ),
            },
            {"role": "user", "content": prompt},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        narrative = str(content).strip()
        if not narrative:
            return fallback, False, "template-v1"
        return narrative, True, settings.LLM_PRIMARY_MODEL
    except Exception:
        return fallback, False, "template-v1"


def _build_sar_prompt(case_row: Any, txns: list[Any], alerts: list[Any], payload: SarDraftRequest) -> str:
    tx_lines: list[str] = []
    for txn in txns[:10]:
        tx_lines.append(
            " | ".join(
                [
                    f"ref={txn.get('transaction_ref')}",
                    f"when={txn.get('transacted_at')}",
                    f"type={txn.get('transaction_type')}",
                    f"amount_usd={txn.get('amount_usd') or txn.get('amount')}",
                    f"sender={txn.get('sender_name') or txn.get('sender_account_ref')}",
                    f"receiver={txn.get('receiver_name') or txn.get('receiver_account_ref')}",
                    f"risk_score={txn.get('risk_score')}",
                    f"risk_level={txn.get('risk_level')}",
                ]
            )
        )

    alert_lines = [
        " | ".join(
            [
                f"ref={alert.get('alert_ref')}",
                f"type={alert.get('alert_type')}",
                f"severity={alert.get('severity')}",
                f"title={alert.get('title')}",
            ]
        )
        for alert in alerts
    ]

    subject_name = payload.subject_name or _guess_subject_name(txns, case_row["title"]) or "Unknown subject"
    subject_type = payload.subject_type or "unknown"
    subject_account = payload.subject_account or _first_nonempty([case_row["primary_account_id"]]) or "unknown"

    return (
        "Draft a SAR narrative for the following case.\n\n"
        f"Case ref: {case_row['case_ref']}\n"
        f"Case title: {case_row['title']}\n"
        f"Case priority: {case_row['priority']}\n"
        f"Case status: {case_row['status']}\n"
        f"Subject name: {subject_name}\n"
        f"Subject type: {subject_type}\n"
        f"Subject account: {subject_account}\n"
        f"Requested activity type: {payload.activity_type or _infer_activity_type(txns) or 'unknown'}\n\n"
        "Linked alerts:\n"
        f"{chr(10).join(alert_lines) if alert_lines else 'None'}\n\n"
        "Linked transactions:\n"
        f"{chr(10).join(tx_lines) if tx_lines else 'None'}\n\n"
        "Write a polished SAR narrative in 2-4 short paragraphs. Include why the activity appears suspicious, "
        "reference transaction behavior and alert indicators, and do not invent facts beyond the supplied case data."
    )


def _build_sar_ref() -> str:
    return f"SAR-{uuid4().hex[:12].upper()}"


def _build_filing_ref() -> str:
    return f"FILING-{uuid4().hex[:12].upper()}"
