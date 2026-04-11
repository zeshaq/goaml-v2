"""
Typology playbooks, checklist evaluation, SLA targets, and auto-generated task support.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID
from uuid import uuid4

from core.config import settings
from core.database import get_pool

SUPPORTED_PLAYBOOKS = [
    "structuring",
    "sanctions_match",
    "layering",
    "pep_exposure",
    "large_cash",
    "crypto_mixing",
]

QUEUE_LABELS = {
    "draft": "draft",
    "review": "review",
    "approval": "approval",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return _utcnow().isoformat()


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


def _metadata_tasks(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    values = _normalize_json_list(metadata.get("tasks"))
    return [item for item in values if isinstance(item, dict)]


def _task_due_at(
    *,
    config: dict[str, Any],
    priority: str | None,
    queue_key: str,
) -> str | None:
    hours = resolve_playbook_sla_hours(
        queue_key=queue_key,
        case_metadata={"playbook": {"sla_targets": config.get("sla_targets") or {}}},
        case_priority=priority,
    )
    if hours is None:
        return None
    return (_utcnow() + timedelta(hours=float(hours))).isoformat()


def _priority_key(value: str | None) -> str:
    normalized = str(value or "medium").strip().lower()
    if normalized in {"low", "medium", "high", "critical"}:
        return normalized
    return "medium"


def _deepcopy_json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def _base_sla_targets(draft: float, review: float, approval: float) -> dict[str, dict[str, float]]:
    return {
        "low": {"draft": draft * 1.5, "review": review * 1.5, "approval": approval * 1.5},
        "medium": {"draft": draft, "review": review, "approval": approval},
        "high": {"draft": round(draft * 0.5, 2), "review": round(review * 0.5, 2), "approval": round(approval * 0.67, 2)},
        "critical": {"draft": round(draft * 0.25, 2), "review": round(review * 0.25, 2), "approval": round(max(approval * 0.33, 1.0), 2)},
    }


DEFAULT_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "structuring": {
        "display_name": "Structuring Investigation",
        "checklist": [
            {
                "key": "assign_owner",
                "label": "Assign an analyst owner",
                "description": "A named analyst should own the case before it leaves triage.",
                "condition": "case_assigned",
                "blocking": True,
                "guidance": "Assign a named analyst before formal review.",
            },
            {
                "key": "review_transaction_pattern",
                "label": "Review linked structuring transactions",
                "description": "Confirm threshold avoidance across linked transactions.",
                "condition": "task_done",
                "task_key": "review_transaction_pattern",
                "blocking": True,
                "guidance": "Complete the structuring pattern review task.",
            },
            {
                "key": "attach_support_document",
                "label": "Attach a supporting evidence document",
                "description": "KYC or account evidence should be directly attached to the case.",
                "condition": "direct_document",
                "blocking": True,
                "guidance": "Attach at least one direct evidence document.",
                "evidence_related": True,
            },
            {
                "key": "pin_filing_evidence",
                "label": "Pin filing evidence for the SAR",
                "description": "The strongest alerts and transaction trail should be pinned for filing.",
                "condition": "filing_evidence",
                "blocking": True,
                "guidance": "Mark at least two pinned evidence items for SAR inclusion.",
                "evidence_related": True,
            },
            {
                "key": "capture_case_summary",
                "label": "Capture investigation summary",
                "description": "Save an analyst or AI summary before handoff.",
                "condition": "case_summary",
                "blocking": False,
                "guidance": "Generate or save a case summary before review.",
            },
        ],
        "evidence_rules": {
            "min_pinned_evidence": 2,
            "min_filing_evidence": 2,
            "require_transaction_links": True,
            "require_alert_links": True,
            "require_direct_document": True,
        },
        "sla_targets": _base_sla_targets(48.0, 24.0, 12.0),
        "task_templates": [
            {
                "key": "review_transaction_pattern",
                "title": "Review structuring transaction pattern",
                "description": "Confirm threshold avoidance across linked transactions and document the suspicious pattern.",
                "priority": "high",
                "queue": "draft",
            },
            {
                "key": "collect_supporting_document",
                "title": "Attach supporting account evidence",
                "description": "Attach a direct evidence document before the SAR enters review.",
                "priority": "medium",
                "queue": "draft",
            },
        ],
        "metadata": {"focus": "threshold_avoidance"},
    },
    "sanctions_match": {
        "display_name": "Sanctions Match Investigation",
        "checklist": [
            {
                "key": "assign_owner",
                "label": "Assign an analyst owner",
                "condition": "case_assigned",
                "blocking": True,
                "guidance": "Assign a sanctions analyst before escalation.",
            },
            {
                "key": "validate_match",
                "label": "Validate sanctions match quality",
                "description": "Review hit quality and matched identifiers.",
                "condition": "task_done",
                "task_key": "validate_match_quality",
                "blocking": True,
                "guidance": "Complete the sanctions match validation task.",
            },
            {
                "key": "review_screening_hits",
                "label": "Review screening evidence",
                "condition": "screening_hit",
                "blocking": True,
                "guidance": "Confirm screening hits are present and reviewed.",
                "evidence_related": True,
            },
            {
                "key": "attach_support_document",
                "label": "Attach source or KYC document",
                "condition": "direct_document",
                "blocking": True,
                "guidance": "Attach a document that supports identity resolution.",
                "evidence_related": True,
            },
            {
                "key": "pin_filing_evidence",
                "label": "Pin filing evidence",
                "condition": "filing_evidence",
                "blocking": True,
                "guidance": "Pin the screening hit and supporting document for SAR use.",
                "evidence_related": True,
            },
        ],
        "evidence_rules": {
            "min_pinned_evidence": 2,
            "min_filing_evidence": 1,
            "require_screening_hit": True,
            "require_alert_links": True,
            "require_direct_document": True,
        },
        "sla_targets": _base_sla_targets(24.0, 12.0, 6.0),
        "task_templates": [
            {
                "key": "validate_match_quality",
                "title": "Validate sanctions match quality",
                "description": "Review sanctions identifiers, aliases, and country context before escalation.",
                "priority": "high",
                "queue": "draft",
            },
            {
                "key": "collect_identity_evidence",
                "title": "Collect identity and KYC evidence",
                "description": "Attach KYC or customer identity evidence to support the sanctions decision.",
                "priority": "high",
                "queue": "draft",
            },
        ],
        "metadata": {"focus": "sanctions_triage"},
    },
    "layering": {
        "display_name": "Layering Investigation",
        "checklist": [
            {
                "key": "assign_owner",
                "label": "Assign an analyst owner",
                "condition": "case_assigned",
                "blocking": True,
                "guidance": "Assign a named analyst before review.",
            },
            {
                "key": "map_transaction_chain",
                "label": "Map the transaction chain",
                "condition": "task_done",
                "task_key": "map_transaction_chain",
                "blocking": True,
                "guidance": "Complete the layering chain review task.",
            },
            {
                "key": "attach_support_document",
                "label": "Attach supporting document",
                "condition": "direct_document",
                "blocking": True,
                "guidance": "Attach at least one supporting document or memo.",
                "evidence_related": True,
            },
            {
                "key": "pin_filing_evidence",
                "label": "Pin key evidence for the filing pack",
                "condition": "filing_evidence",
                "blocking": True,
                "guidance": "Mark at least two pieces of evidence for SAR inclusion.",
                "evidence_related": True,
            },
            {
                "key": "capture_case_summary",
                "label": "Capture investigation summary",
                "condition": "case_summary",
                "blocking": False,
                "guidance": "Summarize the layering pattern before handoff.",
            },
        ],
        "evidence_rules": {
            "min_pinned_evidence": 3,
            "min_filing_evidence": 2,
            "require_transaction_links": True,
            "require_alert_links": True,
            "require_direct_document": True,
        },
        "sla_targets": _base_sla_targets(36.0, 18.0, 10.0),
        "task_templates": [
            {
                "key": "map_transaction_chain",
                "title": "Map layering transaction chain",
                "description": "Trace the layered movement of funds across accounts or counterparties.",
                "priority": "high",
                "queue": "draft",
            },
            {
                "key": "collect_supporting_document",
                "title": "Attach layering evidence memo",
                "description": "Attach a document or memo that explains the layered flow.",
                "priority": "medium",
                "queue": "draft",
            },
        ],
        "metadata": {"focus": "transaction_chain"},
    },
    "pep_exposure": {
        "display_name": "PEP Exposure Investigation",
        "checklist": [
            {
                "key": "assign_owner",
                "label": "Assign an analyst owner",
                "condition": "case_assigned",
                "blocking": True,
            },
            {
                "key": "validate_pep_exposure",
                "label": "Validate PEP exposure",
                "condition": "task_done",
                "task_key": "validate_pep_exposure",
                "blocking": True,
                "guidance": "Confirm the individual or related party exposure.",
            },
            {
                "key": "review_screening_hits",
                "label": "Review screening or source hits",
                "condition": "screening_hit",
                "blocking": False,
                "guidance": "Use screening evidence when it exists.",
                "evidence_related": True,
            },
            {
                "key": "attach_support_document",
                "label": "Attach source evidence",
                "condition": "direct_document",
                "blocking": True,
                "guidance": "Attach the source article, profile, or KYC note.",
                "evidence_related": True,
            },
            {
                "key": "pin_filing_evidence",
                "label": "Pin filing evidence",
                "condition": "filing_evidence",
                "blocking": True,
                "guidance": "Pin the PEP evidence and the triggering alert context.",
                "evidence_related": True,
            },
        ],
        "evidence_rules": {
            "min_pinned_evidence": 2,
            "min_filing_evidence": 1,
            "require_alert_links": True,
            "require_direct_document": True,
        },
        "sla_targets": _base_sla_targets(48.0, 24.0, 12.0),
        "task_templates": [
            {
                "key": "validate_pep_exposure",
                "title": "Validate PEP exposure",
                "description": "Confirm the PEP relationship and source reliability before escalation.",
                "priority": "high",
                "queue": "draft",
            },
            {
                "key": "collect_pep_source_document",
                "title": "Attach PEP source evidence",
                "description": "Attach a direct document that supports the exposure assessment.",
                "priority": "medium",
                "queue": "draft",
            },
        ],
        "metadata": {"focus": "politically_exposed_person"},
    },
    "large_cash": {
        "display_name": "Large Cash Investigation",
        "checklist": [
            {
                "key": "assign_owner",
                "label": "Assign an analyst owner",
                "condition": "case_assigned",
                "blocking": True,
            },
            {
                "key": "review_cash_activity",
                "label": "Review large cash activity",
                "condition": "task_done",
                "task_key": "review_cash_activity",
                "blocking": True,
                "guidance": "Confirm cash activity rationale and related behavior.",
            },
            {
                "key": "attach_support_document",
                "label": "Attach source or branch evidence",
                "condition": "direct_document",
                "blocking": True,
                "guidance": "Attach branch note, KYC source, or similar evidence.",
                "evidence_related": True,
            },
            {
                "key": "pin_filing_evidence",
                "label": "Pin filing evidence",
                "condition": "filing_evidence",
                "blocking": True,
                "guidance": "Pin the cash activity evidence and supporting document.",
                "evidence_related": True,
            },
        ],
        "evidence_rules": {
            "min_pinned_evidence": 2,
            "min_filing_evidence": 1,
            "require_alert_links": True,
            "require_transaction_links": True,
            "require_direct_document": True,
        },
        "sla_targets": _base_sla_targets(48.0, 24.0, 12.0),
        "task_templates": [
            {
                "key": "review_cash_activity",
                "title": "Review large cash activity",
                "description": "Assess rationale and frequency of the cash activity.",
                "priority": "high",
                "queue": "draft",
            },
            {
                "key": "collect_cash_source_evidence",
                "title": "Collect branch or source evidence",
                "description": "Attach supporting evidence for the large cash pattern.",
                "priority": "medium",
                "queue": "draft",
            },
        ],
        "metadata": {"focus": "cash_activity"},
    },
    "crypto_mixing": {
        "display_name": "Crypto Mixing Investigation",
        "checklist": [
            {
                "key": "assign_owner",
                "label": "Assign an analyst owner",
                "condition": "case_assigned",
                "blocking": True,
            },
            {
                "key": "trace_wallet_chain",
                "label": "Trace wallet or transfer chain",
                "condition": "task_done",
                "task_key": "trace_wallet_chain",
                "blocking": True,
                "guidance": "Confirm the mixer or obfuscation pattern.",
            },
            {
                "key": "attach_support_document",
                "label": "Attach wallet or exchange evidence",
                "condition": "direct_document",
                "blocking": True,
                "guidance": "Attach wallet notes, exchange correspondence, or a memo.",
                "evidence_related": True,
            },
            {
                "key": "pin_filing_evidence",
                "label": "Pin filing evidence",
                "condition": "filing_evidence",
                "blocking": True,
                "guidance": "Mark at least two evidence items for SAR use.",
                "evidence_related": True,
            },
        ],
        "evidence_rules": {
            "min_pinned_evidence": 3,
            "min_filing_evidence": 2,
            "require_alert_links": True,
            "require_transaction_links": True,
            "require_direct_document": True,
        },
        "sla_targets": _base_sla_targets(24.0, 12.0, 6.0),
        "task_templates": [
            {
                "key": "trace_wallet_chain",
                "title": "Trace crypto wallet chain",
                "description": "Trace the wallet path and confirm mixer or obfuscation behavior.",
                "priority": "high",
                "queue": "draft",
            },
            {
                "key": "collect_exchange_evidence",
                "title": "Collect exchange or wallet evidence",
                "description": "Attach a document or memo that supports the crypto tracing analysis.",
                "priority": "medium",
                "queue": "draft",
            },
        ],
        "metadata": {"focus": "crypto_trace"},
    },
}


TYPOLOGY_PRIORITY = {
    "sanctions_match": 100,
    "pep_exposure": 90,
    "crypto_mixing": 80,
    "layering": 70,
    "structuring": 60,
    "large_cash": 50,
}


async def _ensure_default_playbook_configs(conn: Any) -> None:
    for typology, config in DEFAULT_PLAYBOOKS.items():
        await conn.execute(
            """
            INSERT INTO case_playbook_configs (
                typology, display_name, checklist, evidence_rules, sla_targets, task_templates, updated_by, metadata
            ) VALUES (
                $1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8::jsonb
            )
            ON CONFLICT (typology) DO NOTHING
            """,
            typology,
            config["display_name"],
            json.dumps(config.get("checklist") or []),
            json.dumps(config.get("evidence_rules") or {}),
            json.dumps(config.get("sla_targets") or {}),
            json.dumps(config.get("task_templates") or []),
            "system-default",
            json.dumps(config.get("metadata") or {}),
        )


def _normalize_playbook_row(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["checklist"] = [entry for entry in _normalize_json_list(item.get("checklist")) if isinstance(entry, dict)]
    item["evidence_rules"] = _normalize_json_dict(item.get("evidence_rules"))
    item["sla_targets"] = _normalize_json_dict(item.get("sla_targets"))
    item["task_templates"] = [entry for entry in _normalize_json_list(item.get("task_templates")) if isinstance(entry, dict)]
    item["metadata"] = _normalize_json_dict(item.get("metadata"))
    return item


async def list_playbook_configs() -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_default_playbook_configs(conn)
            rows = await conn.fetch(
                """
                SELECT typology, display_name, checklist, evidence_rules, sla_targets, task_templates, updated_by, updated_at, metadata
                FROM case_playbook_configs
                ORDER BY display_name ASC
                """
            )
    return [_normalize_playbook_row(dict(row)) for row in rows]


async def get_playbook_config(typology: str, *, conn: Any | None = None) -> dict[str, Any] | None:
    typology_key = str(typology or "").strip().lower()
    if not typology_key:
        return None
    if conn is not None:
        await _ensure_default_playbook_configs(conn)
        row = await conn.fetchrow(
            """
            SELECT typology, display_name, checklist, evidence_rules, sla_targets, task_templates, updated_by, updated_at, metadata
            FROM case_playbook_configs
            WHERE typology = $1
            """,
            typology_key,
        )
        return _normalize_playbook_row(dict(row)) if row else None

    pool = get_pool()
    async with pool.acquire() as local_conn:
        return await get_playbook_config(typology_key, conn=local_conn)


async def update_playbook_config(typology: str, payload: dict[str, Any]) -> dict[str, Any]:
    typology_key = str(typology or "").strip().lower()
    if typology_key not in SUPPORTED_PLAYBOOKS:
        raise ValueError(f"Unsupported playbook typology: {typology}")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_default_playbook_configs(conn)
            current = await get_playbook_config(typology_key, conn=conn)
            if not current:
                raise ValueError(f"Playbook not found: {typology}")

            updated = {
                "display_name": payload.get("display_name") or current["display_name"],
                "checklist": payload.get("checklist") if payload.get("checklist") is not None else current["checklist"],
                "evidence_rules": payload.get("evidence_rules") if payload.get("evidence_rules") is not None else current["evidence_rules"],
                "sla_targets": payload.get("sla_targets") if payload.get("sla_targets") is not None else current["sla_targets"],
                "task_templates": payload.get("task_templates") if payload.get("task_templates") is not None else current["task_templates"],
                "updated_by": payload.get("updated_by") or current.get("updated_by"),
                "metadata": payload.get("metadata") if payload.get("metadata") is not None else current["metadata"],
            }
            row = await conn.fetchrow(
                """
                UPDATE case_playbook_configs
                SET
                    display_name = $2,
                    checklist = $3::jsonb,
                    evidence_rules = $4::jsonb,
                    sla_targets = $5::jsonb,
                    task_templates = $6::jsonb,
                    updated_by = $7,
                    metadata = $8::jsonb,
                    updated_at = NOW()
                WHERE typology = $1
                RETURNING typology, display_name, checklist, evidence_rules, sla_targets, task_templates, updated_by, updated_at, metadata
                """,
                typology_key,
                updated["display_name"],
                json.dumps(updated["checklist"] or []),
                json.dumps(updated["evidence_rules"] or {}),
                json.dumps(updated["sla_targets"] or {}),
                json.dumps(updated["task_templates"] or []),
                updated["updated_by"],
                json.dumps(updated["metadata"] or {}),
            )
    return _normalize_playbook_row(dict(row))


def infer_case_typology(*, metadata: dict[str, Any] | None, alert_types: list[str]) -> str | None:
    metadata = metadata or {}
    explicit = str(
        _normalize_json_dict(metadata.get("playbook")).get("typology")
        or metadata.get("typology")
        or metadata.get("primary_typology")
        or ""
    ).strip().lower()
    if explicit in SUPPORTED_PLAYBOOKS:
        return explicit

    candidates = [str(item or "").strip().lower() for item in alert_types if str(item or "").strip().lower() in SUPPORTED_PLAYBOOKS]
    if not candidates:
        return None
    ranked = sorted(candidates, key=lambda item: (-TYPOLOGY_PRIORITY.get(item, 0), item))
    return ranked[0]


async def _fetch_case_typology_context(conn: Any, case_id: UUID) -> tuple[dict[str, Any] | None, list[str]]:
    case_row = await conn.fetchrow("SELECT * FROM cases WHERE id = $1", case_id)
    if not case_row:
        return None, []
    alert_rows = await conn.fetch(
        """
        SELECT DISTINCT a.alert_type
        FROM case_alerts ca
        JOIN alerts a ON a.id = ca.alert_id
        WHERE ca.case_id = $1
        ORDER BY a.alert_type
        """,
        case_id,
    )
    return dict(case_row), [str(row["alert_type"]) for row in alert_rows if row.get("alert_type")]


def resolve_playbook_sla_hours(
    *,
    queue_key: str,
    case_metadata: dict[str, Any] | None,
    case_priority: str | None,
) -> float | None:
    priority_key = _priority_key(case_priority)
    playbook = _normalize_json_dict((case_metadata or {}).get("playbook"))
    sla_targets = _normalize_json_dict(playbook.get("sla_targets"))
    priority_targets = _normalize_json_dict(sla_targets.get(priority_key))
    value = priority_targets.get(queue_key)
    if value is not None:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    if queue_key == "draft":
        return settings.SAR_DRAFT_SLA_HOURS
    if queue_key == "review":
        return settings.SAR_REVIEW_SLA_HOURS
    if queue_key == "approval":
        return settings.SAR_APPROVAL_SLA_HOURS
    return None


def _build_auto_task(*, template: dict[str, Any], case_row: dict[str, Any], assigned_to: str | None, typology: str) -> dict[str, Any]:
    metadata = {
        "auto_generated": True,
        "playbook_typology": typology,
        "playbook_task_key": template.get("key"),
        "task_template": template,
    }
    return {
        "id": str(uuid4()),
        "title": template.get("title") or "Playbook task",
        "description": template.get("description"),
        "status": "open",
        "priority": str(template.get("priority") or "medium"),
        "assigned_to": assigned_to,
        "created_by": "playbook-engine",
        "note": template.get("note"),
        "created_at": _iso_now(),
        "updated_at": _iso_now(),
        "due_at": _task_due_at(
            config={"sla_targets": case_row.get("_playbook_sla_targets") or {}},
            priority=case_row.get("priority"),
            queue_key=str(template.get("queue") or "draft"),
        ),
        "completed_at": None,
        "metadata": metadata,
    }


async def apply_case_playbook(case_id: UUID, *, actor: str | None = None) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_default_playbook_configs(conn)
            case_row, alert_types = await _fetch_case_typology_context(conn, case_id)
            if not case_row:
                return None

            metadata = _normalize_json_dict(case_row.get("metadata"))
            typology = infer_case_typology(metadata=metadata, alert_types=alert_types)
            if not typology:
                return {
                    "case_id": case_id,
                    "applied": False,
                    "typology": None,
                    "tasks_created": [],
                }

            config = await get_playbook_config(typology, conn=conn)
            if not config:
                return {
                    "case_id": case_id,
                    "applied": False,
                    "typology": typology,
                    "tasks_created": [],
                }

            tasks = _metadata_tasks(metadata)
            task_lookup = {
                str(_normalize_json_dict(task.get("metadata")).get("playbook_task_key") or ""): task
                for task in tasks
                if str(_normalize_json_dict(task.get("metadata")).get("playbook_task_key") or "").strip()
            }
            assigned_to = case_row.get("assigned_to") or _normalize_json_dict(metadata.get("routing")).get("assigned_to")
            case_row["_playbook_sla_targets"] = config.get("sla_targets") or {}

            tasks_created: list[dict[str, Any]] = []
            for template in config.get("task_templates") or []:
                task_key = str(template.get("key") or "").strip()
                if not task_key or task_key in task_lookup:
                    continue
                task = _build_auto_task(
                    template=template,
                    case_row=case_row,
                    assigned_to=assigned_to,
                    typology=typology,
                )
                tasks.append(task)
                tasks_created.append(task)

            previous_playbook = _normalize_json_dict(metadata.get("playbook"))
            playbook_payload = {
                "typology": typology,
                "display_name": config["display_name"],
                "checklist": config.get("checklist") or [],
                "evidence_rules": config.get("evidence_rules") or {},
                "sla_targets": config.get("sla_targets") or {},
                "task_templates": config.get("task_templates") or [],
                "configured_at": previous_playbook.get("configured_at") or _iso_now(),
                "updated_at": _iso_now(),
            }
            previous_snapshot = {
                "typology": previous_playbook.get("typology"),
                "display_name": previous_playbook.get("display_name"),
                "checklist": previous_playbook.get("checklist") or [],
                "evidence_rules": previous_playbook.get("evidence_rules") or {},
                "sla_targets": previous_playbook.get("sla_targets") or {},
                "task_templates": previous_playbook.get("task_templates") or [],
            }
            next_snapshot = {
                "typology": playbook_payload["typology"],
                "display_name": playbook_payload["display_name"],
                "checklist": playbook_payload["checklist"],
                "evidence_rules": playbook_payload["evidence_rules"],
                "sla_targets": playbook_payload["sla_targets"],
                "task_templates": playbook_payload["task_templates"],
            }
            changed = previous_snapshot != next_snapshot or bool(tasks_created)
            if not changed:
                return {
                    "case_id": case_id,
                    "applied": False,
                    "typology": typology,
                    "tasks_created": [],
                }
            metadata["playbook"] = playbook_payload
            metadata["typology"] = typology
            metadata["tasks"] = tasks[-150:]

            await conn.execute(
                """
                UPDATE cases
                SET metadata = $2::jsonb, updated_at = NOW()
                WHERE id = $1
                """,
                case_id,
                json.dumps(metadata),
            )

            event_type = "playbook_applied" if previous_playbook.get("typology") != typology else "playbook_refreshed"
            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, $2, $3, $4, $5::jsonb)
                """,
                case_id,
                event_type,
                actor or "playbook-engine",
                f"{config['display_name']} playbook applied",
                json.dumps(
                    {
                        "typology": typology,
                        "tasks_created": [task["title"] for task in tasks_created],
                    }
                ),
            )

            for task in tasks_created:
                await conn.execute(
                    """
                    INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                    VALUES ($1, 'task_created', $2, $3, $4::jsonb)
                    """,
                    case_id,
                    actor or "playbook-engine",
                    f"Task created: {task['title']}",
                    json.dumps(
                        {
                            "task_id": task["id"],
                            "assigned_to": task.get("assigned_to"),
                            "priority": task.get("priority"),
                            "auto_generated": True,
                            "playbook_typology": typology,
                            "playbook_task_key": _normalize_json_dict(task.get("metadata")).get("playbook_task_key"),
                        }
                    ),
                )

    return {
        "case_id": case_id,
        "applied": True,
        "typology": typology,
        "tasks_created": tasks_created,
    }


