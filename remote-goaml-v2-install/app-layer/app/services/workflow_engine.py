"""
Operational workflow services for routing, notifications, n8n, and Camunda.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from email.message import EmailMessage
import json
import smtplib
from typing import Any
from uuid import UUID

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


async def _record_notification_event(
    *,
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
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
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

    sar_queue = await list_sar_queue(queue="all", limit=100, offset=0)
    watchlist = await list_watchlist_entities(status="active", limit=30, offset=0)
    n8n = await get_n8n_dashboard(limit=20)
    camunda = await get_camunda_dashboard(limit=20)

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
    return {
        "generated_at": _utcnow(),
        "counts": {
            "sar_breached": sar_queue.get("analytics", {}).get("overall_breached_count", 0),
            "sar_due_soon": sar_queue.get("analytics", {}).get("overall_due_soon_count", 0),
            "watchlist_active": watchlist.get("counts", {}).get("active", 0),
            "watchlist_open_cases": watchlist.get("counts", {}).get("with_open_case", 0),
            "n8n_active_workflows": n8n.get("counts", {}).get("active_workflow_count", 0),
            "camunda_active_tasks": camunda.get("counts", {}).get("active_task_count", 0),
        },
        "channel_status": _channel_status(),
        "owner_workload": sorted(owner_summary.values(), key=lambda item: (-item["breached_count"], -item["item_count"], item["owner"])),
        "recent_notifications": recent_notifications,
        "n8n": n8n,
        "camunda": camunda,
        "summary": [
            f"{sar_queue.get('analytics', {}).get('overall_breached_count', 0)} SAR items are currently outside SLA.",
            f"{watchlist.get('counts', {}).get('with_open_case', 0)} active watchlist entities already have linked review cases.",
            f"{camunda.get('counts', {}).get('tracked_process_count', 0)} Camunda processes are currently tracked against goAML cases.",
        ],
    }
