"""
Entity profile, watchlist, and merge-resolution services for the analyst workspace.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from uuid import uuid4

from core.config import settings
from core.database import get_pool
from models.casework import ScreenEntityRequest
from services.screening import ScreeningUnavailableError, screen_entity
from services.graph_sync import get_graph_drilldown, safe_resync_graph
from services.routing import resolve_case_routing, routing_metadata_payload
from services.workflow_engine import start_watchlist_camunda_flow

RISK_ORDER = {"low": 1, "medium": 2, "high": 3, "critical": 4}


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


def _resolution_status_from_metadata(metadata: dict[str, Any]) -> str | None:
    status = metadata.get("resolution_status")
    if status:
        return str(status)
    watchlist_state = _watchlist_state(metadata)
    if watchlist_state.get("status") == "active":
        return "watchlist_active"
    return None


def _watchlist_state(metadata: dict[str, Any]) -> dict[str, Any]:
    value = metadata.get("watchlist_state")
    watchlist = _normalize_json_dict(value)
    return watchlist if watchlist else {}


def _merge_state(metadata: dict[str, Any]) -> dict[str, Any]:
    value = metadata.get("merge_state")
    merged = _normalize_json_dict(value)
    return merged if merged else {}


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


def _watchlist_interval_days(watchlist_state: dict[str, Any], override: int | None = None) -> int:
    if override is not None:
        return max(1, int(override))
    value = watchlist_state.get("rescreen_interval_days") or settings.WATCHLIST_RESCREEN_INTERVAL_DAYS
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return settings.WATCHLIST_RESCREEN_INTERVAL_DAYS


def _watchlist_rescreen_state(
    metadata: dict[str, Any],
    *,
    latest_screened_at: datetime | None = None,
    interval_override: int | None = None,
) -> dict[str, Any]:
    watchlist_state = _watchlist_state(metadata)
    interval_days = _watchlist_interval_days(watchlist_state, interval_override)
    added_at = _safe_datetime(watchlist_state.get("added_at"))
    metadata_last_screened_at = _safe_datetime(watchlist_state.get("last_screened_at"))
    if metadata_last_screened_at and latest_screened_at:
        last_screened_at = metadata_last_screened_at if metadata_last_screened_at >= latest_screened_at else latest_screened_at
    else:
        last_screened_at = metadata_last_screened_at or latest_screened_at or added_at
    computed_next_due_at = last_screened_at + timedelta(days=interval_days) if last_screened_at is not None else None
    metadata_next_due_at = _safe_datetime(watchlist_state.get("next_screening_due_at"))
    if metadata_last_screened_at and latest_screened_at and latest_screened_at > metadata_last_screened_at:
        next_due_at = computed_next_due_at
    else:
        next_due_at = metadata_next_due_at or computed_next_due_at

    status = str(watchlist_state.get("status") or "").lower()
    now = datetime.now(timezone.utc)
    due_soon_window = timedelta(days=settings.WATCHLIST_RESCREEN_DUE_SOON_DAYS)

    if status != "active":
        rescreen_status = "removed" if status == "removed" else "inactive"
    elif next_due_at is None:
        rescreen_status = "due"
    elif next_due_at <= now:
        rescreen_status = "overdue"
    elif next_due_at - now <= due_soon_window:
        rescreen_status = "due_soon"
    else:
        rescreen_status = "current"

    return {
        "rescreen_interval_days": interval_days,
        "last_screened_at": last_screened_at,
        "last_screened_by": watchlist_state.get("last_screened_by"),
        "next_screening_due_at": next_due_at,
        "rescreen_status": rescreen_status,
        "last_match_count": int(watchlist_state.get("last_match_count") or 0),
        "last_screening_trigger": watchlist_state.get("last_screening_trigger"),
        "last_datasets": [str(item) for item in _normalize_json_list(watchlist_state.get("last_datasets"))],
    }


def _aliases(metadata: dict[str, Any], entity_name: str) -> list[str]:
    aliases = []
    for item in _normalize_json_list(metadata.get("aliases")):
        if isinstance(item, str) and item.strip():
            aliases.append(item.strip())
    seen = {entity_name.lower()}
    unique: list[str] = []
    for alias in aliases:
        key = alias.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(alias)
    return unique[:50]


def _merge_text_lists(*values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for value in values:
        for item in value or []:
            text = str(item).strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(text)
    return merged[:50]


def _risk_level_max(left: str | None, right: str | None) -> str:
    left_key = str(left or "low").lower()
    right_key = str(right or "low").lower()
    return left_key if RISK_ORDER.get(left_key, 0) >= RISK_ORDER.get(right_key, 0) else right_key


def _history_item(
    *,
    action: str,
    actor: str | None,
    note: str | None,
    resolution_status: str | None,
    candidate_entity_id: UUID | None = None,
    candidate_name: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "action": action,
        "actor": actor,
        "note": note,
        "candidate_entity_id": str(candidate_entity_id) if candidate_entity_id else None,
        "candidate_name": candidate_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "resolution_status": resolution_status,
    }
    if extra:
        item.update(extra)
    return item


def _metadata_tasks(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    values = _normalize_json_list(metadata.get("tasks"))
    return [item for item in values if isinstance(item, dict)]


async def _create_case_task(
    conn: Any,
    *,
    case_id: UUID,
    metadata: dict[str, Any],
    actor: str | None,
    title: str,
    description: str,
    assigned_to: str | None,
    priority: str = "high",
    note: str | None = None,
) -> UUID | None:
    tasks = _metadata_tasks(metadata)
    for item in tasks:
        if str(item.get("title") or "").strip() != title:
            continue
        if str(item.get("status") or "open") == "done":
            continue
        return UUID(str(item["id"])) if item.get("id") else None

    now_iso = datetime.now(timezone.utc).isoformat()
    task_id = uuid4()
    task = {
        "id": str(task_id),
        "title": title,
        "description": description,
        "status": "open",
        "priority": priority,
        "assigned_to": assigned_to,
        "created_by": actor,
        "note": note,
        "created_at": now_iso,
        "updated_at": now_iso,
        "due_at": None,
        "completed_at": None,
    }
    tasks.append(task)
    metadata["tasks"] = tasks[-100:]
    await conn.execute(
        """
        INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
        VALUES ($1, 'task_created', $2, $3, $4::jsonb)
        """,
        case_id,
        actor,
        f"Task created: {title}",
        json.dumps({"task_id": str(task_id), "assigned_to": assigned_to, "priority": priority}),
    )
    return task_id


async def _auto_escalate_watchlist_case(
    conn: Any,
    *,
    case_id: UUID,
    entity_row: dict[str, Any],
    actor: str | None,
    match_count: int,
    new_matches: int,
    datasets: list[str],
) -> tuple[bool, UUID | None]:
    case_row = await conn.fetchrow(
        "SELECT id, case_ref, status, priority, assigned_to, metadata FROM cases WHERE id = $1 FOR UPDATE",
        case_id,
    )
    if not case_row:
        return False, None

    current_metadata = _normalize_json_dict(case_row.get("metadata"))
    current_priority = str(case_row.get("priority") or "medium").lower()
    next_priority = "critical" if bool(entity_row.get("is_sanctioned")) or new_matches > 1 else "high"
    if RISK_ORDER.get(current_priority, 0) > RISK_ORDER.get(next_priority, 0):
        next_priority = current_priority

    current_status = str(case_row.get("status") or "open").lower()
    next_status = current_status
    if current_status in {"open", "referred"}:
        next_status = "reviewing"

    current_metadata["watchlist_auto_escalation"] = {
        "actor": actor,
        "entity_id": str(entity_row["id"]),
        "entity_name": entity_row["name"],
        "match_count": match_count,
        "new_matches": new_matches,
        "datasets": datasets,
        "escalated_at": datetime.now(timezone.utc).isoformat(),
    }

    task_id = await _create_case_task(
        conn,
        case_id=case_id,
        metadata=current_metadata,
        actor=actor,
        title=f"Review new watchlist matches for {entity_row['name']}",
        description=(
            f"Recurring watchlist re-screen found {new_matches} new match(es) and {match_count} total hit(s) "
            f"for {entity_row['name']}. Review the updated screening evidence and escalate further if required."
        ),
        assigned_to=case_row["assigned_to"] or actor,
        priority="critical" if next_priority == "critical" else "high",
        note=f"Datasets: {', '.join(datasets) if datasets else 'none'}",
    )

    await conn.execute(
        """
        UPDATE cases
        SET
            status = $2::case_status,
            priority = $3::case_priority,
            metadata = $4::jsonb,
            updated_at = NOW()
        WHERE id = $1
        """,
        case_id,
        next_status,
        next_priority,
        json.dumps(current_metadata),
    )
    await conn.execute(
        """
        INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
        VALUES ($1, 'watchlist_case_escalated', $2, $3, $4::jsonb)
        """,
        case_id,
        actor,
        "Watchlist review case escalated after recurring re-screen found new matches",
        json.dumps(
            {
                "entity_id": str(entity_row["id"]),
                "entity_name": entity_row["name"],
                "match_count": match_count,
                "new_matches": new_matches,
                "datasets": datasets,
                "task_id": str(task_id) if task_id else None,
                "priority": next_priority,
                "status": next_status,
            }
        ),
    )
    return True, task_id


async def list_entities(
    *,
    limit: int,
    offset: int,
    query: str | None = None,
    risk_level: str | None = None,
) -> list[dict[str, Any]]:
    pool = get_pool()
    conditions = ["coalesce(metadata->>'resolution_status', '') <> 'merged'"]
    args: list[Any] = []
    idx = 1

    if query:
        conditions.append(
            f"""(
                lower(name) LIKE ${idx}
                OR lower(coalesce(name_normalized, '')) LIKE ${idx}
                OR lower(coalesce(id_number, '')) LIKE ${idx}
            )"""
        )
        args.append(f"%{query.lower()}%")
        idx += 1

    if risk_level:
        conditions.append(f"risk_level = ${idx}::risk_level")
        args.append(risk_level)
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                id, name, entity_type, country, nationality,
                is_pep, is_sanctioned, risk_score, risk_level,
                metadata, created_at
            FROM entities
            WHERE {where}
            ORDER BY
                (CASE WHEN coalesce(metadata->'watchlist_state'->>'status', '') = 'active' THEN 1 ELSE 0 END) DESC,
                is_sanctioned DESC,
                is_pep DESC,
                risk_score DESC NULLS LAST,
                created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *args,
            limit,
            offset,
        )

    results: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["risk_score"] = float(item["risk_score"]) if item.get("risk_score") is not None else None
        metadata = _normalize_json_dict(item.pop("metadata", {}))
        item["resolution_status"] = _resolution_status_from_metadata(metadata)
        results.append(item)
    return results


async def list_watchlist_entities(
    *,
    status: str,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    status_key = status.lower()
    if status_key not in {"active", "removed", "all"}:
        raise ValueError(f"Unsupported watchlist status filter: {status}")

    if status_key == "all":
        where = "coalesce(e.metadata->'watchlist_state'->>'status', '') <> ''"
    else:
        where = f"coalesce(e.metadata->'watchlist_state'->>'status', '') = '{status_key}'"

    pool = get_pool()
    async with pool.acquire() as conn:
        count_rows = await conn.fetch(
            """
            SELECT
                e.id,
                e.risk_level,
                e.metadata,
                EXISTS (
                    SELECT 1
                    FROM cases c
                    WHERE c.primary_entity_id = e.id
                      AND coalesce(c.metadata->>'entity_workflow', '') = 'watchlist_review'
                      AND c.status <> 'closed'
                ) AS has_open_case,
                ls.last_screened_at
            FROM entities e
            LEFT JOIN LATERAL (
                SELECT MAX(sr.created_at) AS last_screened_at
                FROM screening_results sr
                WHERE sr.entity_id = e.id OR lower(sr.entity_name) = lower(e.name)
            ) ls ON TRUE
            WHERE coalesce(e.metadata->'watchlist_state'->>'status', '') <> ''
              AND coalesce(e.metadata->>'resolution_status', '') <> 'merged'
            """
        )

        rows = await conn.fetch(
            f"""
            SELECT
                e.id,
                e.name,
                e.entity_type,
                e.country,
                e.risk_score,
                e.risk_level,
                e.is_pep,
                e.is_sanctioned,
                e.metadata,
                COALESCE(ac.account_count, 0)::int AS linked_account_count,
                COALESCE(cc.case_count, 0)::int AS linked_case_count,
                COALESCE(dc.document_count, 0)::int AS linked_document_count,
                COALESCE(sc.screening_count, 0)::int AS screening_hit_count,
                COALESCE(alc.alert_count, 0)::int AS alert_count,
                ls.last_screened_at,
                wc.id AS case_id,
                wc.case_ref
            FROM entities e
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS account_count
                FROM account_entities ae
                WHERE ae.entity_id = e.id
            ) ac ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(DISTINCT c.id) AS case_count
                FROM cases c
                LEFT JOIN case_alerts ca ON ca.case_id = c.id
                LEFT JOIN alerts a ON a.id = ca.alert_id
                WHERE c.primary_entity_id = e.id OR a.entity_id = e.id
            ) cc ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS document_count
                FROM documents d
                WHERE d.entity_id = e.id
            ) dc ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS screening_count
                FROM screening_results sr
                WHERE sr.entity_id = e.id OR lower(sr.entity_name) = lower(e.name)
            ) sc ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS alert_count
                FROM alerts al
                WHERE al.entity_id = e.id
            ) alc ON TRUE
            LEFT JOIN LATERAL (
                SELECT MAX(sr.created_at) AS last_screened_at
                FROM screening_results sr
                WHERE sr.entity_id = e.id OR lower(sr.entity_name) = lower(e.name)
            ) ls ON TRUE
            LEFT JOIN LATERAL (
                SELECT c.id, c.case_ref
                FROM cases c
                WHERE c.primary_entity_id = e.id
                  AND coalesce(c.metadata->>'entity_workflow', '') = 'watchlist_review'
                  AND c.status <> 'closed'
                ORDER BY c.created_at DESC
                LIMIT 1
            ) wc ON TRUE
            WHERE {where}
              AND coalesce(e.metadata->>'resolution_status', '') <> 'merged'
            ORDER BY
                CASE WHEN coalesce(e.metadata->'watchlist_state'->>'status', '') = 'active' THEN 0 ELSE 1 END,
                CASE WHEN e.risk_level = 'critical' THEN 0 WHEN e.risk_level = 'high' THEN 1 WHEN e.risk_level = 'medium' THEN 2 ELSE 3 END,
                e.risk_score DESC NULLS LAST,
                e.created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )

    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        metadata = _normalize_json_dict(item.pop("metadata", {}))
        watchlist_state = _watchlist_state(metadata)
        if item.get("case_id") and not watchlist_state.get("case_id"):
            watchlist_state["case_id"] = str(item["case_id"])
            watchlist_state["case_ref"] = item.get("case_ref")
        rescreen = _watchlist_rescreen_state(metadata, latest_screened_at=item.pop("last_screened_at", None))
        item["risk_score"] = float(item["risk_score"]) if item.get("risk_score") is not None else None
        item["resolution_status"] = _resolution_status_from_metadata(metadata)
        item["watchlist_status"] = watchlist_state.get("status")
        item["watchlist_source"] = watchlist_state.get("source")
        item["watchlist_reason"] = watchlist_state.get("reason")
        item["watchlist_added_by"] = watchlist_state.get("added_by")
        item["watchlist_added_at"] = watchlist_state.get("added_at")
        item["rescreen_interval_days"] = rescreen.get("rescreen_interval_days")
        item["last_screened_at"] = rescreen.get("last_screened_at")
        item["last_screened_by"] = rescreen.get("last_screened_by")
        item["next_screening_due_at"] = rescreen.get("next_screening_due_at")
        item["rescreen_status"] = rescreen.get("rescreen_status")
        item["last_match_count"] = rescreen.get("last_match_count")
        item["last_screening_trigger"] = rescreen.get("last_screening_trigger")
        items.append(item)

    counts = {
        "active": 0,
        "removed": 0,
        "with_open_case": 0,
        "critical": 0,
        "due_for_rescreen": 0,
        "due_soon_rescreen": 0,
        "overdue_rescreen": 0,
        "screened_last_7d": 0,
        "total": 0,
    }
    now = datetime.now(timezone.utc)
    for row in count_rows:
        metadata = _normalize_json_dict(row["metadata"])
        watchlist_state = _watchlist_state(metadata)
        watchlist_status = str(watchlist_state.get("status") or "").lower()
        if not watchlist_status:
            continue
        counts["total"] += 1
        if watchlist_status == "active":
            counts["active"] += 1
        if watchlist_status == "removed":
            counts["removed"] += 1
        if bool(row["has_open_case"]) and watchlist_status == "active":
            counts["with_open_case"] += 1
        if watchlist_status == "active" and str(row["risk_level"] or "").lower() == "critical":
            counts["critical"] += 1
        rescreen = _watchlist_rescreen_state(metadata, latest_screened_at=row["last_screened_at"])
        if watchlist_status == "active" and rescreen["rescreen_status"] in {"due", "overdue"}:
            counts["due_for_rescreen"] += 1
        if watchlist_status == "active" and rescreen["rescreen_status"] == "due_soon":
            counts["due_soon_rescreen"] += 1
        if watchlist_status == "active" and rescreen["rescreen_status"] == "overdue":
            counts["overdue_rescreen"] += 1
        last_screened_at = rescreen.get("last_screened_at")
        if watchlist_status == "active" and isinstance(last_screened_at, datetime) and (now - last_screened_at) <= timedelta(days=7):
            counts["screened_last_7d"] += 1

    return {"status": status_key, "counts": counts, "items": items}