async def backfill_case_playbooks(*, actor: str | None = None, typology: str | None = None, limit: int = 500) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await _ensure_default_playbook_configs(conn)
            rows = await conn.fetch(
                """
                SELECT c.id, c.metadata
                FROM cases c
                ORDER BY c.updated_at DESC, c.created_at DESC
                LIMIT $1
                """,
                limit,
            )

    processed_count = 0
    applied_count = 0
    task_count = 0
    typology_filter = str(typology or "").strip().lower()

    for row in rows:
        case_id = row["id"]
        metadata = _normalize_json_dict(row.get("metadata"))
        metadata_typology = str(
            _normalize_json_dict(metadata.get("playbook")).get("typology")
            or metadata.get("typology")
            or ""
        ).strip().lower()
        if typology_filter and metadata_typology and metadata_typology != typology_filter:
            continue
        result = await apply_case_playbook(case_id, actor=actor or "playbook-backfill")
        processed_count += 1
        if result and result.get("applied"):
            applied_count += 1
            task_count += len(result.get("tasks_created") or [])

    summary = [
        f"Processed {processed_count} cases for playbook backfill.",
        f"Applied or refreshed {applied_count} playbooks.",
        f"Created {task_count} playbook tasks.",
    ]
    if typology_filter:
        summary.append(f"Backfill scope was limited to {typology_filter}.")
    return {
        "processed_count": processed_count,
        "applied_count": applied_count,
        "task_count": task_count,
        "summary": summary,
        "generated_at": _utcnow(),
    }


