"""
Operational workflow services for routing, notifications, n8n, and Camunda.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import json
import smtplib
from typing import Any
from uuid import UUID, uuid4

import httpx

from core.config import settings
from core.database import get_pool
from services.routing import analyst_directory, resolve_case_routing


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


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_json_map(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _directory_by_name() -> dict[str, dict[str, Any]]:
    return {item["name"]: item for item in analyst_directory()}


def _channel_status() -> dict[str, Any]:
    slack_map = _parse_json_map(settings.TEAM_SLACK_WEBHOOKS_JSON)
    email_map = _parse_json_map(settings.TEAM_EMAIL_RECIPIENTS_JSON)
    return {
        "slack": {
            "configured": bool(settings.SLACK_WEBHOOK_URL) or bool(slack_map),
            "mode": "team_map" if slack_map else ("global" if settings.SLACK_WEBHOOK_URL else "not_configured"),
        },
        "email": {
            "configured": bool(settings.SMTP_HOST and (settings.SLA_NOTIFICATION_EMAIL_TO or email_map)),
            "mode": "team_map" if email_map else ("global" if settings.SLA_NOTIFICATION_EMAIL_TO else "not_configured"),
        },
    }


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _titleize(value: Any) -> str:
    return str(value or "").replace("_", " ").strip().title()


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


def _hours_between(start: datetime | None, end: datetime | None = None) -> float | None:
    if not start:
        return None
    stop = end or _utcnow()
    return round((stop - start).total_seconds() / 3600.0, 2)


def _case_tasks(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _normalize_json_list(metadata.get("tasks")) if isinstance(item, dict)]


def _workflow_history_timestamp(history: list[dict[str, Any]], *, action: str | None = None, status: str | None = None) -> datetime | None:
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


def _max_priority(current: str | None, proposed: str | None) -> str:
    rank = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    current_key = str(current or "medium").lower()
    proposed_key = str(proposed or "medium").lower()
    return proposed_key if rank.get(proposed_key, 0) > rank.get(current_key, 0) else current_key


def _playbook_stage_context(case_row: dict[str, Any]) -> dict[str, Any]:
    case_status = str(case_row.get("status") or "").lower()
    sar_status = str(case_row.get("sar_status") or "").lower()
    sar_history = [item for item in _normalize_json_list(_normalize_json_dict(case_row.get("sar_metadata")).get("workflow_history")) if isinstance(item, dict)]
    created_at = _safe_datetime(case_row.get("created_at"))
    updated_at = _safe_datetime(case_row.get("updated_at"))
    if sar_status == "approved":
        started_at = _workflow_history_timestamp(sar_history, action="approve") or _workflow_history_timestamp(sar_history, status="approved") or updated_at or created_at
        return {"queue_key": "approval", "started_at": started_at, "label": "approval"}
    if sar_status == "pending_review":
        started_at = _workflow_history_timestamp(sar_history, action="submit_review") or _workflow_history_timestamp(sar_history, status="pending_review") or updated_at or created_at
        return {"queue_key": "review", "started_at": started_at, "label": "review"}
    if case_status in {"sar_filed", "closed"}:
        return {"queue_key": None, "started_at": updated_at or created_at, "label": "closed"}
    return {"queue_key": "draft", "started_at": created_at, "label": "draft"}


async def _manager_actor_for_case(conn: Any, *, team_key: str | None) -> str:
    manager = await conn.fetchval(
        """
        SELECT username
        FROM app_users
        WHERE role_key = 'manager'
          AND is_active = TRUE
          AND ($1::varchar IS NULL OR team_key = $1 OR team_key = 'global_ops')
        ORDER BY CASE WHEN team_key = $1 THEN 0 ELSE 1 END, username ASC
        LIMIT 1
        """,
        team_key,
    )
    return str(manager or "manager1")


async def _record_notification_event(
    *,
    conn: Any | None = None,
    notification_type: str,
    channel: str,
    severity: str,
    status: str,
    subject: str,
    target: str | None,
    team_key: str | None,
    region_key: str | None,
    case_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    async def _insert(target_conn: Any) -> None:
        await target_conn.execute(
            """
            INSERT INTO notification_events (
                notification_type, channel, severity, status, subject, target,
                team_key, region_key, case_id, metadata, delivered_at
            ) VALUES (
                $1::varchar, $2::varchar, $3::varchar, $4::varchar, $5::varchar, $6::varchar,
                $7::varchar, $8::varchar, $9, $10::jsonb,
                CASE WHEN $4::varchar = 'sent' THEN NOW() ELSE NULL END
            )
            """,
            notification_type,
            channel,
            severity,
            status,
            subject,
            target,
            team_key,
            region_key,
            case_id,
            json.dumps(metadata or {}),
        )

    if conn is not None:
        await _insert(conn)
        return

    pool = get_pool()
    async with pool.acquire() as target_conn:
        await _insert(target_conn)


async def _create_or_reuse_automation_task(
    conn: Any,
    *,
    case_id: UUID,
    metadata: dict[str, Any],
    actor: str,
    automation_key: str,
    title: str,
    description: str,
    assigned_to: str | None,
    priority: str = "high",
    note: str | None = None,
) -> tuple[UUID | None, bool]:
    tasks = _case_tasks(metadata)
    for task in tasks:
        task_metadata = _normalize_json_dict(task.get("metadata"))
        if str(task_metadata.get("automation_key") or "") != automation_key:
            continue
        if str(task.get("status") or "open").lower() == "done":
            continue
        task["updated_at"] = _utcnow().isoformat()
        metadata["tasks"] = tasks[-100:]
        return (UUID(str(task["id"])) if task.get("id") else None), False

    task_id = uuid4()
    now_iso = _utcnow().isoformat()
    tasks.append(
        {
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
            "metadata": {
                "automation_key": automation_key,
                "automation_actor": actor,
                "automation_type": "playbook",
            },
        }
    )
    metadata["tasks"] = tasks[-100:]
    await conn.execute(
        """
        INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
        VALUES ($1, 'task_created', $2, $3, $4::jsonb)
        """,
        case_id,
        actor,
        f"Task created: {title}",
        json.dumps({"task_id": str(task_id), "assigned_to": assigned_to, "priority": priority, "automation_key": automation_key}),
    )
    return task_id, True


async def _record_playbook_app_notification(
    *,
    notification_type: str,
    severity: str,
    subject: str,
    team_key: str | None,
    region_key: str | None,
    case_id: UUID,
    metadata: dict[str, Any],
) -> None:
    await _record_notification_event(
        notification_type=notification_type,
        channel="app",
        severity=severity,
        status="sent",
        subject=subject,
        target=f"/#case-command?case={case_id}",
        team_key=team_key,
        region_key=region_key,
        case_id=case_id,
        metadata=metadata,
    )


async def run_playbook_automation(
    *,
    triggered_by: str | None = None,
    stuck_hours: float | None = None,
    evidence_gap_warning_hours: float | None = None,
    cooldown_hours: float | None = None,
    limit: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    from services.case_playbooks import get_case_playbook_state, resolve_playbook_sla_hours

    actor = triggered_by or settings.PLAYBOOK_AUTOMATION_WORKFLOW_ACTOR
    runtime_settings = await get_playbook_automation_settings()
    stuck_threshold = float(stuck_hours or runtime_settings["stuck_hours"])
    evidence_threshold = float(evidence_gap_warning_hours or runtime_settings["evidence_gap_warning_hours"])
    cooldown = float(cooldown_hours or runtime_settings["cooldown_hours"])
    batch_limit = int(limit or runtime_settings["max_cases"])

    pool = get_pool()
    async with pool.acquire() as conn:
        case_rows = await conn.fetch(
            """
            SELECT
                c.id,
                c.case_ref,
                c.title,
                c.status,
                c.priority,
                c.assigned_to,
                c.primary_entity_id,
                c.primary_account_id,
                c.metadata,
                c.created_at,
                c.updated_at,
                s.status AS sar_status,
                s.metadata AS sar_metadata
            FROM cases c
            LEFT JOIN sar_reports s ON s.id = c.sar_id
            WHERE c.status NOT IN ('closed', 'sar_filed')
              AND COALESCE(c.metadata->'playbook'->>'typology', '') <> ''
            ORDER BY c.updated_at ASC
            LIMIT $1
            """,
            batch_limit,
        )

    processed_count = 0
    stuck_items: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []

    for raw_row in case_rows:
        case_row = dict(raw_row)
        playbook = await get_case_playbook_state(UUID(str(case_row["id"])), case_row=case_row)
        if not playbook:
            continue
        processed_count += 1

        metadata = _normalize_json_dict(case_row.get("metadata"))
        routing = _normalize_json_dict(metadata.get("routing"))
        stage = _playbook_stage_context(case_row)
        queue_key = stage.get("queue_key")
        started_at = stage.get("started_at")
        age_hours = _hours_between(started_at)
        sla_hours = resolve_playbook_sla_hours(
            queue_key=queue_key,
            case_metadata=metadata,
            case_priority=case_row.get("priority"),
        ) if queue_key else None
        hours_remaining = round(float(sla_hours) - float(age_hours), 2) if sla_hours is not None and age_hours is not None else None

        blocked_steps = [str(item) for item in (playbook.get("blocked_steps") or []) if str(item).strip()]
        missing_evidence = [str(item) for item in (playbook.get("required_evidence_missing") or []) if str(item).strip()]

        automation_state = _normalize_json_dict(metadata.get("playbook_automation"))
        now = _utcnow()
        current_assignee = case_row.get("assigned_to") or routing.get("assignee") or actor

        if blocked_steps and (force or (_hours_between(_safe_datetime(case_row.get("updated_at")), now) or 0) >= stuck_threshold):
            blocked_signature = "|".join(sorted(blocked_steps))
            stuck_state = _normalize_json_dict(automation_state.get("stuck_checklist"))
            last_notified_at = _safe_datetime(stuck_state.get("last_notified_at"))
            should_fire = force or blocked_signature != str(stuck_state.get("signature") or "")
            if not should_fire and last_notified_at:
                should_fire = (_hours_between(last_notified_at, now) or 0) >= cooldown
            if should_fire:
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        locked = await conn.fetchrow(
                            "SELECT metadata, priority FROM cases WHERE id = $1 FOR UPDATE",
                            case_row["id"],
                        )
                        if not locked:
                            continue
                        locked_metadata = _normalize_json_dict(locked.get("metadata"))
                        task_id, created = await _create_or_reuse_automation_task(
                            conn,
                            case_id=case_row["id"],
                            metadata=locked_metadata,
                            actor=actor,
                            automation_key=f"playbook_stuck::{blocked_signature}",
                            title="Resolve blocked playbook steps",
                            description=f"The active {playbook.get('display_name')} playbook is stalled on: {', '.join(blocked_steps[:4])}.",
                            assigned_to=current_assignee,
                            priority="high",
                            note=f"Checklist blocked for approximately {round(_hours_between(_safe_datetime(case_row.get('updated_at')), now) or 0, 1)} hours.",
                        )
                        current_auto_state = _normalize_json_dict(locked_metadata.get("playbook_automation"))
                        locked_metadata["playbook_automation"] = {
                            **current_auto_state,
                            "stuck_checklist": {
                                "signature": blocked_signature,
                                "last_notified_at": now.isoformat(),
                                "task_id": str(task_id) if task_id else None,
                                "blocked_steps": blocked_steps,
                            },
                        }
                        await conn.execute(
                            "UPDATE cases SET metadata = $2::jsonb, updated_at = NOW() WHERE id = $1",
                            case_row["id"],
                            json.dumps(locked_metadata),
                        )
                        await conn.execute(
                            """
                            INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                            VALUES ($1, 'playbook_stuck_flagged', $2, $3, $4::jsonb)
                            """,
                            case_row["id"],
                            actor,
                            "Checklist automation flagged blocked playbook steps",
                            json.dumps({"blocked_steps": blocked_steps, "task_id": str(task_id) if task_id else None, "created_task": created}),
                        )
                await _record_playbook_app_notification(
                    notification_type="playbook_stuck_case",
                    severity="warning",
                    subject=f"goAML playbook blocker - {case_row['case_ref']}",
                    team_key=routing.get("team_key"),
                    region_key=routing.get("region_key"),
                    case_id=case_row["id"],
                    metadata={
                        "message": f"{playbook.get('display_name')} is blocked on {', '.join(blocked_steps[:3])}.",
                        "deeplink": f"/#case-command?case={case_row['id']}",
                        "blocked_steps": blocked_steps,
                        "playbook_typology": playbook.get("typology"),
                    },
                )
                stuck_items.append(
                    {
                        "case_id": str(case_row["id"]),
                        "case_ref": case_row["case_ref"],
                        "assigned_to": current_assignee,
                        "team_key": routing.get("team_key"),
                        "blocked_steps": blocked_steps,
                    }
                )

        if missing_evidence and hours_remaining is not None and (force or hours_remaining <= evidence_threshold):
            evidence_signature = "|".join(sorted(missing_evidence))
            evidence_state = _normalize_json_dict(automation_state.get("evidence_gap"))
            last_notified_at = _safe_datetime(evidence_state.get("last_notified_at"))
            should_fire = force or evidence_signature != str(evidence_state.get("signature") or "")
            if not should_fire and last_notified_at:
                should_fire = (_hours_between(last_notified_at, now) or 0) >= cooldown
            if should_fire:
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        locked = await conn.fetchrow(
                            "SELECT metadata, priority, status, assigned_to FROM cases WHERE id = $1 FOR UPDATE",
                            case_row["id"],
                        )
                        if not locked:
                            continue
                        locked_metadata = _normalize_json_dict(locked.get("metadata"))
                        manager_actor = await _manager_actor_for_case(conn, team_key=routing.get("team_key"))
                        analyst_task_id, _ = await _create_or_reuse_automation_task(
                            conn,
                            case_id=case_row["id"],
                            metadata=locked_metadata,
                            actor=actor,
                            automation_key=f"playbook_evidence_gap::{evidence_signature}::analyst",
                            title="Resolve required evidence gap",
                            description=f"Required evidence is still missing before the case reaches {stage.get('label')} SLA: {', '.join(missing_evidence[:4])}.",
                            assigned_to=locked.get("assigned_to") or current_assignee,
                            priority="high",
                            note=f"{round(hours_remaining, 1)} hours remain before the active playbook SLA target is breached." if hours_remaining is not None else None,
                        )
                        manager_task_id, _ = await _create_or_reuse_automation_task(
                            conn,
                            case_id=case_row["id"],
                            metadata=locked_metadata,
                            actor=actor,
                            automation_key=f"playbook_evidence_gap::{evidence_signature}::manager",
                            title="Review evidence gap escalation",
                            description=f"Case {case_row['case_ref']} is near SLA breach with missing evidence: {', '.join(missing_evidence[:4])}.",
                            assigned_to=manager_actor,
                            priority="critical" if hours_remaining is not None and hours_remaining <= 2 else "high",
                            note=f"Escalated from the {playbook.get('display_name')} automation path.",
                        )
                        current_auto_state = _normalize_json_dict(locked_metadata.get("playbook_automation"))
                        locked_metadata["playbook_automation"] = {
                            **current_auto_state,
                            "evidence_gap": {
                                "signature": evidence_signature,
                                "last_notified_at": now.isoformat(),
                                "analyst_task_id": str(analyst_task_id) if analyst_task_id else None,
                                "manager_task_id": str(manager_task_id) if manager_task_id else None,
                                "missing_evidence": missing_evidence,
                                "hours_remaining": hours_remaining,
                            },
                        }
                        next_priority = _max_priority(str(locked.get("priority") or "medium"), "critical" if hours_remaining is not None and hours_remaining <= 2 else "high")
                        next_status = str(locked.get("status") or "open").lower()
                        if next_status in {"open", "referred"}:
                            next_status = "reviewing"
                        await conn.execute(
                            """
                            UPDATE cases
                            SET priority = $2::case_priority,
                                status = $3::case_status,
                                metadata = $4::jsonb,
                                updated_at = NOW()
                            WHERE id = $1
                            """,
                            case_row["id"],
                            next_priority,
                            next_status,
                            json.dumps(locked_metadata),
                        )
                        await conn.execute(
                            """
                            INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                            VALUES ($1, 'playbook_evidence_gap_escalated', $2, $3, $4::jsonb)
                            """,
                            case_row["id"],
                            actor,
                            "Playbook automation escalated missing evidence near SLA breach",
                            json.dumps(
                                {
                                    "missing_evidence": missing_evidence,
                                    "hours_remaining": hours_remaining,
                                    "analyst_task_id": str(analyst_task_id) if analyst_task_id else None,
                                    "manager_task_id": str(manager_task_id) if manager_task_id else None,
                                    "priority": next_priority,
                                    "status": next_status,
                                }
                            ),
                        )
                await _record_playbook_app_notification(
                    notification_type="playbook_evidence_gap_escalation",
                    severity="high" if hours_remaining is None or hours_remaining > 2 else "critical",
                    subject=f"goAML evidence gap escalation - {case_row['case_ref']}",
                    team_key=routing.get("team_key"),
                    region_key=routing.get("region_key"),
                    case_id=case_row["id"],
                    metadata={
                        "message": f"Required evidence is missing near SLA breach: {', '.join(missing_evidence[:3])}.",
                        "deeplink": f"/#case-command?case={case_row['id']}",
                        "missing_evidence": missing_evidence,
                        "playbook_typology": playbook.get("typology"),
                        "hours_remaining": hours_remaining,
                    },
                )
                evidence_items.append(
                    {
                        "case_id": str(case_row["id"]),
                        "case_ref": case_row["case_ref"],
                        "team_key": routing.get("team_key"),
                        "hours_remaining": hours_remaining,
                        "missing_evidence": missing_evidence,
                    }
                )

    return {
        "generated_at": _utcnow(),
        "processed_count": processed_count,
        "stuck_case_count": len(stuck_items),
        "evidence_gap_case_count": len(evidence_items),
        "stuck_cases": stuck_items,
        "evidence_gap_cases": evidence_items,
        "settings": runtime_settings,
        "summary": [
            f"Processed {processed_count} playbook-enabled cases.",
            f"Flagged {len(stuck_items)} stuck checklist case(s).",
            f"Escalated {len(evidence_items)} evidence gap case(s).",
        ],
    }


async def run_decision_quality_automation(
    *,
    triggered_by: str,
    lookback_hours: int = 168,
    noisy_threshold: int = 2,
    weak_sar_threshold: int = 1,
    missing_evidence_threshold: int = 1,
    cooldown_hours: float = 12,
    limit: int = 60,
    force: bool = False,
) -> dict[str, Any]:
    pool = get_pool()
    since = _utcnow() - timedelta(hours=max(1, int(lookback_hours)))
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                df.id,
                df.subject_type,
                df.subject_id,
                df.case_id,
                df.alert_id,
                df.feedback_key,
                df.created_at,
                c.id AS resolved_case_id,
                c.case_ref,
                c.assigned_to,
                c.priority,
                c.status AS case_status,
                c.metadata AS case_metadata,
                a.alert_ref,
                a.alert_type,
                a.status AS alert_status
            FROM decision_feedback df
            LEFT JOIN cases c ON c.id = COALESCE(df.case_id, CASE WHEN df.subject_type = 'case' THEN df.subject_id ELSE NULL END)
            LEFT JOIN alerts a ON a.id = COALESCE(df.alert_id, CASE WHEN df.subject_type = 'alert' THEN df.subject_id ELSE NULL END)
            WHERE df.created_at >= $1
            ORDER BY df.created_at DESC
            LIMIT $2
            """,
            since,
            max(10, min(int(limit) * 8, 2000)),
        )

    noisy_hotspots: dict[tuple[str, str, str], dict[str, Any]] = {}
    weak_sar_cases: dict[str, dict[str, Any]] = {}
    missing_evidence_cases: dict[str, dict[str, Any]] = {}
    processed_feedback_count = 0

    for raw in rows:
        row = dict(raw)
        processed_feedback_count += 1
        feedback_key = str(row.get("feedback_key") or "").lower()
        case_metadata = _normalize_json_dict(row.get("case_metadata"))
        routing = _normalize_json_dict(case_metadata.get("routing"))
        team_key = str(routing.get("team_key") or case_metadata.get("team_key") or settings.OPS_ALERT_DEFAULT_TEAM)
        region_key = str(routing.get("region_key") or case_metadata.get("region_key") or settings.OPS_ALERT_DEFAULT_REGION)
        typology = str(row.get("alert_type") or _normalize_json_dict(case_metadata.get("playbook")).get("typology") or case_metadata.get("typology") or "unknown").lower()

        if feedback_key == "noisy_alert":
            bucket = noisy_hotspots.setdefault(
                (typology, team_key, region_key),
                {
                    "typology": typology,
                    "team_key": team_key,
                    "region_key": region_key,
                    "count": 0,
                },
            )
            bucket["count"] += 1
        elif feedback_key == "weak_sar_draft" and row.get("resolved_case_id"):
            case_id = str(row["resolved_case_id"])
            bucket = weak_sar_cases.setdefault(
                case_id,
                {
                    "case_id": row["resolved_case_id"],
                    "case_ref": row.get("case_ref"),
                    "assigned_to": row.get("assigned_to"),
                    "team_key": team_key,
                    "region_key": region_key,
                    "count": 0,
                },
            )
            bucket["count"] += 1
        elif feedback_key == "missing_evidence" and row.get("resolved_case_id"):
            case_id = str(row["resolved_case_id"])
            bucket = missing_evidence_cases.setdefault(
                case_id,
                {
                    "case_id": row["resolved_case_id"],
                    "case_ref": row.get("case_ref"),
                    "assigned_to": row.get("assigned_to"),
                    "team_key": team_key,
                    "region_key": region_key,
                    "count": 0,
                },
            )
            bucket["count"] += 1

    items: list[dict[str, Any]] = []
    noisy_count = 0
    weak_count = 0
    missing_count = 0

    async with pool.acquire() as conn:
        async with conn.transaction():
            for hotspot in sorted(noisy_hotspots.values(), key=lambda item: item["count"], reverse=True):
                if hotspot["count"] < noisy_threshold and not force:
                    continue
                subject_key = f"noisy::{hotspot['typology']}::{hotspot['team_key']}::{hotspot['region_key']}"
                if not force and await _decision_quality_notification_recent(
                    conn,
                    notification_type="decision_quality_noisy_alert_hotspot",
                    subject_key=subject_key,
                    cooldown_hours=cooldown_hours,
                ):
                    continue
                noisy_count += 1
                await _record_notification_event(
                    conn=conn,
                    notification_type="decision_quality_noisy_alert_hotspot",
                    channel="app",
                    severity="warning" if hotspot["count"] < max(noisy_threshold + 2, 4) else "critical",
                    status="sent",
                    subject=f"Decision quality hotspot - {_titleize(hotspot['typology'])}",
                    target="/#reports",
                    team_key=hotspot["team_key"],
                    region_key=hotspot["region_key"],
                    metadata={
                        "subject_key": subject_key,
                        "message": f"{hotspot['count']} noisy-alert signals were recorded for {_titleize(hotspot['typology'])}.",
                        "deeplink": "/#reports",
                        "typology": hotspot["typology"],
                        "metric": "decision_alert_precision",
                    },
                )
                items.append(
                    {
                        "subject_type": "typology",
                        "subject_key": subject_key,
                        "title": f"Noisy alert hotspot - {_titleize(hotspot['typology'])}",
                        "severity": "warning" if hotspot["count"] < max(noisy_threshold + 2, 4) else "critical",
                        "count": hotspot["count"],
                        "team_key": hotspot["team_key"],
                        "region_key": hotspot["region_key"],
                        "note": "Manager review recommended for alert quality and typology tuning.",
                        "deep_link": "/#reports",
                        "metadata": {"metric": "decision_alert_precision", "typology": hotspot["typology"]},
                    }
                )

            for case_group, threshold, notification_type, title, description, severity, automation_key in (
                (weak_sar_cases, weak_sar_threshold, "decision_quality_weak_sar_draft", "Revise SAR draft from feedback", "Recent reviewers flagged the SAR draft as weak and needing stronger synthesis.", "warning", "decision_quality_weak_sar"),
                (missing_evidence_cases, missing_evidence_threshold, "decision_quality_missing_evidence", "Resolve missing evidence before next decision", "Recent feedback indicates missing evidence is reducing decision quality.", "warning", "decision_quality_missing_evidence"),
            ):
                for case_info in sorted(case_group.values(), key=lambda item: item["count"], reverse=True):
                    if case_info["count"] < threshold and not force:
                        continue
                    locked = await conn.fetchrow(
                        "SELECT metadata, assigned_to FROM cases WHERE id = $1 FOR UPDATE",
                        case_info["case_id"],
                    )
                    if not locked:
                        continue
                    locked_metadata = _normalize_json_dict(locked.get("metadata"))
                    subject_key = f"{automation_key}::{case_info['case_id']}"
                    state = _normalize_json_dict(_normalize_json_dict(locked_metadata.get("decision_quality_automation")).get(automation_key))
                    last_notified_at = _safe_datetime(state.get("last_notified_at"))
                    if not force and last_notified_at and (_hours_between(last_notified_at, _utcnow()) or 0) < cooldown_hours:
                        continue
                    task_id, created = await _create_or_reuse_automation_task(
                        conn,
                        case_id=case_info["case_id"],
                        metadata=locked_metadata,
                        actor=triggered_by,
                        automation_key=subject_key,
                        title=title,
                        description=description,
                        assigned_to=locked.get("assigned_to") or case_info.get("assigned_to") or triggered_by,
                        priority="high",
                        note=f"{case_info['count']} quality signal(s) in the last {lookback_hours}h.",
                    )
                    current_state = _normalize_json_dict(locked_metadata.get("decision_quality_automation"))
                    current_state[automation_key] = {
                        "last_notified_at": _utcnow().isoformat(),
                        "count": case_info["count"],
                        "task_id": str(task_id) if task_id else None,
                    }
                    locked_metadata["decision_quality_automation"] = current_state
                    await conn.execute(
                        "UPDATE cases SET metadata = $2::jsonb, updated_at = NOW() WHERE id = $1",
                        case_info["case_id"],
                        json.dumps(locked_metadata),
                    )
                    await conn.execute(
                        """
                        INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                        VALUES ($1, 'decision_quality_intervention', $2, $3, $4::jsonb)
                        """,
                        case_info["case_id"],
                        triggered_by,
                        title,
                        json.dumps({"automation_key": automation_key, "signal_count": case_info["count"], "task_id": str(task_id) if task_id else None, "created_task": created}),
                    )
                    await _record_notification_event(
                        conn=conn,
                        notification_type=notification_type,
                        channel="app",
                        severity=severity,
                        status="sent",
                        subject=f"Decision quality intervention - {case_info['case_ref']}",
                        target=f"/#case-command?case={case_info['case_id']}",
                        team_key=case_info["team_key"],
                        region_key=case_info["region_key"],
                        case_id=case_info["case_id"],
                        metadata={
                            "subject_key": subject_key,
                            "message": description,
                            "deeplink": f"/#case-command?case={case_info['case_id']}",
                            "task_id": str(task_id) if task_id else None,
                        },
                    )
                    items.append(
                        {
                            "subject_type": "case",
                            "subject_key": subject_key,
                            "title": title,
                            "severity": severity,
                            "count": case_info["count"],
                            "team_key": case_info["team_key"],
                            "region_key": case_info["region_key"],
                            "case_id": case_info["case_id"],
                            "case_ref": case_info["case_ref"],
                            "note": description,
                            "deep_link": f"/#case-command?case={case_info['case_id']}",
                            "metadata": {"task_id": str(task_id) if task_id else None, "created_task": created},
                        }
                    )
                    if notification_type == "decision_quality_weak_sar_draft":
                        weak_count += 1
                    else:
                        missing_count += 1

    return {
        "triggered_at": _utcnow(),
        "triggered_by": triggered_by,
        "lookback_hours": lookback_hours,
        "processed_feedback_count": processed_feedback_count,
        "noisy_hotspot_count": noisy_count,
        "weak_sar_case_count": weak_count,
        "missing_evidence_case_count": missing_count,
        "items": items[: max(1, min(limit, len(items) or limit))],
        "summary": [
            f"Processed {processed_feedback_count} recent feedback item(s).",
            f"Triggered {noisy_count} noisy-alert hotspot intervention(s).",
            f"Triggered {weak_count} weak-SAR intervention(s) and {missing_count} missing-evidence intervention(s).",
        ],
    }