async def _load_watchlist_rescreen_candidates(
    conn: Any,
    *,
    entity_id: UUID | None,
    due_only: bool,
    limit: int,
    interval_days: int | None,
) -> list[dict[str, Any]]:
    conditions = [
        "coalesce(e.metadata->'watchlist_state'->>'status', '') = 'active'",
        "coalesce(e.metadata->>'resolution_status', '') <> 'merged'",
    ]
    args: list[Any] = []
    if entity_id is not None:
        conditions.append("e.id = $1")
        args.append(entity_id)

    where = " AND ".join(conditions)
    rows = await conn.fetch(
        f"""
        SELECT
            e.id,
            e.name,
            e.entity_type,
            e.country,
            e.risk_level,
            e.risk_score,
            e.is_pep,
            e.is_sanctioned,
            e.metadata,
            e.created_at,
            ls.last_screened_at,
            wc.id AS case_id,
            wc.case_ref
        FROM entities e
        LEFT JOIN LATERAL (
            SELECT MAX(sr.created_at) AS last_screened_at
            FROM screening_results sr
            WHERE sr.entity_id = e.id OR lower(sr.entity_name) = lower(e.name)
        ) ls ON TRUE
        LEFT JOIN LATERAL (
            SELECT c.id, c.case_ref
            FROM cases c
            WHERE c.primary_entity_id = e.id
              AND coalesce(c.metadata->>'entity_workflow', '') = 'watchlist_review'
              AND c.status <> 'closed'
            ORDER BY c.created_at DESC
            LIMIT 1
        ) wc ON TRUE
        WHERE {where}
        ORDER BY
            CASE WHEN e.risk_level = 'critical' THEN 0 WHEN e.risk_level = 'high' THEN 1 WHEN e.risk_level = 'medium' THEN 2 ELSE 3 END,
            e.risk_score DESC NULLS LAST,
            e.created_at DESC
        """,
        *args,
    )

    candidates: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for row in rows:
        item = dict(row)
        metadata = _normalize_json_dict(item.pop("metadata", {}))
        watchlist_state = _watchlist_state(metadata)
        if item.get("case_id") and not watchlist_state.get("case_id"):
            watchlist_state["case_id"] = str(item["case_id"])
            watchlist_state["case_ref"] = item.get("case_ref")
        rescreen = _watchlist_rescreen_state(metadata, latest_screened_at=item.pop("last_screened_at", None), interval_override=interval_days)
        next_due_at = rescreen.get("next_screening_due_at")
        if due_only and next_due_at is not None and next_due_at > now:
            continue
        if due_only and next_due_at is None and rescreen.get("rescreen_status") not in {"due", "overdue"}:
            continue
        item["metadata"] = metadata
        item["watchlist_state"] = watchlist_state
        item["rescreen"] = rescreen
        candidates.append(item)

    candidates.sort(
        key=lambda item: (
            0 if item["rescreen"].get("rescreen_status") == "overdue" else 1,
            item["rescreen"].get("next_screening_due_at") or datetime.now(timezone.utc),
            -(float(item.get("risk_score")) if item.get("risk_score") is not None else 0.0),
        )
    )
    return candidates[:limit]