def _build_case_playbook_snapshot(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "typology": config.get("typology"),
        "display_name": config.get("display_name"),
        "checklist": _deepcopy_json(config.get("checklist") or []),
        "evidence_rules": _deepcopy_json(config.get("evidence_rules") or {}),
        "sla_targets": _deepcopy_json(config.get("sla_targets") or {}),
        "task_templates": _deepcopy_json(config.get("task_templates") or []),
    }


def _check_condition(
    *,
    condition: str,
    task: dict[str, Any] | None,
    stats: dict[str, Any],
) -> bool:
    if condition == "case_assigned":
        return bool(stats["assigned"])
    if condition == "direct_document":
        return stats["direct_document_count"] > 0
    if condition == "filing_evidence":
        return stats["filing_evidence_count"] > 0
    if condition == "screening_hit":
        return stats["screening_hit_count"] > 0
    if condition == "case_summary":
        return bool(stats["case_summary"])
    if condition == "sar_draft":
        return bool(stats["sar_exists"])
    if condition == "sar_approved":
        return bool(stats["sar_approved"])
    if condition == "transaction_links":
        return stats["transaction_count"] > 0
    if condition == "alert_links":
        return stats["alert_count"] > 0
    if condition == "task_done":
        return str((task or {}).get("status") or "").lower() == "done"
    return False