async def run_decision_quality_recommendation_automation(
    *,
    triggered_by: str,
    range_days: int = 180,
    recurring_periods: int = 2,
    noisy_threshold: float = 0.3,
    drafter_rejection_threshold: float = 0.2,
    cooldown_hours: float = 24,
    force: bool = False,
) -> dict[str, Any]:
    from services.decision_quality import capture_decision_quality_snapshot, get_decision_quality_snapshots

    await capture_decision_quality_snapshot(
        actor=triggered_by,
        snapshot_granularity="daily",
        range_days=range_days,
        source="automation",
        metadata={"automation": "decision_quality_recommendations"},
    )
    snapshots = await get_decision_quality_snapshots(
        snapshot_granularity="daily",
        range_days=range_days,
        limit=max(6, recurring_periods + 2),
        auto_capture=True,
    )
    points = list(snapshots.get("points") or [])
    items: list[dict[str, Any]] = []
    notification_count = 0
    latest_points = points[: max(2, recurring_periods)]

    def repeated_value(key: str) -> str | None:
        values = [str((point.get("summary_metrics") or {}).get(key) or "").strip() for point in latest_points]
        values = [value for value in values if value]
        if len(values) < recurring_periods:
            return None
        return values[0] if all(value == values[0] for value in values[:recurring_periods]) else None

    top_typology = repeated_value("top_noisy_typology")
    top_typology_rate = max(float((point.get("summary_metrics") or {}).get("top_noisy_rate") or 0.0) for point in latest_points) if latest_points else 0.0
    top_drafter = repeated_value("top_drafter")
    top_drafter_rejection = max(float((point.get("summary_metrics") or {}).get("top_drafter_rejection_rate") or 0.0) for point in latest_points) if latest_points else 0.0

    pool = get_pool()
    async with pool.acquire() as conn:
        if top_typology and (top_typology_rate >= noisy_threshold or force):
            subject_key = f"quality_recurring_typology::{top_typology}"
            if force or not await _decision_quality_notification_recent(
                conn,
                notification_type="decision_quality_recurring_typology",
                subject_key=subject_key,
                cooldown_hours=cooldown_hours,
            ):
                await _record_notification_event(
                    conn=conn,
                    notification_type="decision_quality_recurring_typology",
                    channel="app",
                    severity="critical" if top_typology_rate >= max(noisy_threshold + 0.1, 0.45) else "warning",
                    status="sent",
                    subject=f"Recurring quality hotspot - {_titleize(top_typology)}",
                    target="/#reports",
                    team_key=None,
                    region_key=None,
                    metadata={
                        "subject_key": subject_key,
                        "message": f"{_titleize(top_typology)} remained the noisiest typology for {recurring_periods} snapshot(s).",
                        "deeplink": "/#reports",
                        "metric": "decision_alert_precision",
                        "typology": top_typology,
                    },
                )
                items.append(
                    {
                        "subject_type": "typology",
                        "subject_key": subject_key,
                        "title": f"Recurring quality hotspot - {_titleize(top_typology)}",
                        "severity": "critical" if top_typology_rate >= max(noisy_threshold + 0.1, 0.45) else "warning",
                        "count": recurring_periods,
                        "note": "Manager review recommended because the same typology remained noisy across multiple quality snapshots.",
                        "deep_link": "/#reports",
                        "metadata": {"typology": top_typology, "metric": "decision_alert_precision"},
                    }
                )
                notification_count += 1

        if top_drafter and (top_drafter_rejection >= drafter_rejection_threshold or force):
            subject_key = f"quality_drafter_coaching::{top_drafter}"
            if force or not await _decision_quality_notification_recent(
                conn,
                notification_type="decision_quality_drafter_coaching",
                subject_key=subject_key,
                cooldown_hours=cooldown_hours,
            ):
                await _record_notification_event(
                    conn=conn,
                    notification_type="decision_quality_drafter_coaching",
                    channel="app",
                    severity="warning",
                    status="sent",
                    subject=f"Reviewer coaching hotspot - {top_drafter}",
                    target="/#reports",
                    team_key=None,
                    region_key=None,
                    metadata={
                        "subject_key": subject_key,
                        "message": f"{top_drafter} remained the highest drafter rejection hotspot for {recurring_periods} snapshot(s).",
                        "deeplink": "/#reports",
                        "metric": "reviewer_quality",
                        "actor": top_drafter,
                    },
                )
                items.append(
                    {
                        "subject_type": "drafter",
                        "subject_key": subject_key,
                        "title": f"Reviewer coaching hotspot - {top_drafter}",
                        "severity": "warning",
                        "count": recurring_periods,
                        "note": "Repeated rejection/rework patterns suggest targeted coaching or review-guidance intervention.",
                        "deep_link": "/#reports",
                        "metadata": {"actor": top_drafter, "metric": "reviewer_quality"},
                    }
                )
                notification_count += 1

    return {
        "triggered_at": _utcnow(),
        "triggered_by": triggered_by,
        "range_days": range_days,
        "recurring_periods": recurring_periods,
        "notification_count": notification_count,
        "items": items,
        "summary": [
            f"Captured a fresh decision-quality snapshot for {range_days} days before evaluating recurring hotspots.",
            f"Triggered {notification_count} quality recommendation notification(s).",
        ],
    }


