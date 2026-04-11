"""
goAML-V2 alert query and update service.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID

from core.database import get_pool
from models.casework import AlertActionRequest, AlertInvestigateRequest, AlertStatusUpdate, CaseCreate
from services.cases import create_case, get_case_detail
from services.graph_sync import safe_resync_graph
from services.routing import resolve_case_routing, routing_metadata_payload


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


def _append_alert_note(
    metadata: dict[str, Any],
    *,
    action: str,
    actor: str | None,
    note: str | None,
    status: str | None,
    assigned_to: str | None,
) -> dict[str, Any]:
    analyst_notes = _normalize_json_list(metadata.get("analyst_notes"))
    analyst_notes.append(
        {
            "action": action,
            "actor": actor,
            "note": note,
            "status": status,
            "assigned_to": assigned_to,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    metadata["analyst_notes"] = analyst_notes[-50:]
    return metadata


def _normalize_alert_row(row: dict[str, Any]) -> dict[str, Any]:
    row["evidence"] = _normalize_json_dict(row.get("evidence"))
    row["metadata"] = _normalize_json_dict(row.get("metadata"))
    row["analyst_notes"] = _normalize_json_list(row["metadata"].get("analyst_notes"))
    return row


async def list_alerts(
    limit: int,
    offset: int,
    status: str | None,
    severity: str | None,
) -> list[dict[str, Any]]:
    pool = get_pool()
    conditions = ["1=1"]
    args: list[Any] = []
    idx = 1

    if status:
        conditions.append(f"status = ${idx}::alert_status")
        args.append(status)
        idx += 1

    if severity:
        conditions.append(f"severity = ${idx}::risk_level")
        args.append(severity)
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                id, alert_ref, alert_type, status, severity, title,
                transaction_id, account_id, entity_id, case_id, assigned_to, created_at
            FROM alerts
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}
            """,
            *args, limit, offset,
        )
    return [dict(r) for r in rows]


async def get_alert(alert_id: UUID) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id, alert_ref, alert_type, status, severity, title,
                description, evidence, transaction_id, account_id, case_id,
                entity_id, ml_explanation, metadata,
                assigned_to, reviewed_by, reviewed_at, closed_at,
                resolution_note, created_at, updated_at
            FROM alerts
            WHERE id = $1
            """,
            alert_id,
        )
    return _normalize_alert_row(dict(row)) if row else None


async def update_alert_status(alert_id: UUID, payload: AlertStatusUpdate) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE alerts
            SET
                status = $2::alert_status,
                reviewed_by = COALESCE($3, reviewed_by),
                reviewed_at = CASE
                    WHEN $2::alert_status IN ('reviewing', 'escalated', 'closed', 'false_positive')
                    THEN NOW()
                    ELSE reviewed_at
                END,
                closed_at = CASE
                    WHEN $2::alert_status IN ('closed', 'false_positive') THEN NOW()
                    ELSE NULL
                END,
                resolution_note = COALESCE($4, resolution_note)
            WHERE id = $1
            RETURNING
                id, alert_ref, alert_type, status, severity, title,
                transaction_id, account_id, entity_id, case_id, assigned_to, created_at
            """,
            alert_id,
            payload.status.value,
            payload.reviewed_by,
            payload.resolution_note,
        )
    if row:
        await safe_resync_graph(clear_existing=True)
    return dict(row) if row else None


async def investigate_alert(alert_id: UUID, payload: AlertInvestigateRequest) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        alert = await conn.fetchrow(
            """
            SELECT id, alert_ref, title, description, transaction_id, account_id, case_id, status, metadata, assigned_to
            FROM alerts
            WHERE id = $1
            """,
            alert_id,
        )
        if not alert:
            return None

    async with pool.acquire() as conn:
        metadata = _normalize_json_dict(alert["metadata"])
        routing = await resolve_case_routing(
            conn,
            workflow_type="alert_investigation",
            alert_ids=[alert_id],
            preferred_assignee=payload.assigned_to or alert["assigned_to"],
            existing_metadata=metadata,
        )
        assigned_to = payload.assigned_to or routing.get("assigned_to") or alert["assigned_to"]
        metadata["routing"] = routing_metadata_payload(routing, workflow_type="alert_investigation", source="alert_investigate")
        note_text = f"Investigation started by {payload.reviewed_by or payload.assigned_to or payload.created_by or 'analyst'}."
        metadata = _append_alert_note(
            metadata,
            action="investigate",
            actor=payload.reviewed_by or payload.assigned_to or payload.created_by,
            note=note_text,
            status="reviewing",
            assigned_to=assigned_to,
        )
        await conn.execute(
            """
            UPDATE alerts
            SET
                status = 'reviewing',
                assigned_to = COALESCE($2, assigned_to),
                reviewed_by = COALESCE($3, reviewed_by),
                reviewed_at = NOW(),
                metadata = $4::jsonb,
                updated_at = NOW()
            WHERE id = $1
            """,
            alert_id,
            assigned_to,
            payload.reviewed_by,
            json.dumps(metadata),
        )

    if payload.create_case:
        if alert["case_id"]:
            return {
                "alert": await get_alert(alert_id),
                "case": await get_case_detail(alert["case_id"]),
            }
        case = await create_case(
            CaseCreate(
                title=payload.case_title or f"Investigate {alert['alert_ref']} — {alert['title']}",
                description=payload.case_description or alert["description"],
                priority=payload.priority,
                assigned_to=payload.assigned_to,
                created_by=payload.created_by or payload.reviewed_by,
                primary_account_id=alert["account_id"],
                alert_ids=[alert_id],
                transaction_ids=[alert["transaction_id"]] if alert["transaction_id"] else [],
                sar_required=False,
            )
        )
        return {
            "alert": await get_alert(alert_id),
            "case": case,
        }

    await safe_resync_graph(clear_existing=True)
    return {
        "alert": await get_alert(alert_id),
        "case": None,
    }


