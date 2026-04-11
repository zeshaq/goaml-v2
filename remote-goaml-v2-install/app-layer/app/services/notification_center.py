"""
Analyst inbox and notification center aggregation.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID

from core.database import get_pool
from models.casework import CaseTaskStatus, CaseTaskUpdate
from services.cases import update_case_task


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_json(value: Any) -> dict[str, Any]:
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


def _state_for(item: dict[str, Any]) -> str:
    return str(item.get("state") or "new").lower()


async def get_notification_center(
    *,
    actor: str,
    state: str = "active",
    limit: int = 60,
    team_key: str | None = None,
    item_types: list[str] | None = None,
) -> dict[str, Any]:
    pool = get_pool()
    items: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        notification_rows = await conn.fetch(
            """
            SELECT
                n.id::text AS item_id,
                'notification'::text AS item_type,
                COALESCE(s.state, 'new') AS state,
                n.severity AS priority,
                n.subject AS title,
                COALESCE(n.metadata->>'message', n.metadata->>'summary', n.target) AS body,
                n.case_id,
                c.case_ref,
                n.team_key,
                n.region_key,
                n.metadata,
                COALESCE(s.updated_at, n.created_at) AS updated_at,
                n.created_at
            FROM notification_events n
            LEFT JOIN notification_inbox_state s
              ON s.item_type = 'notification'
             AND s.item_id = n.id::text
             AND s.actor = $1
            LEFT JOIN cases c ON c.id = n.case_id
            ORDER BY n.created_at DESC
            LIMIT $2
            """,
            actor,
            max(limit, 20),
        )

        task_rows = await conn.fetch(
            """
            SELECT
                task.value->>'id' AS item_id,
                'task'::text AS item_type,
                COALESCE(s.state, CASE
                    WHEN task.value->>'status' = 'done' THEN 'completed'
                    ELSE 'new'
                END) AS state,
                CASE
                    WHEN task.value->>'priority' = 'high' THEN 'high'
                    WHEN task.value->>'status' = 'blocked' THEN 'warning'
                    ELSE 'info'
                END AS priority,
                task.value->>'title' AS title,
                COALESCE(task.value->>'note', task.value->>'description') AS body,
                c.id AS case_id,
                c.case_ref,
                COALESCE(c.metadata->'routing'->>'team_key', NULL) AS team_key,
                COALESCE(c.metadata->'routing'->>'region_key', NULL) AS region_key,
                task.value AS metadata,
                COALESCE(s.updated_at, (task.value->>'updated_at')::timestamptz, c.updated_at) AS updated_at,
                COALESCE((task.value->>'created_at')::timestamptz, c.updated_at) AS created_at
            FROM cases c
            CROSS JOIN LATERAL jsonb_array_elements(COALESCE(c.metadata->'tasks', '[]'::jsonb)) AS task(value)
            LEFT JOIN notification_inbox_state s
              ON s.item_type = 'task'
             AND s.item_id = task.value->>'id'
             AND s.actor = $1
            WHERE COALESCE(task.value->>'assigned_to', '') = $1
            ORDER BY COALESCE((task.value->>'updated_at')::timestamptz, c.updated_at) DESC
            LIMIT $2
            """,
            actor,
            max(limit, 20),
        )

    for row in notification_rows:
        item = dict(row)
        item["metadata"] = _normalize_json(item.get("metadata"))
        item["owner"] = actor
        item["actor"] = item["metadata"].get("actor")
        item["deep_link"] = f"/#case-command?case={item['case_id']}" if item.get("case_id") else "/#workflow-ops"
        items.append(item)

    for row in task_rows:
        item = dict(row)
        item["metadata"] = _normalize_json(item.get("metadata"))
        item["owner"] = actor
        item["actor"] = item["metadata"].get("created_by")
        item["deep_link"] = f"/#case-command?case={item['case_id']}" if item.get("case_id") else "/#case-command"
        items.append(item)

    normalized_item_types = {str(item).strip().lower() for item in item_types or [] if str(item).strip()}
    if team_key:
        items = [item for item in items if str(item.get("team_key") or "").strip() == str(team_key).strip()]
    if normalized_item_types:
        items = [item for item in items if str(item.get("item_type") or "").strip().lower() in normalized_item_types]

    if state == "active":
        filtered = [item for item in items if _state_for(item) not in {"acknowledged", "dismissed", "completed"}]
    elif state == "completed":
        filtered = [item for item in items if _state_for(item) in {"acknowledged", "dismissed", "completed"}]
    else:
        filtered = items
    filtered.sort(
        key=lambda item: (
            0 if _state_for(item) == "new" else 1,
            -float((item.get("updated_at") or item.get("created_at") or _utcnow()).timestamp()),
        ),
    )
    filtered = filtered[:limit]

    counts = {
        "total": len(items),
        "active": sum(1 for item in items if _state_for(item) not in {"acknowledged", "dismissed", "completed"}),
        "new": sum(1 for item in items if _state_for(item) == "new"),
        "tasks": sum(1 for item in items if item.get("item_type") == "task"),
        "notifications": sum(1 for item in items if item.get("item_type") == "notification"),
    }
    summary = [
        f"{counts['active']} active inbox items are assigned to {actor}.",
        f"{counts['tasks']} tasks and {counts['notifications']} notification events are available.",
    ]
    if team_key:
        summary.append(f"The current view is scoped to team {team_key}.")
    if normalized_item_types:
        summary.append(f"Item types in scope: {', '.join(sorted(normalized_item_types))}.")
    return {
        "actor": actor,
        "generated_at": _utcnow(),
        "counts": counts,
        "items": filtered,
        "summary": summary,
    }


async def update_notification_center_state(
    *,
    actor: str,
    item_type: str,
    item_id: str,
    state: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pool = get_pool()
    now = _utcnow()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO notification_inbox_state (
                item_type,
                item_id,
                actor,
                state,
                metadata,
                updated_at
            ) VALUES ($1,$2,$3,$4,$5::jsonb,$6)
            ON CONFLICT (item_type, item_id, actor)
            DO UPDATE SET
                state = EXCLUDED.state,
                metadata = EXCLUDED.metadata,
                updated_at = EXCLUDED.updated_at
            """,
            item_type,
            item_id,
            actor,
            state,
            json.dumps(metadata or {}),
            now,
        )
    return {
        "status": "updated",
        "actor": actor,
        "item_type": item_type,
        "item_id": item_id,
        "state": state,
        "updated_at": now,
    }