async def run_watchlist_rescreen(
    *,
    actor: str | None,
    due_only: bool,
    limit: int,
    interval_days: int | None = None,
    entity_id: UUID | None = None,
) -> dict[str, Any]:
    actor_name = actor or "watchlist-automation"
    batch_limit = min(limit, settings.WATCHLIST_RESCREEN_BATCH_LIMIT) if entity_id is None else limit
    pool = get_pool()

    async with pool.acquire() as conn:
        candidates = await _load_watchlist_rescreen_candidates(
            conn,
            entity_id=entity_id,
            due_only=due_only,
            limit=batch_limit,
            interval_days=interval_days,
        )

        if entity_id is not None and not candidates:
            existing = await conn.fetchval("SELECT 1 FROM entities WHERE id = $1", entity_id)
            if not existing:
                return {}
            return {
                "scope": "single_entity",
                "processed_count": 0,
                "matched_count": 0,
                "new_match_entity_count": 0,
                "escalated_case_count": 0,
                "items": [],
                "summary": ["The selected entity is not currently eligible for watchlist re-screening."],
                "generated_at": datetime.now(timezone.utc),
            }

    processed_items: list[dict[str, Any]] = []
    camunda_starts: list[dict[str, Any]] = []
    matched_count = 0
    new_match_entity_count = 0
    escalated_case_count = 0
    selected_interval_days = interval_days or settings.WATCHLIST_RESCREEN_INTERVAL_DAYS

    for candidate in candidates:
        hits = await screen_entity(
            ScreenEntityRequest(
                entity_name=candidate["name"],
                trigger="watchlist_recurring",
                screened_by=actor_name,
                limit=10,
            ),
            resync_graph=False,
        )

        now = datetime.now(timezone.utc)
        match_count = len(hits)
        previous_match_count = int(candidate["rescreen"].get("last_match_count") or 0)
        new_matches = max(match_count - previous_match_count, 0)
        if match_count > 0:
            matched_count += 1
        if new_matches > 0:
            new_match_entity_count += 1

        datasets = sorted({str(hit.get("dataset") or "Unknown dataset") for hit in hits if hit.get("dataset")})

        async with pool.acquire() as conn:
            async with conn.transaction():
                entity_row = await conn.fetchrow("SELECT * FROM entities WHERE id = $1 FOR UPDATE", candidate["id"])
                if not entity_row:
                    continue

                entity_data = dict(entity_row)
                metadata = _normalize_json_dict(entity_data.get("metadata"))
                watchlist_state = _watchlist_state(metadata)
                watchlist_state.update(
                    {
                        "status": watchlist_state.get("status") or "active",
                        "rescreen_interval_days": selected_interval_days,
                        "last_screened_at": now.isoformat(),
                        "last_screened_by": actor_name,
                        "next_screening_due_at": (now + timedelta(days=selected_interval_days)).isoformat(),
                        "last_match_count": match_count,
                        "last_screening_trigger": "watchlist_recurring",
                        "last_datasets": datasets,
                    }
                )

                auto_case_id = watchlist_state.get("case_id")
                auto_case_ref = watchlist_state.get("case_ref")
                auto_escalated = False
                escalation_task_id: UUID | None = None
                if match_count > 0:
                    case_id, case_ref = await _create_watchlist_case(
                        conn,
                        entity_row=entity_data,
                        metadata={**metadata, "watchlist_state": watchlist_state},
                        actor=actor_name,
                        note=f"Recurring watchlist re-screen found {match_count} potential screening hit(s).",
                    )
                    auto_case_id = str(case_id)
                    auto_case_ref = case_ref
                    watchlist_state["case_id"] = auto_case_id
                    watchlist_state["case_ref"] = auto_case_ref
                    if new_matches > 0 and settings.WATCHLIST_AUTO_ESCALATE_NEW_MATCHES:
                        auto_escalated, escalation_task_id = await _auto_escalate_watchlist_case(
                            conn,
                            case_id=case_id,
                            entity_row=entity_data,
                            actor=actor_name,
                            match_count=match_count,
                            new_matches=new_matches,
                            datasets=datasets,
                        )
                        if auto_escalated:
                            escalated_case_count += 1
                            camunda_starts.append(
                                {
                                    "case_id": case_id,
                                    "entity_id": candidate["id"],
                                    "entity_name": candidate["name"],
                                    "actor": actor_name,
                                }
                            )
                    await conn.execute(
                        """
                        INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                        VALUES ($1, 'watchlist_rescreened', $2, $3, $4::jsonb)
                        """,
                        case_id,
                        actor_name,
                        "Recurring watchlist re-screen completed",
                        json.dumps(
                            {
                                "entity_id": str(candidate["id"]),
                                "entity_name": candidate["name"],
                                "match_count": match_count,
                                "new_matches": new_matches,
                                "datasets": datasets,
                                "auto_escalated": auto_escalated,
                                "escalation_task_id": str(escalation_task_id) if escalation_task_id else None,
                            }
                        ),
                    )

                metadata["watchlist_state"] = watchlist_state
                metadata["resolution_status"] = _resolution_status_from_metadata(metadata) or "watchlist_active"
                history = _normalize_json_list(metadata.get("resolution_history"))
                history.append(
                    _history_item(
                        action="watchlist_rescreened",
                        actor=actor_name,
                        note=f"Recurring re-screen completed with {match_count} hit(s).",
                        resolution_status=metadata.get("resolution_status"),
                        extra={
                            "match_count": match_count,
                            "new_matches": new_matches,
                            "datasets": datasets,
                            "watchlist_case_id": auto_case_id,
                            "watchlist_case_ref": auto_case_ref,
                            "auto_escalated": auto_escalated,
                            "escalation_task_id": str(escalation_task_id) if escalation_task_id else None,
                        },
                    )
                )
                metadata["resolution_history"] = history[-60:]

                await conn.execute(
                    "UPDATE entities SET metadata = $2::jsonb, updated_at = NOW() WHERE id = $1",
                    candidate["id"],
                    json.dumps(metadata),
                )

                processed_items.append(
                    {
                        "entity_id": candidate["id"],
                        "name": candidate["name"],
                        "watchlist_status": watchlist_state.get("status"),
                        "case_id": auto_case_id,
                        "case_ref": auto_case_ref,
                        "match_count": match_count,
                        "new_matches": new_matches,
                        "auto_escalated": auto_escalated,
                        "escalation_task_id": escalation_task_id,
                        "rescreen_status": _watchlist_rescreen_state(metadata)["rescreen_status"],
                        "last_screened_at": now,
                        "next_screening_due_at": now + timedelta(days=selected_interval_days),
                        "trigger": "watchlist_recurring",
                        "datasets": datasets,
                    }
                )

    if processed_items:
        await safe_resync_graph(clear_existing=True)
    for item in camunda_starts:
        await start_watchlist_camunda_flow(
            case_id=item["case_id"],
            entity_id=item["entity_id"],
            entity_name=item["entity_name"],
            actor=item["actor"],
        )

    scope = "single_entity" if entity_id is not None else ("due_only" if due_only else "full_active_watchlist")
    summary = [
        f"Processed {len(processed_items)} watchlist entity re-screen checks.",
        f"{matched_count} entities produced at least one screening match in this run.",
        f"{new_match_entity_count} entities produced new matches compared with the prior recorded run.",
        f"{escalated_case_count} watchlist review cases were automatically escalated for analyst follow-up.",
    ]
    return {
        "scope": scope,
        "processed_count": len(processed_items),
        "matched_count": matched_count,
        "new_match_entity_count": new_match_entity_count,
        "escalated_case_count": escalated_case_count,
        "items": processed_items,
        "summary": summary,
        "generated_at": datetime.now(timezone.utc),
    }