def _evidence_rule_items(*, stats: dict[str, Any], rules: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    items: list[dict[str, Any]] = []
    missing: list[str] = []

    def add_item(
        *,
        rule_key: str,
        label: str,
        required: bool,
        met: bool,
        current_value: Any,
        required_value: Any,
        message: str,
    ) -> None:
        if not required and not met and current_value in {None, False, 0}:
            return
        items.append(
            {
                "rule_key": rule_key,
                "label": label,
                "required": required,
                "met": met,
                "current_value": current_value,
                "required_value": required_value,
                "message": message,
            }
        )
        if required and not met:
            missing.append(label)

    min_pinned = int(rules.get("min_pinned_evidence") or 0)
    if min_pinned:
        add_item(
            rule_key="min_pinned_evidence",
            label="Pinned evidence minimum",
            required=True,
            met=stats["pinned_evidence_count"] >= min_pinned,
            current_value=stats["pinned_evidence_count"],
            required_value=min_pinned,
            message=f"Need at least {min_pinned} pinned evidence items.",
        )

    min_filing = int(rules.get("min_filing_evidence") or 0)
    if min_filing:
        add_item(
            rule_key="min_filing_evidence",
            label="Filing evidence minimum",
            required=True,
            met=stats["filing_evidence_count"] >= min_filing,
            current_value=stats["filing_evidence_count"],
            required_value=min_filing,
            message=f"Need at least {min_filing} pinned evidence items marked for SAR inclusion.",
        )

    if bool(rules.get("require_direct_document")):
        add_item(
            rule_key="require_direct_document",
            label="Direct evidence document",
            required=True,
            met=stats["direct_document_count"] > 0,
            current_value=stats["direct_document_count"],
            required_value=1,
            message="Attach a direct evidence document to the case.",
        )
    if bool(rules.get("require_screening_hit")):
        add_item(
            rule_key="require_screening_hit",
            label="Screening hit evidence",
            required=True,
            met=stats["screening_hit_count"] > 0,
            current_value=stats["screening_hit_count"],
            required_value=1,
            message="Review or add a screening hit linked to the case.",
        )
    if bool(rules.get("require_transaction_links")):
        add_item(
            rule_key="require_transaction_links",
            label="Linked transactions",
            required=True,
            met=stats["transaction_count"] > 0,
            current_value=stats["transaction_count"],
            required_value=1,
            message="Link transactions to the case before review or filing.",
        )
    if bool(rules.get("require_alert_links")):
        add_item(
            rule_key="require_alert_links",
            label="Linked alerts",
            required=True,
            met=stats["alert_count"] > 0,
            current_value=stats["alert_count"],
            required_value=1,
            message="Link at least one alert to the case.",
        )

    return items, missing


async def get_case_playbook_state(
    case_id: UUID,
    *,
    case_row: dict[str, Any] | None = None,
    sar_row: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
    tasks: list[dict[str, Any]] | None = None,
    direct_document_count: int | None = None,
    screening_hit_count: int | None = None,
    alert_count: int | None = None,
    transaction_count: int | None = None,
) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await _ensure_default_playbook_configs(conn)
        if case_row is None:
            case_data, alert_types = await _fetch_case_typology_context(conn, case_id)
            if not case_data:
                return None
            case_row = case_data
        else:
            alert_type_rows = await conn.fetch(
                """
                SELECT DISTINCT a.alert_type
                FROM case_alerts ca
                JOIN alerts a ON a.id = ca.alert_id
                WHERE ca.case_id = $1
                ORDER BY a.alert_type
                """,
                case_id,
            )
            alert_types = [str(row["alert_type"]) for row in alert_type_rows if row.get("alert_type")]

        metadata = _normalize_json_dict(case_row.get("metadata"))
        typology = infer_case_typology(metadata=metadata, alert_types=alert_types)
        if not typology:
            return None

        config = await get_playbook_config(typology, conn=conn)
        if not config:
            return None

        if sar_row is None:
            sar = await conn.fetchrow("SELECT * FROM sar_reports WHERE id = $1", case_row.get("sar_id")) if case_row.get("sar_id") else None
            sar_row = dict(sar) if sar else {}
        if evidence is None:
            evidence_rows = await conn.fetch(
                """
                SELECT id, evidence_type, include_in_sar, importance, metadata
                FROM case_evidence
                WHERE case_id = $1
                ORDER BY include_in_sar DESC, importance DESC, pinned_at DESC
                """,
                case_id,
            )
            evidence = [dict(row) for row in evidence_rows]
        if tasks is None:
            tasks = _metadata_tasks(metadata)
        if alert_count is None:
            alert_count = int(
                await conn.fetchval("SELECT COUNT(*) FROM case_alerts WHERE case_id = $1", case_id) or 0
            )
        if transaction_count is None:
            transaction_count = int(
                await conn.fetchval("SELECT COUNT(*) FROM case_transactions WHERE case_id = $1", case_id) or 0
            )
        if direct_document_count is None:
            direct_document_count = int(
                await conn.fetchval("SELECT COUNT(*) FROM documents WHERE case_id = $1", case_id) or 0
            )
        if screening_hit_count is None:
            screening_hit_count = int(
                await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM screening_results sr
                    WHERE ($1::uuid IS NOT NULL AND sr.entity_id = $1)
                       OR sr.linked_txn_id IN (
                            SELECT transaction_id FROM case_transactions WHERE case_id = $2
                       )
                    """,
                    case_row.get("primary_entity_id"),
                    case_id,
                )
                or 0
            )

    sar_metadata = _normalize_json_dict((sar_row or {}).get("metadata"))
    filing_evidence_count = sum(1 for item in evidence if bool(item.get("include_in_sar")))
    pinned_evidence_count = len(evidence)
    task_index = {
        str(_normalize_json_dict(task.get("metadata")).get("playbook_task_key") or ""): task
        for task in tasks
        if str(_normalize_json_dict(task.get("metadata")).get("playbook_task_key") or "").strip()
    }
    stats = {
        "assigned": bool(case_row.get("assigned_to")),
        "alert_count": int(alert_count or 0),
        "transaction_count": int(transaction_count or 0),
        "direct_document_count": int(direct_document_count or 0),
        "screening_hit_count": int(screening_hit_count or 0),
        "pinned_evidence_count": int(pinned_evidence_count),
        "filing_evidence_count": int(filing_evidence_count),
        "case_summary": bool(case_row.get("ai_summary")),
        "sar_exists": bool((sar_row or {}).get("id")),
        "sar_approved": str((sar_row or {}).get("status") or "").lower() in {"approved", "filed"},
    }

    checklist: list[dict[str, Any]] = []
    blocked_steps: list[str] = []
    suggested_tasks: list[str] = []
    completed_count = 0

    for raw_item in config.get("checklist") or []:
        item = dict(raw_item)
        condition = str(item.get("condition") or "task_done")
        task_key = str(item.get("task_key") or "")
        task = task_index.get(task_key)
        met = _check_condition(condition=condition, task=task, stats=stats)
        if met:
            status = "done"
            completed_count += 1
        elif task:
            status = str(task.get("status") or "open")
        else:
            status = "missing"
        checklist_item = {
            "key": item.get("key") or task_key or condition,
            "label": item.get("label") or str(item.get("key") or condition).replace("_", " ").title(),
            "description": item.get("description"),
            "status": status,
            "blocking": bool(item.get("blocking", True)),
            "guidance": item.get("guidance"),
            "evidence_related": bool(item.get("evidence_related")),
            "auto_task_id": task.get("id") if task else None,
        }
        checklist.append(checklist_item)
        if not met and bool(item.get("blocking", True)):
            blocked_steps.append(checklist_item["label"])
        if not met and task and str(task.get("status") or "").lower() != "done":
            suggested_tasks.append(task.get("title") or checklist_item["label"])

    evidence_rule_items, required_evidence_missing = _evidence_rule_items(
        stats=stats,
        rules=config.get("evidence_rules") or {},
    )
    checklist_total = len(checklist)
    checklist_progress = int(round((completed_count / checklist_total) * 100)) if checklist_total else 100

    priority_key = _priority_key(case_row.get("priority"))
    priority_sla = _normalize_json_dict(_normalize_json_dict(config.get("sla_targets")).get(priority_key))

    summary = [
        f"{config['display_name']} is active for this case.",
        f"Checklist progress is {completed_count}/{checklist_total or 0}.",
    ]
    if blocked_steps:
        summary.append(f"{len(blocked_steps)} blocking checklist steps remain open.")
    if required_evidence_missing:
        summary.append(f"Required evidence is still missing: {', '.join(required_evidence_missing[:3])}.")
    if priority_sla:
        summary.append(
            f"{priority_key.title()} priority targets: draft {priority_sla.get('draft', 'n/a')}h, review {priority_sla.get('review', 'n/a')}h, approval {priority_sla.get('approval', 'n/a')}h."
        )

    return {
        "typology": typology,
        "display_name": config["display_name"],
        "active": True,
        "checklist_progress": checklist_progress,
        "checklist_completed_count": completed_count,
        "checklist_total_count": checklist_total,
        "checklist": checklist,
        "blocked_steps": blocked_steps,
        "required_evidence_missing": required_evidence_missing,
        "evidence_rules": evidence_rule_items,
        "suggested_tasks": list(dict.fromkeys([item for item in suggested_tasks if item]))[:8],
        "sla_targets": priority_sla,
        "summary": summary,
        "configured_at": _safe_datetime(_normalize_json_dict(metadata.get("playbook")).get("configured_at")),
        "updated_at": _safe_datetime(config.get("updated_at")) or _safe_datetime(_normalize_json_dict(metadata.get("playbook")).get("updated_at")),
    }


async def enforce_case_playbook(case_id: UUID, *, stage: str) -> dict[str, Any] | None:
    playbook = await get_case_playbook_state(case_id)
    if not playbook:
        return None
    if stage not in {"submit_review", "file"}:
        return playbook

    blocking = list(playbook.get("blocked_steps") or [])
    missing = list(playbook.get("required_evidence_missing") or [])
    if blocking or missing:
        stage_label = "SAR review" if stage == "submit_review" else "SAR filing"
        parts: list[str] = []
        if blocking:
            parts.append("checklist blockers: " + ", ".join(blocking[:3]))
        if missing:
            parts.append("missing evidence: " + ", ".join(missing[:3]))
        raise ValueError(f"{stage_label} is blocked by the active {playbook['display_name']} playbook: {'; '.join(parts)}.")
    return playbook
