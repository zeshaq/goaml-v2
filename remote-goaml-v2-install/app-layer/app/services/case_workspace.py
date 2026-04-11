"""
Case workspace aggregation, pinned evidence, and filing readiness services.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from core.database import get_pool
from services.case_context import get_case_context
from services.case_playbooks import get_case_playbook_state
from services.cases import (
    get_case_detail,
    get_case_sar,
    list_case_events,
    list_case_notes,
    list_case_tasks,
    list_sar_queue,
)
from services.decision_quality import list_decision_feedback
from services.graph_sync import get_graph_drilldown
from services.workflow_engine import get_workflow_overview


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


def _normalize_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return _utcnow()


def _normalize_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["metadata"] = _normalize_json_dict(item.get("metadata"))
    item["pinned_at"] = _normalize_datetime(item.get("pinned_at"))
    item["updated_at"] = _normalize_datetime(item.get("updated_at"))
    return item


async def _record_case_event(
    conn: Any,
    *,
    case_id: UUID,
    event_type: str,
    actor: str | None,
    detail: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
        VALUES ($1, $2, $3, $4, $5::jsonb)
        """,
        case_id,
        event_type,
        actor,
        detail,
        json.dumps(metadata or {}),
    )


async def list_case_evidence(case_id: UUID) -> list[dict[str, Any]] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM cases WHERE id = $1", case_id)
        if not exists:
            return None
        rows = await conn.fetch(
            """
            SELECT *
            FROM case_evidence
            WHERE case_id = $1
            ORDER BY include_in_sar DESC, importance DESC, pinned_at DESC
            """,
            case_id,
        )
    return [_normalize_evidence_row(dict(row)) for row in rows]


async def pin_case_evidence(case_id: UUID, payload: dict[str, Any]) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            case_ref = await conn.fetchval("SELECT case_ref FROM cases WHERE id = $1 FOR UPDATE", case_id)
            if not case_ref:
                return None

            row = await conn.fetchrow(
                """
                INSERT INTO case_evidence (
                    case_id,
                    evidence_type,
                    source_evidence_id,
                    title,
                    summary,
                    source,
                    importance,
                    include_in_sar,
                    pinned_by,
                    metadata
                ) VALUES (
                    $1,
                    $2,
                    $3,
                    $4,
                    $5,
                    $6,
                    $7,
                    $8,
                    $9,
                    $10::jsonb
                )
                ON CONFLICT (case_id, evidence_type, source_evidence_id)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    source = EXCLUDED.source,
                    importance = EXCLUDED.importance,
                    include_in_sar = EXCLUDED.include_in_sar,
                    pinned_by = EXCLUDED.pinned_by,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                RETURNING *
                """,
                case_id,
                payload.get("evidence_type"),
                payload.get("source_evidence_id"),
                payload.get("title"),
                payload.get("summary"),
                payload.get("source"),
                int(payload.get("importance") or 50),
                bool(payload.get("include_in_sar")),
                payload.get("pinned_by"),
                json.dumps(payload.get("metadata") or {}),
            )

            await _record_case_event(
                conn,
                case_id=case_id,
                event_type="evidence_pinned",
                actor=payload.get("pinned_by"),
                detail=f"Pinned {payload.get('evidence_type', 'evidence').replace('_', ' ')}: {payload.get('title')}",
                metadata={
                    "evidence_type": payload.get("evidence_type"),
                    "source_evidence_id": payload.get("source_evidence_id"),
                    "include_in_sar": bool(payload.get("include_in_sar")),
                    "importance": int(payload.get("importance") or 50),
                },
            )
    return _normalize_evidence_row(dict(row)) if row else None


async def update_case_evidence(case_id: UUID, evidence_id: UUID, payload: dict[str, Any]) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM case_evidence WHERE id = $1 AND case_id = $2 FOR UPDATE",
                evidence_id,
                case_id,
            )
            if not row:
                return None

            current = dict(row)
            metadata = _normalize_json_dict(current.get("metadata"))
            if payload.get("metadata") is not None:
                metadata.update(payload.get("metadata") or {})

            updated = await conn.fetchrow(
                """
                UPDATE case_evidence
                SET
                    title = COALESCE($3, title),
                    summary = COALESCE($4, summary),
                    importance = COALESCE($5, importance),
                    include_in_sar = COALESCE($6, include_in_sar),
                    metadata = $7::jsonb,
                    updated_at = NOW()
                WHERE id = $1 AND case_id = $2
                RETURNING *
                """,
                evidence_id,
                case_id,
                payload.get("title"),
                payload.get("summary"),
                payload.get("importance"),
                payload.get("include_in_sar"),
                json.dumps(metadata),
            )

            await _record_case_event(
                conn,
                case_id=case_id,
                event_type="evidence_updated",
                actor=payload.get("updated_by"),
                detail=f"Updated pinned evidence: {payload.get('title') or current.get('title')}",
                metadata={
                    "evidence_id": str(evidence_id),
                    "include_in_sar": payload.get("include_in_sar"),
                    "importance": payload.get("importance"),
                },
            )
    return _normalize_evidence_row(dict(updated)) if updated else None