async def _recent_notification_rows(limit: int = 20) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                id, notification_type, channel, severity, status, subject, target,
                team_key, region_key, case_id, metadata, created_at, delivered_at
            FROM notification_events
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [{**dict(row), "metadata": _normalize_json_dict(row.get("metadata"))} for row in rows]


async def _playbook_automation_counts(hours: int = 72) -> dict[str, Any]:
    pool = get_pool()
    since = _utcnow() - timedelta(hours=hours)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT notification_type, COUNT(*)::int AS item_count
            FROM notification_events
            WHERE notification_type IN ('playbook_stuck_case', 'playbook_evidence_gap_escalation')
              AND created_at >= $1
            GROUP BY notification_type
            """,
            since,
        )
    counts = {str(row["notification_type"]): int(row["item_count"]) for row in rows}
    return {
        "stuck_case_count": counts.get("playbook_stuck_case", 0),
        "evidence_gap_case_count": counts.get("playbook_evidence_gap_escalation", 0),
    }


async def _decision_quality_automation_counts(hours: int = 72) -> dict[str, Any]:
    pool = get_pool()
    since = _utcnow() - timedelta(hours=hours)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT notification_type, COUNT(*)::int AS item_count
            FROM notification_events
            WHERE notification_type IN (
                'decision_quality_noisy_alert_hotspot',
                'decision_quality_weak_sar_draft',
                'decision_quality_missing_evidence'
            )
              AND created_at >= $1
            GROUP BY notification_type
            """,
            since,
        )
    counts = {str(row["notification_type"]): int(row["item_count"]) for row in rows}
    return {
        "noisy_alert_hotspot_count": counts.get("decision_quality_noisy_alert_hotspot", 0),
        "weak_sar_case_count": counts.get("decision_quality_weak_sar_draft", 0),
        "missing_evidence_case_count": counts.get("decision_quality_missing_evidence", 0),
    }