async def run_alert_action(alert_id: UUID, payload: AlertActionRequest) -> dict[str, Any] | None:
    if payload.action.value == "investigate":
        return await investigate_alert(
            alert_id,
            AlertInvestigateRequest(
                assigned_to=payload.assigned_to,
                reviewed_by=payload.actor,
                create_case=payload.create_case if payload.create_case is not None else True,
                case_title=payload.case_title,
                case_description=payload.case_description or payload.note,
                priority=payload.priority,
                created_by=payload.actor,
            ),
        )

    pool = get_pool()
    action = payload.action.value
    actor = payload.actor or payload.assigned_to
    note_text = (payload.note or "").strip() or None

    async with pool.acquire() as conn:
        async with conn.transaction():
            current = await conn.fetchrow(
                """
                SELECT id, alert_ref, title, description, transaction_id, account_id, entity_id, case_id,
                       status, assigned_to, metadata, reviewed_by, resolution_note
                FROM alerts
                WHERE id = $1
                FOR UPDATE
                """,
                alert_id,
            )
            if not current:
                return None

            current_status = current["status"]
            routing = await resolve_case_routing(
                conn,
                workflow_type="alert_investigation",
                alert_ids=[alert_id],
                preferred_assignee=payload.assigned_to or current["assigned_to"],
                existing_metadata=current["metadata"],
            )
            assigned_to = payload.assigned_to or current["assigned_to"] or routing.get("assigned_to")
            metadata = _normalize_json_dict(current["metadata"])
            metadata["routing"] = routing_metadata_payload(routing, workflow_type="alert_investigation", source=f"alert_{action}")
            linked_case_id = current["case_id"]

            if action == "add_note":
                if not note_text:
                    raise ValueError("Provide a note before saving alert notes.")
                metadata = _append_alert_note(
                    metadata,
                    action="note",
                    actor=actor,
                    note=note_text,
                    status=current_status,
                    assigned_to=assigned_to,
                )
                await conn.execute(
                    """
                    UPDATE alerts
                    SET
                        assigned_to = COALESCE($2, assigned_to),
                        metadata = $3::jsonb,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    alert_id,
                    assigned_to,
                    json.dumps(metadata),
                )
            else:
                status_map = {
                    "dismiss": "closed",
                    "false_positive": "false_positive",
                    "escalate": "escalated",
                }
                next_status = status_map.get(action)
                if not next_status:
                    raise ValueError(f"Unsupported alert action: {action}")

                default_note = {
                    "dismiss": "Alert dismissed after analyst review.",
                    "false_positive": "Alert marked as false positive after analyst review.",
                    "escalate": "Alert escalated for deeper investigation.",
                }[action]
                final_note = note_text or default_note
                metadata = _append_alert_note(
                    metadata,
                    action=action,
                    actor=actor,
                    note=final_note,
                    status=next_status,
                    assigned_to=assigned_to,
                )
                await conn.execute(
                    """
                    UPDATE alerts
                    SET
                        status = $2::alert_status,
                        assigned_to = COALESCE($3, assigned_to),
                        reviewed_by = COALESCE($4, reviewed_by),
                        reviewed_at = NOW(),
                        closed_at = CASE
                            WHEN $2::alert_status IN ('closed', 'false_positive') THEN NOW()
                            ELSE NULL
                        END,
                        resolution_note = CASE
                            WHEN $2::alert_status IN ('closed', 'false_positive') THEN $5
                            ELSE resolution_note
                        END,
                        metadata = $6::jsonb,
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    alert_id,
                    next_status,
                    assigned_to,
                    actor,
                    final_note,
                    json.dumps(metadata),
                )

    case_detail = None
    created_case = False
    if action == "escalate":
        should_create_case = payload.create_case if payload.create_case is not None else True
        if linked_case_id:
            case_detail = await get_case_detail(linked_case_id)
        elif should_create_case:
            case_detail = await create_case(
                CaseCreate(
                    title=payload.case_title or f"Escalated {current['alert_ref']} — {current['title']}",
                    description=payload.case_description or note_text or current["description"],
                    priority=payload.priority,
                    assigned_to=assigned_to,
                    created_by=actor,
                    primary_account_id=current["account_id"],
                    primary_entity_id=current["entity_id"],
                    alert_ids=[alert_id],
                    transaction_ids=[current["transaction_id"]] if current["transaction_id"] else [],
                    sar_required=True,
                    metadata={"source": "alert_escalation", "alert_ref": current["alert_ref"]},
                )
            )
            created_case = True
        if not created_case:
            await safe_resync_graph(clear_existing=True)
    else:
        await safe_resync_graph(clear_existing=True)

    return {
        "action": action,
        "alert": await get_alert(alert_id),
        "case": case_detail,
    }