async def delete_case_evidence(case_id: UUID, evidence_id: UUID, removed_by: str | None = None) -> bool | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM case_evidence WHERE id = $1 AND case_id = $2 FOR UPDATE",
                evidence_id,
                case_id,
            )
            if not row:
                case_exists = await conn.fetchval("SELECT 1 FROM cases WHERE id = $1", case_id)
                return None if not case_exists else False

            await conn.execute("DELETE FROM case_evidence WHERE id = $1", evidence_id)
            await _record_case_event(
                conn,
                case_id=case_id,
                event_type="evidence_removed",
                actor=removed_by,
                detail=f"Removed pinned evidence: {row['title']}",
                metadata={"evidence_id": str(evidence_id), "evidence_type": row["evidence_type"]},
            )
    return True


def _filter_case_notifications(case_id: UUID, case_ref: str, notifications: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for item in notifications:
        metadata = _normalize_json_dict(item.get("metadata"))
        case_refs = metadata.get("case_refs") if isinstance(metadata.get("case_refs"), list) else []
        if item.get("case_id") == case_id or case_ref in case_refs:
            enriched = dict(item)
            enriched["metadata"] = metadata
            enriched["deeplink"] = f"/#case-command?case={case_id}"
            matched.append(enriched)
    return matched


def _expected_role_for_case(*, queue_item: dict[str, Any] | None, active_task: dict[str, Any] | None, case_row: dict[str, Any]) -> str | None:
    task_name = str((active_task or {}).get("name") or "").lower()
    sar_id = case_row.get("sar_id")
    if "review" in task_name or "triage" in task_name:
        return "reviewer"
    if "approve" in task_name:
        return "approver"
    if queue_item and str(queue_item.get("sar_status") or "").lower() == "approved":
        return "approver"
    if sar_id:
        return "analyst"
    return "investigator"


async def get_case_workflow_state(case_id: UUID) -> dict[str, Any] | None:
    case_row = await get_case_detail(case_id)
    if not case_row:
        return None

    pool = get_pool()
    workflow_overview, sar_queue = await asyncio.gather(
        get_workflow_overview(),
        list_sar_queue(queue="all", limit=250, offset=0),
    )
    case_ref = str(case_row["case_ref"])
    queue_item = next((item for item in sar_queue.get("items", []) if str(item.get("case_id")) == str(case_id)), None)
    owner_workload = next(
        (item for item in workflow_overview.get("owner_workload", []) if item.get("owner") == case_row.get("assigned_to")),
        None,
    )
    camunda = workflow_overview.get("camunda", {})
    tracked_process = next(
        (
            item
            for item in camunda.get("tracked_processes", [])
            if str(item.get("case_id")) == str(case_id) or item.get("business_key") == case_ref
        ),
        None,
    )
    active_task = None
    if tracked_process:
        active_task = next(
            (
                item
                for item in camunda.get("tasks", [])
                if item.get("process_instance_id") == tracked_process.get("process_instance_id")
            ),
            None,
        )

    notifications = _filter_case_notifications(
        case_id,
        case_ref,
        workflow_overview.get("recent_notifications", []),
    )
    routing = _normalize_json_dict(case_row.get("metadata", {}).get("routing"))
    expected_role = _expected_role_for_case(queue_item=queue_item, active_task=active_task, case_row=case_row)

    async with pool.acquire() as conn:
        process_rows = await conn.fetch(
            """
            SELECT *
            FROM orchestration_runs
            WHERE case_id = $1
            ORDER BY started_at DESC
            LIMIT 8
            """,
            case_id,
        )
    process_history = []
    for row in process_rows:
        item = dict(row)
        item["metadata"] = _normalize_json_dict(item.get("metadata"))
        process_history.append(item)

    latest_automation_touches = [
        {
            "source": item.get("notification_type"),
            "channel": item.get("channel"),
            "status": item.get("status"),
            "subject": item.get("subject"),
            "created_at": item.get("created_at"),
            "deeplink": item.get("deeplink"),
        }
        for item in notifications[:5]
    ]

    summary = [
        f"Routing: {routing.get('team_label', 'Global AML Operations')} / {routing.get('region_label', 'Global')}",
        f"Assigned to {case_row.get('assigned_to') or 'unassigned'}",
    ]
    if queue_item:
        summary.append(
            f"SAR queue status {queue_item.get('sla_status') or 'n/a'} with due time {queue_item.get('sla_due_at') or 'not scheduled'}."
        )
    if tracked_process:
        summary.append(
            f"Camunda process {tracked_process.get('workflow_label') or tracked_process.get('workflow_key')} is active."
        )
    if expected_role:
        summary.append(f"Expected next role: {expected_role}.")
    if notifications:
        summary.append(f"{len(notifications)} notification events are linked to this case.")

    return {
        "case_id": case_id,
        "case_ref": case_ref,
        "routing": routing,
        "queue_item": queue_item,
        "owner_workload": owner_workload,
        "active_process": tracked_process,
        "active_task": active_task,
        "expected_role": expected_role,
        "process_history": process_history,
        "latest_automation_touches": latest_automation_touches,
        "quick_links": {
            "workflow_ops": "/#workflow-ops",
            "n8n": "/#n8n",
            "camunda": "/#camunda",
            "command_center": f"/#case-command?case={case_id}",
        },
        "notifications": notifications,
        "summary": summary,
        "generated_at": _utcnow(),
    }


async def get_case_filing_readiness(case_id: UUID) -> dict[str, Any] | None:
    case_row = await get_case_detail(case_id)
    if not case_row:
        return None

    sar_row, evidence, context, workflow_state = await asyncio.gather(
        get_case_sar(case_id),
        list_case_evidence(case_id),
        get_case_context(case_id=case_id, document_limit=4, related_limit=6),
        get_case_workflow_state(case_id),
    )
    evidence = evidence or []
    context = context or {}
    workflow_state = workflow_state or {}
    sar_status = sar_row.get("status") if sar_row else None
    pinned_count = len(evidence)
    filing_evidence_count = sum(1 for item in evidence if item.get("include_in_sar"))
    direct_document_count = len(context.get("direct_documents") or [])
    screening_hit_count = len(context.get("screening_hits") or [])
    graph_summary_count = len((context.get("graph") or {}).get("summary") or [])
    latest_note = _normalize_json_dict((sar_row or {}).get("metadata")).get("latest_workflow_note")
    screening_required = bool(case_row.get("primary_entity_id"))
    screening_reviewed = (screening_hit_count > 0) or (not screening_required)

    blocking_items: list[str] = []
    warning_items: list[str] = []
    passed_checks: list[str] = []
    recommended_next_actions: list[str] = []

    def check(condition: bool, success: str, failure: str, *, blocking: bool) -> None:
        if condition:
            passed_checks.append(success)
        elif blocking:
            blocking_items.append(failure)
            recommended_next_actions.append(failure)
        else:
            warning_items.append(failure)
            recommended_next_actions.append(failure)

    check(bool(case_row.get("assigned_to")), "Case has an assigned analyst.", "Assign the case to an analyst.", blocking=True)
    check(bool(sar_row), "SAR draft exists.", "Draft a SAR before moving to formal review.", blocking=True)
    check(bool((sar_row or {}).get("narrative")), "SAR narrative is present.", "Generate or refine the SAR narrative.", blocking=True)
    check(
        bool(pinned_count),
        "Pinned evidence exists for this case.",
        "Pin at least one evidence item before filing.",
        blocking=True,
    )
    check(
        bool(filing_evidence_count),
        "At least one pinned evidence item is marked for SAR inclusion.",
        "Mark pinned evidence for SAR inclusion.",
        blocking=True,
    )
    check(
        bool(direct_document_count),
        "Case has attached evidence documents.",
        "Attach at least one direct evidence document.",
        blocking=False,
    )
    check(
        bool(graph_summary_count),
        "Graph context is available.",
        "Review graph relationships for this case.",
        blocking=False,
    )
    check(
        screening_reviewed,
        "Screening context is available for review.",
        "Review linked screening context for the primary entity.",
        blocking=False,
    )

    review_required = sar_status in {"pending_review", "approved", "filed"}
    approve_required = sar_status in {"approved", "filed"}
    check(
        (not review_required) or bool(latest_note),
        "Reviewer workflow note is present.",
        "Add a reviewer note before final approval.",
        blocking=False,
    )
    check(
        (not approve_required) or bool((sar_row or {}).get("approved_by")),
        "Approver is recorded.",
        "Approve the SAR before filing.",
        blocking=True,
    )
    check(
        sar_status in {"approved", "filed"},
        "SAR is approved or filed.",
        "Advance the SAR to approved status.",
        blocking=True,
    )

    total_checks = len(blocking_items) + len(warning_items) + len(passed_checks)
    score = int(round((len(passed_checks) / total_checks) * 100)) if total_checks else 0
    if sar_status == "filed" and not blocking_items:
        overall_status = "filed"
    elif blocking_items:
        overall_status = "blocked"
    elif warning_items:
        overall_status = "needs_review"
    elif sar_status == "approved":
        overall_status = "ready"
    else:
        overall_status = "in_progress"

    recommended_next_actions = list(dict.fromkeys(recommended_next_actions))[:8]

    playbook = await get_case_playbook_state(
        case_id,
        case_row=case_row,
        sar_row=sar_row or {},
        evidence=evidence,
        tasks=_normalize_json_list(case_row.get("metadata", {}).get("tasks")),
        direct_document_count=direct_document_count,
        screening_hit_count=screening_hit_count,
        alert_count=len(context.get("alerts") or []),
        transaction_count=len(context.get("transactions") or []),
    )
    if playbook:
        blocking_items = list(dict.fromkeys(blocking_items + [f"Playbook: {item}" for item in playbook.get("blocked_steps", [])]))
        warning_items = list(
            dict.fromkeys(
                warning_items + [f"Playbook evidence: {item}" for item in playbook.get("required_evidence_missing", [])]
            )
        )
        passed_checks = list(
            dict.fromkeys(
                passed_checks
                + (
                    [f"Playbook checklist {playbook.get('checklist_completed_count', 0)}/{playbook.get('checklist_total_count', 0)} completed."]
                    if playbook.get("checklist_total_count")
                    else []
                )
            )
        )
        recommended_next_actions = list(
            dict.fromkeys(
                recommended_next_actions
                + [f"Resolve playbook step: {item}" for item in playbook.get("blocked_steps", [])]
                + [f"Add required evidence: {item}" for item in playbook.get("required_evidence_missing", [])]
            )
        )[:10]

        total_checks = len(blocking_items) + len(warning_items) + len(passed_checks)
        score = int(round((len(passed_checks) / total_checks) * 100)) if total_checks else score
        if blocking_items:
            overall_status = "blocked"
        elif warning_items and overall_status == "ready":
            overall_status = "needs_review"

    return {
        "case_id": case_id,
        "case_ref": case_row["case_ref"],
        "sar_id": (sar_row or {}).get("id"),
        "sar_status": sar_status,
        "overall_status": overall_status,
        "score": score,
        "blocking_items": blocking_items,
        "warning_items": warning_items,
        "passed_checks": passed_checks,
        "recommended_next_actions": recommended_next_actions,
        "playbook": playbook,
        "generated_at": _utcnow(),
    }


async def get_case_workspace(case_id: UUID, document_limit: int = 4, related_limit: int = 6) -> dict[str, Any] | None:
    case_row = await get_case_detail(case_id)
    if not case_row:
        return None

    sar_row = await get_case_sar(case_id)
    sar_payload = None if sar_row == {} else sar_row

    events, context, graph, tasks, notes, workflow_state, evidence, filing_readiness, feedback = await asyncio.gather(
        list_case_events(case_id=case_id, limit=60, offset=0, order="desc"),
        get_case_context(case_id=case_id, document_limit=document_limit, related_limit=related_limit),
        get_graph_drilldown(node_id=f"case:{case_id}", hops=2, limit=18),
        list_case_tasks(case_id),
        list_case_notes(case_id),
        get_case_workflow_state(case_id),
        list_case_evidence(case_id),
        get_case_filing_readiness(case_id),
        list_decision_feedback("case", case_id, limit=20),
    )

    return {
        "case": case_row,
        "events": events or [],
        "sar": sar_payload,
        "context": context,
        "graph": graph,
        "tasks": tasks or [],
        "notes": notes or [],
        "feedback": feedback or [],
        "workflow": workflow_state,
        "pinned_evidence": evidence or [],
        "filing_readiness": filing_readiness,
        "playbook": (filing_readiness or {}).get("playbook"),
    }