async def _decision_quality_recommendation_counts(hours: int = 72) -> dict[str, Any]:
    pool = get_pool()
    since = _utcnow() - timedelta(hours=hours)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT notification_type, COUNT(*)::int AS item_count
            FROM notification_events
            WHERE notification_type IN (
                'decision_quality_recurring_typology',
                'decision_quality_drafter_coaching'
            )
              AND created_at >= $1
            GROUP BY notification_type
            """,
            since,
        )
    counts = {str(row["notification_type"]): int(row["item_count"] or 0) for row in rows}
    return {
        "recurring_typology_count": counts.get("decision_quality_recurring_typology", 0),
        "drafter_coaching_count": counts.get("decision_quality_drafter_coaching", 0),
    }


async def _decision_quality_notification_recent(
    conn: Any,
    *,
    notification_type: str,
    subject_key: str,
    cooldown_hours: float,
) -> bool:
    row = await conn.fetchrow(
        """
        SELECT created_at
        FROM notification_events
        WHERE notification_type = $1
          AND metadata->>'subject_key' = $2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        notification_type,
        subject_key,
    )
    if not row:
        return False
    created_at = _safe_datetime(row.get("created_at"))
    if not created_at:
        return False
    return (_hours_between(created_at, _utcnow()) or 0) < float(cooldown_hours)