def _bulk_action_state(item_type: str, action: str) -> str:
    item_kind = str(item_type or "").strip().lower()
    action_key = str(action or "").strip().lower()
    if action_key == "acknowledge":
        return "acknowledged"
    if action_key == "dismiss":
        return "dismissed"
    if action_key == "reopen":
        return "new"
    if action_key == "complete":
        return "completed" if item_kind == "task" else "acknowledged"
    return "acknowledged"


async def bulk_update_notification_center(
    *,
    actor: str,
    action: str,
    items: list[dict[str, Any]],
    note: str | None = None,
) -> dict[str, Any]:
    action_key = str(action or "").strip().lower()
    results: list[dict[str, Any]] = []

    for item in items:
        item_type = str(item.get("item_type") or "").strip().lower()
        item_id = str(item.get("item_id") or "").strip()
        case_id = item.get("case_id")
        if not item_type or not item_id:
            results.append(
                {
                    "item_type": item_type or "unknown",
                    "item_id": item_id or "missing",
                    "case_id": case_id,
                    "action": action_key,
                    "status": "failed",
                    "message": "Inbox item reference is incomplete.",
                }
            )
            continue

        try:
            if item_type == "task" and action_key in {"complete", "reopen"}:
                if not case_id:
                    raise ValueError("Task items require a case_id for workflow updates.")
                task_status = CaseTaskStatus.done if action_key == "complete" else CaseTaskStatus.open
                task_update = await update_case_task(
                    UUID(str(case_id)),
                    UUID(item_id),
                    CaseTaskUpdate(
                        status=task_status,
                        note=note,
                        actor=actor,
                    ),
                )
                if not task_update:
                    raise ValueError("Task could not be updated from the inbox.")

            state = _bulk_action_state(item_type, action_key)
            updated = await update_notification_center_state(
                actor=actor,
                item_type=item_type,
                item_id=item_id,
                state=state,
                metadata={"source": "ui-inbox-bulk", "note": note, "action": action_key},
            )
            results.append(
                {
                    "item_type": item_type,
                    "item_id": item_id,
                    "case_id": case_id,
                    "action": action_key,
                    "status": "success",
                    "message": f"{item_type.title()} marked {updated['state']}.",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "item_type": item_type,
                    "item_id": item_id,
                    "case_id": case_id,
                    "action": action_key,
                    "status": "failed",
                    "message": str(exc),
                }
            )

    success_count = sum(1 for item in results if item["status"] == "success")
    failure_count = len(results) - success_count
    summary = [
        f"Processed {len(results)} inbox items for action {action_key}.",
        f"{success_count} succeeded and {failure_count} failed.",
    ]
    if note:
        summary.append("A bulk analyst note was attached to the inbox action.")
    return {
        "action": action_key,
        "processed_count": len(results),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
        "summary": summary,
        "generated_at": _utcnow(),
    }