async def get_entity_profile(entity_id: UUID) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        entity_row = await conn.fetchrow("SELECT * FROM entities WHERE id = $1", entity_id)
        if not entity_row:
            return None

        account_rows = await conn.fetch(
            """
            SELECT
                ae.account_id, ae.role,
                a.account_number, a.account_name, a.risk_score, a.risk_level, a.country
            FROM account_entities ae
            JOIN accounts a ON a.id = ae.account_id
            WHERE ae.entity_id = $1
            ORDER BY a.risk_score DESC NULLS LAST, a.account_number
            LIMIT 25
            """,
            entity_id,
        )

        case_rows = await conn.fetch(
            """
            SELECT DISTINCT
                c.id AS case_id, c.case_ref, c.title, c.status, c.priority, c.assigned_to, c.created_at
            FROM cases c
            LEFT JOIN case_alerts ca ON ca.case_id = c.id
            LEFT JOIN alerts a ON a.id = ca.alert_id
            WHERE c.primary_entity_id = $1 OR a.entity_id = $1
            ORDER BY c.created_at DESC
            LIMIT 20
            """,
            entity_id,
        )

        document_rows = await conn.fetch(
            """
            SELECT
                id AS document_id, filename, file_type, uploaded_by,
                pii_detected, parse_applied, embedded, created_at
            FROM documents
            WHERE entity_id = $1
            ORDER BY created_at DESC
            LIMIT 20
            """,
            entity_id,
        )

        screening_rows = await conn.fetch(
            """
            SELECT
                id AS screening_id, entity_name, matched_name, dataset,
                match_type, match_score, matched_country, created_at
            FROM screening_results
            WHERE entity_id = $1 OR lower(entity_name) = lower($2)
            ORDER BY match_score DESC NULLS LAST, created_at DESC
            LIMIT 20
            """,
            entity_id,
            entity_row["name"],
        )

        candidate_rows = await conn.fetch(
            """
            SELECT
                e.id AS entity_id,
                e.name,
                e.entity_type,
                e.country,
                e.risk_level,
                e.risk_score,
                similarity(coalesce(e.name_normalized, lower(e.name)), lower($2)) AS similarity,
                COALESCE(ac.account_count, 0)::int AS linked_account_count,
                COALESCE(cc.case_count, 0)::int AS linked_case_count,
                COALESCE(dc.document_count, 0)::int AS linked_document_count,
                COALESCE(sc.screening_count, 0)::int AS screening_hit_count,
                COALESCE(alc.alert_count, 0)::int AS alert_count
            FROM entities e
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS account_count
                FROM account_entities ae
                WHERE ae.entity_id = e.id
            ) ac ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(DISTINCT c.id) AS case_count
                FROM cases c
                LEFT JOIN case_alerts ca ON ca.case_id = c.id
                LEFT JOIN alerts a ON a.id = ca.alert_id
                WHERE c.primary_entity_id = e.id OR a.entity_id = e.id
            ) cc ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS document_count
                FROM documents d
                WHERE d.entity_id = e.id
            ) dc ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS screening_count
                FROM screening_results sr
                WHERE sr.entity_id = e.id OR lower(sr.entity_name) = lower(e.name)
            ) sc ON TRUE
            LEFT JOIN LATERAL (
                SELECT COUNT(*) AS alert_count
                FROM alerts al
                WHERE al.entity_id = e.id
            ) alc ON TRUE
            WHERE e.id <> $1
              AND coalesce(e.metadata->>'resolution_status', '') <> 'merged'
              AND similarity(coalesce(e.name_normalized, lower(e.name)), lower($2)) > 0.12
            ORDER BY similarity DESC, e.risk_score DESC NULLS LAST
            LIMIT 8
            """,
            entity_id,
            entity_row["name"],
        )

        watchlist_case_row = await conn.fetchrow(
            """
            SELECT id, case_ref
            FROM cases
            WHERE primary_entity_id = $1
              AND coalesce(metadata->>'entity_workflow', '') = 'watchlist_review'
              AND status <> 'closed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            entity_id,
        )

    entity = dict(entity_row)
    metadata = _normalize_json_dict(entity.get("metadata"))
    resolution_history = _normalize_json_list(metadata.get("resolution_history"))
    watchlist_state = _watchlist_state(metadata)
    merge_state = _merge_state(metadata)
    aliases = _aliases(metadata, entity["name"])
    latest_screened_at = None
    for row in screening_rows:
        created_at = _safe_datetime(row.get("created_at"))
        if created_at and (latest_screened_at is None or created_at > latest_screened_at):
            latest_screened_at = created_at

    if watchlist_case_row:
        watchlist_state.setdefault("status", "active")
        watchlist_state["case_id"] = watchlist_case_row["id"]
        watchlist_state["case_ref"] = watchlist_case_row["case_ref"]
    if watchlist_state:
        watchlist_state.update(_watchlist_rescreen_state(metadata, latest_screened_at=latest_screened_at))

    graph = await get_graph_drilldown(f"entity:{entity_id}", hops=2, limit=18)

    return {
        "id": entity["id"],
        "name": entity["name"],
        "entity_type": entity["entity_type"],
        "date_of_birth": entity["date_of_birth"].isoformat() if entity.get("date_of_birth") else None,
        "nationality": entity["nationality"],
        "country": entity["country"],
        "id_number": entity["id_number"],
        "id_type": entity["id_type"],
        "is_pep": bool(entity["is_pep"]),
        "is_sanctioned": bool(entity["is_sanctioned"]),
        "sanctions_list": entity.get("sanctions_list") or [],
        "risk_score": float(entity["risk_score"]) if entity.get("risk_score") is not None else None,
        "risk_level": entity["risk_level"],
        "embedding_id": entity["embedding_id"],
        "resolution_status": _resolution_status_from_metadata(metadata),
        "aliases": aliases,
        "watchlist_state": watchlist_state or None,
        "merge_state": merge_state or None,
        "metadata": metadata,
        "related_accounts": [
            {
                **dict(row),
                "risk_score": float(row["risk_score"]) if row["risk_score"] is not None else None,
            }
            for row in account_rows
        ],
        "related_cases": [dict(row) for row in case_rows],
        "screening_hits": [
            {
                **dict(row),
                "match_score": float(row["match_score"]) if row["match_score"] is not None else None,
            }
            for row in screening_rows
        ],
        "documents": [dict(row) for row in document_rows],
        "resolution_candidates": [
            {
                **dict(row),
                "risk_score": float(row["risk_score"]) if row["risk_score"] is not None else None,
                "similarity": float(row["similarity"]) if row["similarity"] is not None else None,
            }
            for row in candidate_rows
        ],
        "resolution_history": [
            {
                **item,
                "created_at": item.get("created_at"),
            }
            for item in resolution_history
        ],
        "graph": graph,
    }


async def _create_watchlist_case(
    conn: Any,
    *,
    entity_row: dict[str, Any],
    metadata: dict[str, Any],
    actor: str | None,
    note: str | None,
) -> tuple[UUID, str]:
    existing = await conn.fetchrow(
        """
        SELECT id, case_ref
        FROM cases
        WHERE primary_entity_id = $1
          AND coalesce(metadata->>'entity_workflow', '') = 'watchlist_review'
          AND status <> 'closed'
        ORDER BY created_at DESC
        LIMIT 1
        """,
        entity_row["id"],
    )
    if existing:
        return existing["id"], existing["case_ref"]

    primary_account_id = await conn.fetchval(
        """
        SELECT account_id
        FROM account_entities
        WHERE entity_id = $1
        ORDER BY CASE WHEN role = 'owner' THEN 0 ELSE 1 END, since NULLS LAST
        LIMIT 1
        """,
        entity_row["id"],
    )

    watchlist_state = _watchlist_state(metadata)
    watchlist_reason = watchlist_state.get("reason") or note
    routing = await resolve_case_routing(
        conn,
        workflow_type="watchlist",
        primary_entity_id=entity_row["id"],
        primary_account_id=primary_account_id,
        existing_metadata=metadata,
    )
    case_metadata = {
        "entity_workflow": "watchlist_review",
        "linked_entity_id": str(entity_row["id"]),
        "watchlist_reason": watchlist_reason,
        "watchlist_source": watchlist_state.get("source") or "internal",
        "routing": routing_metadata_payload(routing, workflow_type="watchlist", source="watchlist_case"),
    }

    case_row = await conn.fetchrow(
        """
        INSERT INTO cases (
            title,
            description,
            priority,
            assigned_to,
            created_by,
            primary_account_id,
            primary_entity_id,
            sar_required,
            metadata
        ) VALUES ($1, $2, $3::case_priority, $4, $5, $6, $7, $8, $9::jsonb)
        RETURNING id, case_ref
        """,
        f"Entity watchlist review — {entity_row['name']}",
        (
            f"Internal watchlist review opened for {entity_row['name']}.\n"
            f"Reason: {watchlist_reason or 'Entity flagged from the analyst resolution workspace.'}"
        ),
        "high" if entity_row.get("is_sanctioned") or entity_row.get("is_pep") else "medium",
        routing.get("assigned_to") or actor,
        actor,
        primary_account_id,
        entity_row["id"],
        bool(entity_row.get("is_sanctioned")),
        json.dumps(case_metadata),
    )

    await conn.execute(
        """
        INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
        VALUES ($1, 'created', $2, $3, $4::jsonb)
        """,
        case_row["id"],
        actor,
        "Case created",
        json.dumps({"entity_workflow": "watchlist_review", "linked_entity_id": str(entity_row["id"])}),
    )
    await conn.execute(
        """
        INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
        VALUES ($1, 'watchlist_case_opened', $2, $3, $4::jsonb)
        """,
        case_row["id"],
        actor,
        "Watchlist review case opened from entity workspace",
        json.dumps({"entity_id": str(entity_row["id"]), "entity_name": entity_row["name"]}),
    )

    return case_row["id"], case_row["case_ref"]


async def _merge_into_candidate(
    conn: Any,
    *,
    source_row: dict[str, Any],
    target_row: dict[str, Any],
    actor: str | None,
    note: str | None,
) -> UUID:
    source_metadata = _normalize_json_dict(source_row.get("metadata"))
    target_metadata = _normalize_json_dict(target_row.get("metadata"))

    target_watchlist = _watchlist_state(target_metadata)
    source_watchlist = _watchlist_state(source_metadata)
    if source_watchlist.get("status") == "active" and target_watchlist.get("status") != "active":
        target_watchlist = dict(source_watchlist)

    target_aliases = _merge_text_lists(
        _aliases(target_metadata, target_row["name"]),
        _aliases(source_metadata, source_row["name"]),
        [source_row["name"]],
    )

    target_resolution_status = _resolution_status_from_metadata(target_metadata) or "merged_record"
    target_history = _normalize_json_list(target_metadata.get("resolution_history"))
    target_history.append(
        _history_item(
            action="merge_candidate",
            actor=actor,
            note=note,
            resolution_status=target_resolution_status,
            candidate_entity_id=source_row["id"],
            candidate_name=source_row["name"],
            extra={"merged_from_entity_id": str(source_row["id"])},
        )
    )

    merge_event = {
        "source_entity_id": str(source_row["id"]),
        "source_entity_name": source_row["name"],
        "target_entity_id": str(target_row["id"]),
        "target_entity_name": target_row["name"],
        "actor": actor,
        "note": note,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    target_metadata["aliases"] = target_aliases
    target_metadata["merge_history"] = (_normalize_json_list(target_metadata.get("merge_history")) + [merge_event])[-60:]
    target_metadata["resolution_history"] = target_history[-60:]
    target_metadata["watchlist_state"] = target_watchlist or target_metadata.get("watchlist_state")

    next_is_pep = bool(target_row["is_pep"]) or bool(source_row["is_pep"])
    next_is_sanctioned = bool(target_row["is_sanctioned"]) or bool(source_row["is_sanctioned"])
    next_risk_score = max(
        float(target_row["risk_score"]) if target_row.get("risk_score") is not None else 0.0,
        float(source_row["risk_score"]) if source_row.get("risk_score") is not None else 0.0,
    )
    next_risk_level = _risk_level_max(target_row.get("risk_level"), source_row.get("risk_level"))
    next_sanctions_list = _merge_text_lists(target_row.get("sanctions_list"), source_row.get("sanctions_list"))

    impacted_case_rows = await conn.fetch(
        """
        SELECT DISTINCT case_id
        FROM (
            SELECT id AS case_id FROM cases WHERE primary_entity_id = $1
            UNION
            SELECT case_id FROM alerts WHERE entity_id = $1 AND case_id IS NOT NULL
        ) AS impacted
        WHERE case_id IS NOT NULL
        """,
        source_row["id"],
    )

    await conn.execute(
        """
        INSERT INTO account_entities (account_id, entity_id, role, since)
        SELECT account_id, $1, role, since
        FROM account_entities
        WHERE entity_id = $2
        ON CONFLICT (account_id, entity_id) DO NOTHING
        """,
        target_row["id"],
        source_row["id"],
    )
    await conn.execute("DELETE FROM account_entities WHERE entity_id = $1", source_row["id"])
    await conn.execute("UPDATE alerts SET entity_id = $1, updated_at = NOW() WHERE entity_id = $2", target_row["id"], source_row["id"])
    await conn.execute("UPDATE cases SET primary_entity_id = $1, updated_at = NOW() WHERE primary_entity_id = $2", target_row["id"], source_row["id"])
    await conn.execute("UPDATE documents SET entity_id = $1 WHERE entity_id = $2", target_row["id"], source_row["id"])
    await conn.execute("UPDATE screening_results SET entity_id = $1 WHERE entity_id = $2", target_row["id"], source_row["id"])

    await conn.execute(
        """
        UPDATE entities
        SET
            is_pep = $2,
            is_sanctioned = $3,
            sanctions_list = $4::text[],
            risk_score = $5,
            risk_level = $6::risk_level,
            metadata = $7::jsonb,
            updated_at = NOW()
        WHERE id = $1
        """,
        target_row["id"],
        next_is_pep,
        next_is_sanctioned,
        next_sanctions_list or None,
        next_risk_score,
        next_risk_level,
        json.dumps(target_metadata),
    )

    source_history = _normalize_json_list(source_metadata.get("resolution_history"))
    source_history.append(
        _history_item(
            action="merged_into_candidate",
            actor=actor,
            note=note,
            resolution_status="merged",
            candidate_entity_id=target_row["id"],
            candidate_name=target_row["name"],
        )
    )
    source_metadata["resolution_status"] = "merged"
    source_metadata["merge_state"] = {
        "merged_into_entity_id": str(target_row["id"]),
        "merged_into_name": target_row["name"],
        "merged_by": actor,
        "merged_at": datetime.now(timezone.utc).isoformat(),
    }
    source_metadata["resolution_history"] = source_history[-60:]
    source_metadata["aliases"] = _merge_text_lists(_aliases(source_metadata, source_row["name"]), [source_row["name"]])

    await conn.execute(
        """
        UPDATE entities
        SET metadata = $2::jsonb, updated_at = NOW()
        WHERE id = $1
        """,
        source_row["id"],
        json.dumps(source_metadata),
    )

    for case_row in impacted_case_rows:
        await conn.execute(
            """
            INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
            VALUES ($1, 'entity_merged', $2, $3, $4::jsonb)
            """,
            case_row["case_id"],
            actor,
            f"Entity {source_row['name']} merged into {target_row['name']}",
            json.dumps(
                {
                    "source_entity_id": str(source_row["id"]),
                    "source_entity_name": source_row["name"],
                    "target_entity_id": str(target_row["id"]),
                    "target_entity_name": target_row["name"],
                }
            ),
        )

    return target_row["id"]


async def resolve_entity(
    entity_id: UUID,
    *,
    action: str,
    actor: str | None,
    note: str | None,
    candidate_entity_id: UUID | None,
) -> dict[str, Any] | None:
    supported_actions = {
        "add_note",
        "clear_entity",
        "watchlist_confirmed",
        "pep_confirmed",
        "sanctions_confirmed",
        "review_candidate",
        "remove_from_watchlist",
        "create_watchlist_case",
        "merge_candidate",
    }
    if action not in supported_actions:
        raise ValueError(f"Unsupported entity resolution action: {action}")

    pool = get_pool()
    profile_entity_id = entity_id
    watchlist_case_to_start: dict[str, Any] | None = None

    async with pool.acquire() as conn:
        async with conn.transaction():
            current_row = await conn.fetchrow("SELECT * FROM entities WHERE id = $1 FOR UPDATE", entity_id)
            if not current_row:
                return None

            current = dict(current_row)
            metadata = _normalize_json_dict(current.get("metadata"))
            history = _normalize_json_list(metadata.get("resolution_history"))
            watchlist_state = _watchlist_state(metadata)
            resolution_status = _resolution_status_from_metadata(metadata)

            candidate_row = None
            candidate_name = None
            if candidate_entity_id:
                if candidate_entity_id == entity_id:
                    raise ValueError("Candidate entity must be different from the current entity.")
                candidate_row = await conn.fetchrow("SELECT * FROM entities WHERE id = $1 FOR UPDATE", candidate_entity_id)
                if not candidate_row:
                    raise ValueError("Candidate entity not found.")
                candidate_name = candidate_row["name"]

            if action == "merge_candidate":
                if not candidate_row:
                    raise ValueError("A candidate entity is required to merge records.")
                profile_entity_id = await _merge_into_candidate(
                    conn,
                    source_row=current,
                    target_row=dict(candidate_row),
                    actor=actor,
                    note=note,
                )
            else:
                next_is_pep = bool(current["is_pep"])
                next_is_sanctioned = bool(current["is_sanctioned"])
                next_risk_score = float(current["risk_score"]) if current["risk_score"] is not None else 0.0
                next_risk_level = current["risk_level"]

                if action == "clear_entity":
                    resolution_status = "cleared"
                    watchlist_state = {}
                elif action == "watchlist_confirmed":
                    resolution_status = "watchlist_active"
                    watchlist_state = {
                        **watchlist_state,
                        "status": "active",
                        "source": watchlist_state.get("source") or "internal",
                        "reason": note or watchlist_state.get("reason"),
                        "added_by": actor or watchlist_state.get("added_by"),
                        "added_at": watchlist_state.get("added_at") or datetime.now(timezone.utc).isoformat(),
                    }
                    next_risk_score = max(next_risk_score, 0.82)
                    next_risk_level = _risk_level_max(next_risk_level, "high")
                elif action == "pep_confirmed":
                    resolution_status = "pep_confirmed"
                    next_is_pep = True
                    watchlist_state = {
                        **watchlist_state,
                        "status": "active",
                        "source": watchlist_state.get("source") or "internal",
                        "reason": note or watchlist_state.get("reason") or "PEP relationship confirmed by analyst review.",
                        "added_by": actor or watchlist_state.get("added_by"),
                        "added_at": watchlist_state.get("added_at") or datetime.now(timezone.utc).isoformat(),
                    }
                    next_risk_score = max(next_risk_score, 0.9)
                    next_risk_level = _risk_level_max(next_risk_level, "critical")
                elif action == "sanctions_confirmed":
                    resolution_status = "sanctions_confirmed"
                    next_is_sanctioned = True
                    watchlist_state = {
                        **watchlist_state,
                        "status": "active",
                        "source": watchlist_state.get("source") or "external_screening",
                        "reason": note or watchlist_state.get("reason") or "Sanctions linkage confirmed in analyst review.",
                        "added_by": actor or watchlist_state.get("added_by"),
                        "added_at": watchlist_state.get("added_at") or datetime.now(timezone.utc).isoformat(),
                    }
                    next_risk_score = max(next_risk_score, 0.94)
                    next_risk_level = _risk_level_max(next_risk_level, "critical")
                elif action == "review_candidate":
                    resolution_status = "candidate_reviewed"
                elif action == "remove_from_watchlist":
                    resolution_status = "watchlist_removed"
                    watchlist_state = {
                        **watchlist_state,
                        "status": "removed",
                        "reason": note or watchlist_state.get("reason"),
                        "removed_by": actor,
                        "removed_at": datetime.now(timezone.utc).isoformat(),
                    }
                elif action == "create_watchlist_case":
                    if watchlist_state.get("status") != "active":
                        watchlist_state = {
                            **watchlist_state,
                            "status": "active",
                            "source": watchlist_state.get("source") or "internal",
                            "reason": note or watchlist_state.get("reason") or "Manual watchlist review requested.",
                            "added_by": actor or watchlist_state.get("added_by"),
                            "added_at": watchlist_state.get("added_at") or datetime.now(timezone.utc).isoformat(),
                        }
                    resolution_status = "watchlist_active"
                    case_id, case_ref = await _create_watchlist_case(
                        conn,
                        entity_row=current,
                        metadata={**metadata, "watchlist_state": watchlist_state},
                        actor=actor,
                        note=note,
                    )
                    watchlist_state["case_id"] = str(case_id)
                    watchlist_state["case_ref"] = case_ref
                    watchlist_case_to_start = {
                        "case_id": case_id,
                        "entity_id": current["id"],
                        "entity_name": current["name"],
                        "actor": actor,
                    }
                    next_risk_score = max(next_risk_score, 0.82)
                    next_risk_level = _risk_level_max(next_risk_level, "high")
                elif action == "add_note":
                    resolution_status = resolution_status or "noted"

                metadata["resolution_status"] = resolution_status
                metadata["watchlist_state"] = watchlist_state
                history.append(
                    _history_item(
                        action=action,
                        actor=actor,
                        note=note,
                        resolution_status=resolution_status,
                        candidate_entity_id=candidate_entity_id,
                        candidate_name=candidate_name,
                        extra={
                            "watchlist_status": watchlist_state.get("status"),
                            "watchlist_case_id": watchlist_state.get("case_id"),
                            "watchlist_case_ref": watchlist_state.get("case_ref"),
                        },
                    )
                )
                metadata["resolution_history"] = history[-60:]

                await conn.execute(
                    """
                    UPDATE entities
                    SET
                        is_pep = $2,
                        is_sanctioned = $3,
                        risk_score = $4,
                        risk_level = $5::risk_level,
                        metadata = $6::jsonb,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    entity_id,
                    next_is_pep,
                    next_is_sanctioned,
                    next_risk_score,
                    next_risk_level,
                    json.dumps(metadata),
                )

    await safe_resync_graph(clear_existing=True)
    if watchlist_case_to_start:
        await start_watchlist_camunda_flow(
            case_id=watchlist_case_to_start["case_id"],
            entity_id=watchlist_case_to_start["entity_id"],
            entity_name=watchlist_case_to_start["entity_name"],
            actor=watchlist_case_to_start["actor"],
        )
    return await get_entity_profile(profile_entity_id)