def _default_playbook_automation_settings() -> dict[str, Any]:
    return {
        "stuck_hours": float(settings.PLAYBOOK_STUCK_CHECKLIST_HOURS),
        "evidence_gap_warning_hours": float(settings.PLAYBOOK_EVIDENCE_GAP_WARNING_HOURS),
        "cooldown_hours": float(settings.PLAYBOOK_AUTOMATION_COOLDOWN_HOURS),
        "max_cases": int(settings.PLAYBOOK_AUTOMATION_MAX_CASES),
    }


async def get_playbook_automation_settings() -> dict[str, Any]:
    defaults = _default_playbook_automation_settings()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT config, updated_by, updated_at
            FROM app_runtime_settings
            WHERE setting_key = 'playbook_automation'
            """
        )
    config = _normalize_json_dict(row.get("config")) if row else {}
    payload = {
        **defaults,
        **{key: config.get(key, defaults[key]) for key in defaults},
        "updated_by": row.get("updated_by") if row else None,
        "updated_at": row.get("updated_at") if row else None,
    }
    payload["summary"] = [
        f"Stuck checklist automation triggers after {payload['stuck_hours']} hours.",
        f"Evidence-gap escalation triggers within {payload['evidence_gap_warning_hours']} hours of SLA breach.",
        f"Cooldown is {payload['cooldown_hours']} hours with a batch size of {payload['max_cases']} cases.",
    ]
    return payload


async def update_playbook_automation_settings(*, actor: str, updates: dict[str, Any]) -> dict[str, Any]:
    current = await get_playbook_automation_settings()
    merged = {
        "stuck_hours": float(updates.get("stuck_hours", current["stuck_hours"])),
        "evidence_gap_warning_hours": float(updates.get("evidence_gap_warning_hours", current["evidence_gap_warning_hours"])),
        "cooldown_hours": float(updates.get("cooldown_hours", current["cooldown_hours"])),
        "max_cases": int(updates.get("max_cases", current["max_cases"])),
    }
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO app_runtime_settings (setting_key, config, updated_by)
            VALUES ('playbook_automation', $1::jsonb, $2)
            ON CONFLICT (setting_key) DO UPDATE
            SET config = EXCLUDED.config,
                updated_by = EXCLUDED.updated_by,
                updated_at = NOW()
            """,
            json.dumps(merged),
            actor,
        )
    return await get_playbook_automation_settings()


async def _create_case_event(
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


async def get_n8n_dashboard(limit: int = 20) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        workflows = await conn.fetch(
            """
            SELECT
                w.id,
                w.name,
                w.active,
                w."triggerCount" AS trigger_count,
                w."updatedAt" AS updated_at,
                ex.id AS last_execution_id,
                ex.status AS last_execution_status,
                ex.finished AS last_execution_finished,
                ex."startedAt" AS last_started_at,
                ex."stoppedAt" AS last_stopped_at,
                stats.total_count,
                stats.success_count,
                stats.error_count,
                stats.running_count
            FROM workflow_entity w
            LEFT JOIN LATERAL (
                SELECT e.id, e.status, e.finished, e."startedAt", e."stoppedAt"
                FROM execution_entity e
                WHERE e."workflowId" = w.id
                  AND e."deletedAt" IS NULL
                ORDER BY e.id DESC
                LIMIT 1
            ) ex ON TRUE
            LEFT JOIN LATERAL (
                SELECT
                    COUNT(*)::int AS total_count,
                    COUNT(*) FILTER (WHERE e.status = 'success')::int AS success_count,
                    COUNT(*) FILTER (WHERE e.status = 'error')::int AS error_count,
                    COUNT(*) FILTER (WHERE e.finished = FALSE)::int AS running_count
                FROM execution_entity e
                WHERE e."workflowId" = w.id
                  AND e."deletedAt" IS NULL
            ) stats ON TRUE
            WHERE w.name LIKE 'goAML %'
            ORDER BY w.active DESC, w.name ASC
            LIMIT $1
            """,
            limit,
        )
        recent_executions = await conn.fetch(
            """
            SELECT
                e.id,
                w.name,
                e.status,
                e.finished,
                e.mode,
                e."startedAt" AS started_at,
                e."stoppedAt" AS stopped_at
            FROM execution_entity e
            JOIN workflow_entity w ON w.id = e."workflowId"
            WHERE w.name LIKE 'goAML %'
              AND e."deletedAt" IS NULL
            ORDER BY e.id DESC
            LIMIT $1
            """,
            limit,
        )

    workflow_items = [dict(row) for row in workflows]
    execution_items = [dict(row) for row in recent_executions]
    active_count = sum(1 for row in workflow_items if row.get("active"))
    running_count = sum(int(row.get("running_count") or 0) for row in workflow_items)
    return {
        "generated_at": _utcnow(),
        "public_url": settings.N8N_PUBLIC_URL,
        "counts": {
            "workflow_count": len(workflow_items),
            "active_workflow_count": active_count,
            "running_execution_count": running_count,
            "execution_history_count": len(execution_items),
        },
        "workflows": workflow_items,
        "recent_executions": execution_items,
        "summary": [
            f"{active_count} goAML automation workflows are active in n8n.",
            f"{running_count} executions are currently running.",
        ],
    }


async def _camunda_request(path: str, *, params: dict[str, Any] | None = None, method: str = "GET", json_body: dict[str, Any] | None = None) -> Any:
    url = f"{settings.CAMUNDA_BASE_URL.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.request(method, url, params=params, json=json_body)
        response.raise_for_status()
        if response.text:
            return response.json()
        return {}


async def _upsert_orchestration_run(
    *,
    engine: str,
    workflow_key: str,
    workflow_label: str,
    process_instance_id: str,
    business_key: str,
    case_id: UUID | None,
    subject_type: str | None,
    subject_id: UUID | None,
    routing: dict[str, Any] | None,
    status: str,
    current_task_name: str | None,
    summary: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    routing_data = routing or {}
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO orchestration_runs (
                engine, workflow_key, workflow_label, process_instance_id, business_key,
                case_id, subject_type, subject_id, team_key, team_label, region_key, region_label,
                status, current_task_name, summary, metadata, started_at, updated_at
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9, $10, $11, $12,
                $13, $14, $15, $16::jsonb, NOW(), NOW()
            )
            ON CONFLICT (process_instance_id) DO UPDATE
            SET
                workflow_label = EXCLUDED.workflow_label,
                business_key = EXCLUDED.business_key,
                case_id = EXCLUDED.case_id,
                subject_type = EXCLUDED.subject_type,
                subject_id = EXCLUDED.subject_id,
                team_key = EXCLUDED.team_key,
                team_label = EXCLUDED.team_label,
                region_key = EXCLUDED.region_key,
                region_label = EXCLUDED.region_label,
                status = EXCLUDED.status,
                current_task_name = EXCLUDED.current_task_name,
                summary = EXCLUDED.summary,
                metadata = EXCLUDED.metadata,
                updated_at = NOW(),
                finished_at = CASE WHEN EXCLUDED.status IN ('completed', 'ended', 'rejected', 'filed') THEN NOW() ELSE orchestration_runs.finished_at END
            """,
            engine,
            workflow_key,
            workflow_label,
            process_instance_id,
            business_key,
            case_id,
            subject_type,
            subject_id,
            routing_data.get("team_key"),
            routing_data.get("team_label"),
            routing_data.get("region_key"),
            routing_data.get("region_label"),
            status,
            current_task_name,
            summary,
            json.dumps(metadata or {}),
        )


async def _find_active_run(case_id: UUID, workflow_key: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM orchestration_runs
            WHERE case_id = $1
              AND workflow_key = $2
              AND status NOT IN ('completed', 'ended', 'rejected', 'filed')
            ORDER BY started_at DESC
            LIMIT 1
            """,
            case_id,
            workflow_key,
        )
    return dict(row) if row else None


async def _sync_camunda_run(run_row: dict[str, Any]) -> dict[str, Any]:
    process_instance_id = str(run_row.get("process_instance_id") or "")
    tasks = await _camunda_request("/task", params={"processInstanceId": process_instance_id, "maxResults": 10}) if process_instance_id else []
    active = False
    if process_instance_id:
        try:
            await _camunda_request(f"/process-instance/{process_instance_id}")
            active = True
        except httpx.HTTPStatusError:
            active = False
    current_task_name = tasks[0]["name"] if tasks else None
    next_status = "active" if active and tasks else ("waiting" if active else "completed")
    if isinstance(run_row.get("metadata"), str):
        metadata = _normalize_json_dict(run_row.get("metadata"))
    else:
        metadata = dict(run_row.get("metadata") or {})
    metadata["task_count"] = len(tasks)
    metadata["last_synced_at"] = _utcnow().isoformat()
    await _upsert_orchestration_run(
        engine=str(run_row["engine"]),
        workflow_key=str(run_row["workflow_key"]),
        workflow_label=str(run_row.get("workflow_label") or run_row["workflow_key"]),
        process_instance_id=process_instance_id,
        business_key=str(run_row.get("business_key") or ""),
        case_id=run_row.get("case_id"),
        subject_type=run_row.get("subject_type"),
        subject_id=run_row.get("subject_id"),
        routing={
            "team_key": run_row.get("team_key"),
            "team_label": run_row.get("team_label"),
            "region_key": run_row.get("region_key"),
            "region_label": run_row.get("region_label"),
        },
        status=next_status,
        current_task_name=current_task_name,
        summary=(f"Camunda workflow active with task {current_task_name}." if current_task_name else "Camunda workflow completed."),
        metadata=metadata,
    )
    return {
        **run_row,
        "status": next_status,
        "current_task_name": current_task_name,
        "task_count": len(tasks),
    }


async def ensure_camunda_case_process(
    *,
    case_id: UUID,
    workflow_key: str,
    workflow_label: str,
    workflow_type: str,
    actor: str | None = None,
    subject_type: str | None = None,
    subject_id: UUID | None = None,
    extra_variables: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        existing = await _find_active_run(case_id, workflow_key)
        if existing:
            return await _sync_camunda_run(existing)

        pool = get_pool()
        async with pool.acquire() as conn:
            case_row = await conn.fetchrow("SELECT * FROM cases WHERE id = $1", case_id)
            if not case_row:
                return None
            case_data = dict(case_row)
            routing = await resolve_case_routing(
                conn,
                workflow_type=workflow_type,
                primary_entity_id=case_data.get("primary_entity_id"),
                primary_account_id=case_data.get("primary_account_id"),
                existing_metadata=_normalize_json_dict(case_data.get("metadata")),
                preferred_assignee=case_data.get("assigned_to"),
            )

        business_key = case_data["case_ref"]
        variables = {
            "caseId": {"value": str(case_id), "type": "String"},
            "caseRef": {"value": case_data["case_ref"], "type": "String"},
            "caseTitle": {"value": case_data["title"], "type": "String"},
            "priority": {"value": str(case_data["priority"]), "type": "String"},
            "assignedTo": {"value": routing.get("assigned_to") or case_data.get("assigned_to") or "", "type": "String"},
            "team": {"value": routing.get("team_key") or "", "type": "String"},
            "teamLabel": {"value": routing.get("team_label") or "", "type": "String"},
            "region": {"value": routing.get("region_key") or "", "type": "String"},
            "regionLabel": {"value": routing.get("region_label") or "", "type": "String"},
            "triggeredBy": {"value": actor or "system", "type": "String"},
        }
        for key, value in (extra_variables or {}).items():
            variables[key] = {"value": value, "type": "String"}

        response = await _camunda_request(
            f"/process-definition/key/{workflow_key}/start",
            method="POST",
            json_body={"businessKey": business_key, "variables": variables},
        )
        process_instance_id = str(response.get("id"))
        await _upsert_orchestration_run(
            engine="camunda",
            workflow_key=workflow_key,
            workflow_label=workflow_label,
            process_instance_id=process_instance_id,
            business_key=business_key,
            case_id=case_id,
            subject_type=subject_type,
            subject_id=subject_id,
            routing=routing,
            status="active",
            current_task_name=None,
            summary=f"{workflow_label} started for {business_key}.",
            metadata={"started_by": actor, "workflow_type": workflow_type},
        )

        pool = get_pool()
        async with pool.acquire() as conn:
            await _create_case_event(
                conn,
                case_id=case_id,
                event_type="camunda_process_started",
                actor=actor,
                detail=f"{workflow_label} started in Camunda",
                metadata={"workflow_key": workflow_key, "process_instance_id": process_instance_id},
            )
        return await _find_active_run(case_id, workflow_key)
    except httpx.HTTPError:
        return None


async def advance_sar_camunda_flow(case_id: UUID, *, action: str, actor: str | None, note: str | None) -> None:
    try:
        workflow_key = "goamlSarFormalReview"
        if action == "submit_review":
            await ensure_camunda_case_process(
                case_id=case_id,
                workflow_key=workflow_key,
                workflow_label="goAML SAR Formal Review",
                workflow_type="sar_review",
                actor=actor,
            )
            return

        run_row = await _find_active_run(case_id, workflow_key)
        if not run_row:
            return

        tasks = await _camunda_request("/task", params={"processInstanceId": run_row["process_instance_id"], "maxResults": 10})
        if not tasks:
            await _sync_camunda_run(run_row)
            return
        task = tasks[0]

        if action == "approve":
            variables = {
                "reviewDecision": {"value": "approve", "type": "String"},
                "reviewActor": {"value": actor or "system", "type": "String"},
                "reviewNote": {"value": note or "", "type": "String"},
            }
        elif action == "reject":
            variables = {
                "reviewDecision": {"value": "reject", "type": "String"},
                "reviewActor": {"value": actor or "system", "type": "String"},
                "reviewNote": {"value": note or "", "type": "String"},
            }
        elif action == "file":
            variables = {
                "filingDecision": {"value": "filed", "type": "String"},
                "filingActor": {"value": actor or "system", "type": "String"},
                "filingNote": {"value": note or "", "type": "String"},
            }
        else:
            return

        await _camunda_request(f"/task/{task['id']}/complete", method="POST", json_body={"variables": variables})
        await _sync_camunda_run(run_row)
    except httpx.HTTPError:
        return


async def start_watchlist_camunda_flow(
    *,
    case_id: UUID,
    entity_id: UUID | None,
    entity_name: str | None,
    actor: str | None,
) -> None:
    try:
        await ensure_camunda_case_process(
            case_id=case_id,
            workflow_key="goamlWatchlistEscalation",
            workflow_label="goAML Watchlist Escalation",
            workflow_type="watchlist",
            actor=actor,
            subject_type="entity",
            subject_id=entity_id,
            extra_variables={
                "entityId": str(entity_id) if entity_id else "",
                "entityName": entity_name or "",
            },
        )
    except httpx.HTTPError:
        return


async def _deliver_slack(subject: str, message: str, *, team_key: str | None, metadata: dict[str, Any]) -> tuple[str, str | None]:
    team_map = _parse_json_map(settings.TEAM_SLACK_WEBHOOKS_JSON)
    webhook = team_map.get(team_key or "") or settings.SLACK_WEBHOOK_URL
    if not webhook:
        return "not_configured", None
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(str(webhook), json={"text": f"{subject}\n{message}"})
        response.raise_for_status()
    return "sent", str(webhook)


async def _deliver_email(subject: str, message: str, *, team_key: str | None, metadata: dict[str, Any]) -> tuple[str, str | None]:
    recipient_map = _parse_json_map(settings.TEAM_EMAIL_RECIPIENTS_JSON)
    recipients: list[str] = []
    team_recipients = recipient_map.get(team_key or "")
    if isinstance(team_recipients, list):
        recipients.extend(str(item).strip() for item in team_recipients if str(item).strip())
    if not recipients and settings.SLA_NOTIFICATION_EMAIL_TO:
        recipients.extend(item.strip() for item in settings.SLA_NOTIFICATION_EMAIL_TO.split(",") if item.strip())
    if not (settings.SMTP_HOST and recipients and settings.SMTP_FROM):
        return "not_configured", ", ".join(recipients) if recipients else None

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = ", ".join(recipients)
    msg.set_content(message)

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
        smtp.send_message(msg)
    return "sent", ", ".join(recipients)


async def dispatch_sla_notifications(
    *,
    triggered_by: str | None = None,
    channels: list[str] | None = None,
    breached_only: bool = True,
    include_due_soon: bool | None = None,
) -> dict[str, Any]:
    from services.cases import list_sar_queue

    include_due = settings.SLA_NOTIFICATION_INCLUDE_DUE_SOON if include_due_soon is None else include_due_soon
    queue_data = await list_sar_queue(queue="all", limit=200, offset=0)
    pool = get_pool()

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    async with pool.acquire() as conn:
        for item in queue_data.get("items", []):
            sla_state = str(item.get("sla_status") or "")
            if breached_only and sla_state != "breached":
                if not (include_due and sla_state == "due_soon"):
                    continue
            routing = await resolve_case_routing(
                conn,
                workflow_type="sar_review",
                primary_entity_id=item.get("primary_entity_id"),
                primary_account_id=item.get("primary_account_id"),
                preferred_assignee=item.get("queue_owner") or item.get("assigned_to"),
            )
            key = (routing.get("team_key") or "global", routing.get("region_key") or "global")
            if key not in grouped:
                grouped[key] = {
                    "team_key": routing.get("team_key"),
                    "team_label": routing.get("team_label"),
                    "region_key": routing.get("region_key"),
                    "region_label": routing.get("region_label"),
                    "items": [],
                    "owner_names": set(),
                }
            grouped[key]["items"].append(item)
            if item.get("queue_owner"):
                grouped[key]["owner_names"].add(item["queue_owner"])

    selected_channels = [channel for channel in (channels or ["slack", "email"]) if channel in {"slack", "email"}]
    notification_groups: list[dict[str, Any]] = []

    for group in grouped.values():
        items = group["items"][: settings.SLA_NOTIFICATION_MAX_CASES]
        case_refs = [str(item.get("case_ref")) for item in items if item.get("case_ref")]
        subject = f"goAML SAR SLA breach alert - {group['team_label'] or 'AML Ops'}"
        message = (
            f"Region: {group['region_label'] or 'Global'}\n"
            f"Cases outside SLA: {len(group['items'])}\n"
            f"Owners impacted: {', '.join(sorted(group['owner_names'])) or 'unassigned'}\n"
            f"Cases: {', '.join(case_refs) if case_refs else 'none'}"
        )
        channel_results: list[dict[str, Any]] = []
        for channel in selected_channels:
            if channel == "slack":
                status, target = await _deliver_slack(subject, message, team_key=group["team_key"], metadata={"case_refs": case_refs})
            else:
                status, target = await _deliver_email(subject, message, team_key=group["team_key"], metadata={"case_refs": case_refs})
            await _record_notification_event(
                notification_type="sar_sla_breach",
                channel=channel,
                severity="high",
                status=status,
                subject=subject,
                target=target,
                team_key=group["team_key"],
                region_key=group["region_key"],
                metadata={
                    "triggered_by": triggered_by or settings.SLA_NOTIFICATION_WORKFLOW_ACTOR,
                    "case_refs": case_refs,
                    "queue": "sar_sla",
                    "case_count": len(group["items"]),
                    "owners": sorted(group["owner_names"]),
                },
            )
            channel_results.append({"channel": channel, "status": status, "target": target})

        notification_groups.append(
            {
                "team_key": group["team_key"],
                "team_label": group["team_label"],
                "region_key": group["region_key"],
                "region_label": group["region_label"],
                "case_count": len(group["items"]),
                "case_refs": case_refs,
                "owners": sorted(group["owner_names"]),
                "channel_results": channel_results,
            }
        )

    return {
        "generated_at": _utcnow(),
        "breached_case_count": sum(len(group["items"]) for group in grouped.values()),
        "group_count": len(notification_groups),
        "channels": _channel_status(),
        "groups": notification_groups,
        "summary": [
            f"Prepared {len(notification_groups)} SLA breach notification groups.",
            f"Observed {sum(len(group['items']) for group in grouped.values())} breached or due-soon SAR queue items.",
        ],
    }


def _challenger_monitoring_severity(summary: dict[str, Any] | None) -> str:
    details = summary or {}
    disagreement_rate = _safe_float(details.get("disagreement_rate"))
    mean_abs_delta = _safe_float(details.get("mean_abs_delta"))
    if (
        disagreement_rate >= settings.SCORER_CHALLENGER_DISAGREEMENT_CRITICAL
        or mean_abs_delta >= settings.SCORER_CHALLENGER_MEAN_ABS_DELTA_CRITICAL
    ):
        return "critical"
    if (
        disagreement_rate >= settings.SCORER_CHALLENGER_DISAGREEMENT_WARNING
        or mean_abs_delta >= settings.SCORER_CHALLENGER_MEAN_ABS_DELTA_WARNING
    ):
        return "warning"
    return "stable"


async def dispatch_model_monitoring_notifications(
    *,
    triggered_by: str | None = None,
    channels: list[str] | None = None,
    include_stable: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    from services.model_monitoring import get_scorer_monitoring_summary

    monitoring = await get_scorer_monitoring_summary(limit=10)
    selected_channels = [channel for channel in (channels or ["slack", "email"]) if channel in {"slack", "email"}]
    effective_actor = triggered_by or settings.SCORER_MONITORING_WORKFLOW_ACTOR
    alerts: list[dict[str, Any]] = []

    latest_drift = monitoring.get("latest_drift") or {}
    drift_summary = latest_drift.get("summary") or {}
    drift_severity = str(drift_summary.get("severity") or "stable").lower()
    if latest_drift and (force or include_stable or drift_severity in {"warning", "critical"}):
        alerts.append(
            {
                "kind": "scorer_drift_monitoring",
                "severity": drift_severity,
                "subject": f"goAML scorer drift alert - {drift_severity.upper()}",
                "team_key": "model_ops",
                "region_key": settings.OPS_ALERT_DEFAULT_REGION,
                "metadata": {
                    "snapshot_id": latest_drift.get("id"),
                    "model_version": drift_summary.get("model_version"),
                    "baseline_version": drift_summary.get("baseline_version"),
                    "amount_psi": drift_summary.get("amount_psi"),
                    "score_psi": drift_summary.get("score_psi"),
                    "max_rate_delta": drift_summary.get("max_rate_delta"),
                    "deeplink": "/#model-ops",
                    "triggered_by": effective_actor,
                },
                "message": (
                    f"Scorer version: {drift_summary.get('model_version') or 'unknown'}\n"
                    f"Baseline version: {drift_summary.get('baseline_version') or 'unset'}\n"
                    f"Severity: {drift_severity}\n"
                    f"Score PSI: {drift_summary.get('score_psi')}\n"
                    f"Amount PSI: {drift_summary.get('amount_psi')}\n"
                    f"Max rate delta: {drift_summary.get('max_rate_delta')}\n"
                    f"Sample size: {drift_summary.get('sample_size')}\n"
                    f"Window: {drift_summary.get('window_start')} -> {drift_summary.get('window_end')}"
                ),
            }
        )

    latest_challenger = monitoring.get("latest_champion_challenger") or {}
    challenger_summary = latest_challenger.get("summary") or {}
    challenger_severity = _challenger_monitoring_severity(challenger_summary) if latest_challenger else "stable"
    if latest_challenger and (force or include_stable or challenger_severity in {"warning", "critical"}):
        alerts.append(
            {
                "kind": "scorer_champion_challenger",
                "severity": challenger_severity,
                "subject": f"goAML scorer challenger alert - {challenger_severity.upper()}",
                "team_key": "model_ops",
                "region_key": settings.OPS_ALERT_DEFAULT_REGION,
                "metadata": {
                    "snapshot_id": latest_challenger.get("id"),
                    "champion_version": challenger_summary.get("champion_version"),
                    "challenger_version": challenger_summary.get("challenger_version"),
                    "disagreement_rate": challenger_summary.get("disagreement_rate"),
                    "mean_abs_delta": challenger_summary.get("mean_abs_delta"),
                    "max_abs_delta": challenger_summary.get("max_abs_delta"),
                    "deeplink": "/#model-ops",
                    "triggered_by": effective_actor,
                },
                "message": (
                    f"Champion version: {challenger_summary.get('champion_version') or 'unknown'}\n"
                    f"Challenger version: {challenger_summary.get('challenger_version') or 'unknown'}\n"
                    f"Severity: {challenger_severity}\n"
                    f"Disagreement rate: {challenger_summary.get('disagreement_rate')}\n"
                    f"Mean absolute delta: {challenger_summary.get('mean_abs_delta')}\n"
                    f"Max absolute delta: {challenger_summary.get('max_abs_delta')}\n"
                    f"Sample size: {challenger_summary.get('sample_size')}\n"
                    f"Window: {challenger_summary.get('window_start')} -> {challenger_summary.get('window_end')}"
                ),
            }
        )

    notification_groups: list[dict[str, Any]] = []
    for alert in alerts:
        channel_results: list[dict[str, Any]] = []
        for channel in selected_channels:
            if channel == "slack":
                status, target = await _deliver_slack(
                    alert["subject"],
                    alert["message"],
                    team_key=alert["team_key"],
                    metadata=alert["metadata"],
                )
            else:
                status, target = await _deliver_email(
                    alert["subject"],
                    alert["message"],
                    team_key=alert["team_key"],
                    metadata=alert["metadata"],
                )
            await _record_notification_event(
                notification_type=alert["kind"],
                channel=channel,
                severity=alert["severity"],
                status=status,
                subject=alert["subject"],
                target=target,
                team_key=alert["team_key"],
                region_key=alert["region_key"],
                metadata=alert["metadata"],
            )
            channel_results.append({"channel": channel, "status": status, "target": target})
        notification_groups.append(
            {
                "kind": alert["kind"],
                "severity": alert["severity"],
                "subject": alert["subject"],
                "channel_results": channel_results,
                "metadata": alert["metadata"],
            }
        )

    return {
        "generated_at": _utcnow(),
        "alert_count": len(alerts),
        "group_count": len(notification_groups),
        "channels": _channel_status(),
        "alerts": notification_groups,
        "monitoring_summary": monitoring.get("summary", {}),
        "summary": [
            f"Prepared {len(notification_groups)} model monitoring notification groups.",
            (
                "No drift or challenger condition exceeded the current alert threshold."
                if not notification_groups
                else f"Dispatched {len(notification_groups)} model monitoring alert groups."
            ),
        ],
    }


async def get_camunda_dashboard(limit: int = 20) -> dict[str, Any]:
    try:
        definitions = await _camunda_request("/process-definition", params={"latestVersion": "true", "maxResults": limit})
        tasks = await _camunda_request("/task", params={"maxResults": limit, "sortBy": "created", "sortOrder": "desc"})
        instances = await _camunda_request("/process-instance", params={"maxResults": limit})
    except httpx.HTTPError as exc:
        return {
            "generated_at": _utcnow(),
            "public_url": settings.CAMUNDA_PUBLIC_URL,
            "counts": {
                "definition_count": 0,
                "active_task_count": 0,
                "active_instance_count": 0,
                "tracked_process_count": 0,
            },
            "definitions": [],
            "tasks": [],
            "tracked_processes": [],
            "summary": [f"Camunda dashboard is temporarily unavailable: {exc!s}"],
        }

    pool = get_pool()
    async with pool.acquire() as conn:
        run_rows = await conn.fetch(
            """
            SELECT *
            FROM orchestration_runs
            WHERE engine = 'camunda'
            ORDER BY updated_at DESC
            LIMIT $1
            """,
            limit,
        )
    tracked_runs = [await _sync_camunda_run(dict(row)) for row in run_rows]
    process_map = {str(row.get("process_instance_id")): row for row in tracked_runs}

    task_items = []
    for task in tasks:
        mapped = process_map.get(str(task.get("processInstanceId")))
        task_items.append(
            {
                "id": task.get("id"),
                "name": task.get("name"),
                "assignee": task.get("assignee"),
                "created": task.get("created"),
                "due": task.get("due"),
                "priority": task.get("priority"),
                "process_instance_id": task.get("processInstanceId"),
                "process_definition_id": task.get("processDefinitionId"),
                "case_id": mapped.get("case_id") if mapped else None,
                "business_key": mapped.get("business_key") if mapped else None,
                "team_label": mapped.get("team_label") if mapped else None,
                "region_label": mapped.get("region_label") if mapped else None,
            }
        )

    return {
        "generated_at": _utcnow(),
        "public_url": settings.CAMUNDA_PUBLIC_URL,
        "counts": {
            "definition_count": len(definitions),
            "active_task_count": len(tasks),
            "active_instance_count": len(instances),
            "tracked_process_count": len(tracked_runs),
        },
        "definitions": definitions,
        "tasks": task_items,
        "tracked_processes": tracked_runs,
        "summary": [
            f"{len(tasks)} active Camunda tasks are currently visible.",
            f"{len(tracked_runs)} case-linked processes are tracked in goAML.",
        ],
    }


async def get_workflow_overview() -> dict[str, Any]:
    from services.cases import list_sar_queue
    from services.entities import list_watchlist_entities
    from services.model_monitoring import get_scorer_monitoring_summary

    sar_queue = await list_sar_queue(queue="all", limit=100, offset=0)
    watchlist = await list_watchlist_entities(status="active", limit=30, offset=0)
    n8n = await get_n8n_dashboard(limit=20)
    camunda = await get_camunda_dashboard(limit=20)
    model_monitoring = await get_scorer_monitoring_summary(limit=6)
    playbook_automation = await _playbook_automation_counts(hours=72)
    decision_quality_automation = await _decision_quality_automation_counts(hours=72)
    decision_quality_recommendations = await _decision_quality_recommendation_counts(hours=72)

    directory = _directory_by_name()
    owner_summary: dict[str, dict[str, Any]] = {}
    for item in sar_queue.get("items", []):
        owner = item.get("queue_owner") or item.get("assigned_to") or "unassigned"
        profile = directory.get(owner, {})
        slot = owner_summary.setdefault(
            owner,
            {
                "owner": owner,
                "team_label": profile.get("team_label", "Global AML Operations"),
                "team_key": profile.get("team_key", settings.OPS_ALERT_DEFAULT_TEAM),
                "item_count": 0,
                "breached_count": 0,
                "due_soon_count": 0,
            },
        )
        slot["item_count"] += 1
        if item.get("sla_status") == "breached":
            slot["breached_count"] += 1
        elif item.get("sla_status") == "due_soon":
            slot["due_soon_count"] += 1

    recent_notifications = await _recent_notification_rows(limit=15)
    latest_drift_severity = str(model_monitoring.get("summary", {}).get("latest_drift_severity") or "none")
    latest_challenger = model_monitoring.get("latest_champion_challenger") or {}
    latest_challenger_severity = _challenger_monitoring_severity(latest_challenger.get("summary")) if latest_challenger else "none"
    model_alert_count = sum(1 for item in (latest_drift_severity, latest_challenger_severity) if item in {"warning", "critical"})
    return {
        "generated_at": _utcnow(),
        "counts": {
            "sar_breached": sar_queue.get("analytics", {}).get("overall_breached_count", 0),
            "sar_due_soon": sar_queue.get("analytics", {}).get("overall_due_soon_count", 0),
            "watchlist_active": watchlist.get("counts", {}).get("active", 0),
            "watchlist_open_cases": watchlist.get("counts", {}).get("with_open_case", 0),
            "n8n_active_workflows": n8n.get("counts", {}).get("active_workflow_count", 0),
            "camunda_active_tasks": camunda.get("counts", {}).get("active_task_count", 0),
            "model_alerts": model_alert_count,
            "model_drift_severity": latest_drift_severity,
            "model_challenger_severity": latest_challenger_severity,
            "playbook_stuck_cases": playbook_automation.get("stuck_case_count", 0),
            "playbook_evidence_gap_cases": playbook_automation.get("evidence_gap_case_count", 0),
            "decision_quality_noisy_hotspots": decision_quality_automation.get("noisy_alert_hotspot_count", 0),
            "decision_quality_weak_sar_cases": decision_quality_automation.get("weak_sar_case_count", 0),
            "decision_quality_missing_evidence_cases": decision_quality_automation.get("missing_evidence_case_count", 0),
            "decision_quality_recurring_typologies": decision_quality_recommendations.get("recurring_typology_count", 0),
            "decision_quality_drafter_hotspots": decision_quality_recommendations.get("drafter_coaching_count", 0),
        },
        "channel_status": _channel_status(),
        "owner_workload": sorted(owner_summary.values(), key=lambda item: (-item["breached_count"], -item["item_count"], item["owner"])),
        "recent_notifications": recent_notifications,
        "n8n": n8n,
        "camunda": camunda,
        "model_monitoring": model_monitoring,
        "playbook_automation": playbook_automation,
        "decision_quality_automation": decision_quality_automation,
        "decision_quality_recommendations": decision_quality_recommendations,
        "summary": [
            f"{sar_queue.get('analytics', {}).get('overall_breached_count', 0)} SAR items are currently outside SLA.",
            f"{watchlist.get('counts', {}).get('with_open_case', 0)} active watchlist entities already have linked review cases.",
            f"{camunda.get('counts', {}).get('tracked_process_count', 0)} Camunda processes are currently tracked against goAML cases.",
            f"{playbook_automation.get('stuck_case_count', 0)} cases were flagged for stuck playbook checklist steps in the last 72 hours.",
            f"{playbook_automation.get('evidence_gap_case_count', 0)} cases were escalated for missing evidence in the last 72 hours.",
            f"{decision_quality_automation.get('noisy_alert_hotspot_count', 0)} noisy-alert hotspots were flagged from analyst feedback in the last 72 hours.",
            f"{decision_quality_automation.get('weak_sar_case_count', 0)} cases triggered weak-SAR interventions and {decision_quality_automation.get('missing_evidence_case_count', 0)} triggered missing-evidence interventions in the last 72 hours.",
            f"{decision_quality_recommendations.get('recurring_typology_count', 0)} recurring typology hotspot notification(s) and {decision_quality_recommendations.get('drafter_coaching_count', 0)} drafter coaching notification(s) were generated in the last 72 hours.",
            (
                f"Scorer drift is {latest_drift_severity}"
                + (
                    f" against baseline version {model_monitoring.get('summary', {}).get('baseline_version')}"
                    if model_monitoring.get('summary', {}).get('baseline_version')
                    else "."
                )
            ),
            (
                f"Latest challenger state is {latest_challenger_severity}"
                + (
                    f" for version {latest_challenger.get('summary', {}).get('challenger_version')}"
                    if latest_challenger.get("summary", {}).get("challenger_version")
                    else "."
                )
            ),
        ],
    }
