"""
Higher-maturity workflow, evidence, network, and model-support features.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import json
from typing import Any
from uuid import UUID

from core.database import get_pool
from services.case_playbooks import list_playbook_configs
from services.graph_sync import get_graph_drilldown
from services.manager_console import get_manager_console
from services.management_reporting import get_management_reporting_overview
from services.model_registry import get_scorer_model_ops_summary, get_scorer_outcome_analytics
from services.workflow_engine import _record_notification_event, get_camunda_dashboard


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


async def get_alert_bulk_preview(alert_ids: list[UUID], action: str) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT a.id, a.alert_ref, a.title, a.status, a.severity, a.assigned_to, a.metadata,
                   c.case_ref
            FROM alerts a
            LEFT JOIN cases c ON c.id = a.case_id
            WHERE a.id = ANY($1::uuid[])
            ORDER BY a.created_at DESC
            """,
            alert_ids,
        )
    items = []
    teams = Counter()
    for row in rows:
        metadata = _normalize_json_dict(row["metadata"])
        routing = _normalize_json_dict(metadata.get("routing"))
        team_key = str(routing.get("team_key") or "")
        region_key = str(routing.get("region_key") or "")
        if team_key:
            teams[team_key] += 1
        items.append(
            {
                "id": str(row["id"]),
                "ref": row["alert_ref"],
                "title": row["title"],
                "status": row["status"],
                "severity": row["severity"],
                "owner": row["assigned_to"],
                "team_key": team_key or None,
                "region_key": region_key or None,
                "metadata": {"case_ref": row["case_ref"]},
            }
        )
    templates = [
        {
            "key": "bulk_escalation_note",
            "label": "Escalation rationale",
            "action": "escalate",
            "note_template": "Escalated after queue triage due to recurring risk indicators and typology alignment.",
            "metadata": {"recommended_for": ["escalate"]},
        },
        {
            "key": "false_positive_note",
            "label": "False positive rationale",
            "action": "false_positive",
            "note_template": "Closed as false positive after analyst review found no corroborating evidence.",
            "metadata": {"recommended_for": ["false_positive"]},
        },
    ]
    summary = [
        f"Prepared a bulk preview for {len(items)} alert(s).",
        f"Most represented team: {teams.most_common(1)[0][0]}" if teams else "No routed team metadata is present on the current selection.",
    ]
    return {
        "scope": "alerts",
        "action": action,
        "selected_count": len(items),
        "preview_items": items,
        "templates": templates,
        "summary": summary,
        "generated_at": _utcnow(),
    }


async def get_sar_bulk_preview(case_ids: list[UUID], action: str) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT c.id, c.case_ref, c.title, c.status, c.priority, c.assigned_to, c.metadata,
                   s.status AS sar_status, s.sar_ref
            FROM cases c
            LEFT JOIN sar_reports s ON s.case_id = c.id
            WHERE c.id = ANY($1::uuid[])
            ORDER BY c.updated_at DESC
            """,
            case_ids,
        )
    items = []
    owners = Counter()
    for row in rows:
        metadata = _normalize_json_dict(row["metadata"])
        routing = _normalize_json_dict(metadata.get("routing"))
        owner = row["assigned_to"]
        if owner:
            owners[owner] += 1
        items.append(
            {
                "id": str(row["id"]),
                "ref": row["case_ref"],
                "title": row["title"],
                "status": row["sar_status"] or row["status"],
                "severity": row["priority"],
                "owner": owner,
                "team_key": routing.get("team_key"),
                "region_key": routing.get("region_key"),
                "metadata": {"sar_ref": row["sar_ref"]},
            }
        )
    templates = [
        {
            "key": "review_return_template",
            "label": "Review return note",
            "action": "reject",
            "note_template": "Returned for revision because evidence completeness or narrative support is not yet sufficient.",
            "metadata": {"recommended_for": ["reject"]},
        },
        {
            "key": "approval_template",
            "label": "Approval note",
            "action": "approve",
            "note_template": "Approved after review of evidence completeness, workflow history, and filing readiness.",
            "metadata": {"recommended_for": ["approve", "file"]},
        },
    ]
    return {
        "scope": "sar_queue",
        "action": action,
        "selected_count": len(items),
        "preview_items": items,
        "templates": templates,
        "summary": [
            f"Prepared a bulk preview for {len(items)} SAR queue item(s).",
            f"Most represented owner: {owners.most_common(1)[0][0]}" if owners else "No queue owner is set on the current selection.",
        ],
        "generated_at": _utcnow(),
    }


async def get_manager_console_advanced() -> dict[str, Any]:
    console = await get_manager_console(team_key=None, region_key=None, typology=None, sla_status=None, owner=None, limit=80)
    report = await get_management_reporting_overview(range_days=180, snapshot_scope="manager")
    saved_workspaces = [
        {
            "key": "global_breaches",
            "label": "Global breach watch",
            "description": "Focus on all breached SAR and alert queues regardless of pod.",
            "filters": {"sla_status": "breached"},
            "metadata": {"recommended_for": ["manager"]},
        },
        {
            "key": "sanctions_hotspot",
            "label": "Sanctions hotspot board",
            "description": "Jump into sanctions-heavy teams and typologies first.",
            "filters": {"typology": "sanctions_match"},
            "metadata": {"recommended_for": ["manager", "sanctions_manager"]},
        },
    ]
    balancing_rules = [
        {
            "key": "rebalance_breached_first",
            "label": "Rebalance breached work first",
            "value": "enabled",
            "description": "Prioritize breached and due-soon queues before redistributing routine work.",
            "editable": False,
        },
        {
            "key": "regional_ownership_bias",
            "label": "Prefer same-region routing",
            "value": "enabled",
            "description": "Keep reassignment in-region where possible to reduce context switching.",
            "editable": False,
        },
    ]
    interventions = []
    for item in list(report.get("action_recommendations") or [])[:8]:
        metadata = _normalize_json_dict(item.get("metadata"))
        interventions.append(
            {
                "key": item.get("recommendation_key") or item.get("key") or "manager_intervention",
                "title": item.get("title") or "Manager intervention",
                "severity": item.get("severity") or "info",
                "rationale": item.get("rationale") or item.get("note") or "Manager attention is recommended.",
                "suggested_action": item.get("suggested_action"),
                "target_scope": item.get("target_scope"),
                "target_key": item.get("target_key"),
                "metadata": metadata,
            }
        )
    team_hotspots = []
    for item in (report.get("false_positive_by_team") or [])[:6]:
        team_hotspots.append(
            {
                "scope_key": item.get("scope_key"),
                "scope_label": item.get("scope_label"),
                "backlog_count": int(item.get("count") or 0),
                "breached_count": 0,
                "high_priority_count": 0,
                "avg_age_hours": item.get("secondary_metric"),
                "typology_mix": [],
            }
        )
    region_hotspots = []
    for item in (report.get("filed_sar_volume_by_region") or [])[:6]:
        region_hotspots.append(
            {
                "scope_key": item.get("scope_key"),
                "scope_label": item.get("scope_label"),
                "backlog_count": int(item.get("count") or 0),
                "breached_count": 0,
                "high_priority_count": 0,
                "avg_age_hours": item.get("secondary_metric"),
                "typology_mix": [],
            }
        )
    return {
        "generated_at": _utcnow(),
        "saved_workspaces": saved_workspaces,
        "balancing_rules": balancing_rules,
        "intervention_suggestions": interventions,
        "team_hotspots": team_hotspots,
        "region_hotspots": region_hotspots,
        "summary": [
            f"{len(interventions)} manager intervention suggestion(s) are active.",
            f"{len(console.get('workload_board') or [])} owner workload row(s) are currently visible in the manager console.",
        ],
    }


async def get_workflow_exceptions(limit: int = 20) -> dict[str, Any]:
    pool = get_pool()
    camunda = await get_camunda_dashboard(limit=10)
    async with pool.acquire() as conn:
        case_rows = await conn.fetch(
            """
            SELECT c.id, c.case_ref, c.assigned_to, c.metadata, c.updated_at,
                   s.status AS sar_status, s.reviewed_at, s.approved_at
            FROM cases c
            LEFT JOIN sar_reports s ON s.case_id = c.id
            WHERE c.status IN ('reviewing', 'pending_sar', 'open')
            ORDER BY c.updated_at DESC
            LIMIT $1
            """,
            max(limit * 2, 40),
        )
        recent_notifications = await conn.fetch(
            """
            SELECT id, notification_type, severity, subject, target, case_id, created_at, metadata
            FROM notification_events
            WHERE created_at >= NOW() - INTERVAL '7 days'
              AND notification_type LIKE 'decision_quality_%'
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
    items = []
    guided_states = []
    for row in case_rows:
        metadata = _normalize_json_dict(row["metadata"])
        task_items = [
            task
            for task in _normalize_json_list(metadata.get("tasks"))
            if _normalize_json_dict(task).get("status") in {"open", "in_progress"}
        ]
        open_tasks = len(task_items)
        if metadata.get("filing_readiness", {}).get("blocked_count", 0) if isinstance(metadata.get("filing_readiness"), dict) else False:
            pass
        if open_tasks >= 3:
            items.append(
                {
                    "key": f"task_backlog::{row['id']}",
                    "title": f"Task backlog on {row['case_ref']}",
                    "severity": "warning",
                    "source": "case_tasks",
                    "case_id": row["id"],
                    "case_ref": row["case_ref"],
                    "owner": row["assigned_to"],
                    "note": f"{open_tasks} open tasks are still active on this case.",
                    "recommended_action": "review_case_tasks",
                    "deep_link": f"/#case-command?case={row['id']}",
                    "metadata": {"open_tasks": open_tasks},
                }
            )
        if str(row.get("sar_status") or "").lower() == "approved" and not row.get("approved_at"):
            guided_states.append({"state": "approved_without_timestamp", "case_ref": row["case_ref"], "case_id": str(row["id"])})
    for task in (camunda.get("tasks") or [])[: max(4, limit // 2)]:
        items.append(
            {
                "key": f"camunda::{task.get('id')}",
                "title": task.get("name") or "Camunda task",
                "severity": "warning",
                "source": "camunda",
                "case_id": task.get("case_id"),
                "case_ref": task.get("case_ref"),
                "owner": task.get("assignee"),
                "due_at": task.get("created_at"),
                "note": task.get("workflow_label") or "Formal orchestration task needs review.",
                "recommended_action": "open_camunda",
                "deep_link": "/#camunda",
                "metadata": task,
            }
        )
    for row in recent_notifications[: max(4, limit // 2)]:
        items.append(
            {
                "key": f"notification::{row['id']}",
                "title": row["subject"] or row["notification_type"],
                "severity": row["severity"],
                "source": "decision_quality",
                "case_id": row["case_id"],
                "note": (_normalize_json_dict(row["metadata"]).get("message") or row["notification_type"]),
                "recommended_action": "review_quality_recommendation",
                "deep_link": row["target"] or "/#workflow-ops",
                "metadata": _normalize_json_dict(row["metadata"]),
            }
        )
    items = items[:limit]
    counts = {
        "total": len(items),
        "camunda": sum(1 for item in items if item["source"] == "camunda"),
        "task_backlog": sum(1 for item in items if item["source"] == "case_tasks"),
        "decision_quality": sum(1 for item in items if item["source"] == "decision_quality"),
    }
    return {
        "generated_at": _utcnow(),
        "counts": counts,
        "guided_states": guided_states[:10],
        "items": items,
        "summary": [
            f"{counts['total']} workflow exception or intervention item(s) are currently visible.",
            f"{counts['camunda']} Camunda-linked exception(s) are active." if counts["camunda"] else "No Camunda exceptions are active right now.",
        ],
    }


async def run_workflow_exception_action(*, actor: str | None, case_id: str | None, action: str, note: str | None) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        await _record_notification_event(
            conn=conn,
            notification_type="workflow_exception_action",
            channel="app",
            severity="info",
            status="sent",
            subject=f"Workflow exception action - {action.replace('_', ' ')}",
            target=f"/#case-command?case={case_id}" if case_id else "/#workflow-ops",
            case_id=UUID(case_id) if case_id else None,
            metadata={"actor": actor, "action": action, "note": note},
        )
    return {
        "status": "recorded",
        "summary": [f"Recorded workflow exception action {action.replace('_', ' ')}."],
    }


async def get_document_intelligence(document_id: UUID) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM documents WHERE id = $1", document_id)
        if not row:
            return None
        doc = dict(row)
        duplicates = await conn.fetch(
            """
            SELECT id, filename, case_id, entity_id, created_at
            FROM documents
            WHERE checksum = $2 AND id <> $1
            ORDER BY created_at DESC
            LIMIT 8
            """,
            document_id,
            doc.get("checksum"),
        )
        related = await conn.fetch(
            """
            SELECT id, filename, case_id, entity_id, created_at,
                   similarity(coalesce(extracted_text, ''), coalesce($2, '')) AS sim
            FROM documents
            WHERE id <> $1
              AND (
                case_id = $3
                OR entity_id = $4
                OR transaction_id = $5
              )
            ORDER BY sim DESC NULLS LAST, created_at DESC
            LIMIT 8
            """,
            document_id,
            doc.get("extracted_text") or "",
            doc.get("case_id"),
            doc.get("entity_id"),
            doc.get("transaction_id"),
        )
        evidence_rows = await conn.fetch(
            """
            SELECT id, case_id, title, include_in_sar, pinned_at, metadata
            FROM case_evidence
            WHERE evidence_type = 'document'
              AND source_evidence_id = $1::text
            ORDER BY pinned_at DESC
            """,
            str(document_id),
        )
        event_rows = await conn.fetch(
            """
            SELECT case_id, event_type, detail, created_at, metadata
            FROM case_events
            WHERE metadata::text ILIKE '%' || $1 || '%'
            ORDER BY created_at DESC
            LIMIT 12
            """,
            str(document_id),
        )
    duplicate_candidates = [
        {
            "document_id": item["id"],
            "filename": item["filename"],
            "relation": "duplicate_checksum",
            "score": 1.0,
            "case_id": item["case_id"],
            "entity_id": item["entity_id"],
            "created_at": item["created_at"],
            "note": "Exact checksum match",
        }
        for item in duplicates
    ]
    related_documents = [
        {
            "document_id": item["id"],
            "filename": item["filename"],
            "relation": "related_context",
            "score": float(item["sim"]) if item["sim"] is not None else None,
            "case_id": item["case_id"],
            "entity_id": item["entity_id"],
            "created_at": item["created_at"],
            "note": "Shares investigation context or semantic similarity",
        }
        for item in related
    ]
    provenance_trail = [
        {
            "source_type": "case_evidence",
            "source_id": str(item["id"]),
            "label": item["title"],
            "detail": "Pinned as filing evidence" if item["include_in_sar"] else "Pinned as supporting evidence",
            "created_at": item["pinned_at"],
            "metadata": _normalize_json_dict(item["metadata"]),
        }
        for item in evidence_rows
    ] + [
        {
            "source_type": "case_event",
            "source_id": str(item["case_id"]),
            "label": item["event_type"],
            "detail": item["detail"],
            "created_at": item["created_at"],
            "metadata": _normalize_json_dict(item["metadata"]),
        }
        for item in event_rows
    ]
    filing_pack_impact = {
        "linked_case_count": len({str(item["case_id"]) for item in evidence_rows if item["case_id"]}),
        "included_in_sar_count": sum(1 for item in evidence_rows if item["include_in_sar"]),
        "provenance_event_count": len(provenance_trail),
    }
    recommendations = []
    if duplicate_candidates:
        recommendations.append("Review duplicate candidates before attaching this document into additional cases.")
    if not any(item["detail"] == "Pinned as filing evidence" for item in provenance_trail):
        recommendations.append("Pin this document as filing evidence if it materially supports the SAR narrative.")
    return {
        "document_id": document_id,
        "duplicate_candidates": duplicate_candidates,
        "related_documents": related_documents,
        "provenance_trail": provenance_trail[:16],
        "filing_pack_impact": filing_pack_impact,
        "recommendations": recommendations,
        "summary": [
            f"{len(duplicate_candidates)} duplicate candidate(s) and {len(related_documents)} related document(s) were found.",
            f"{filing_pack_impact['included_in_sar_count']} filing-pack inclusion(s) are currently recorded for this document.",
        ],
    }


async def get_entity_network_intelligence(entity_id: UUID) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        entity_row = await conn.fetchrow("SELECT id, name, risk_score FROM entities WHERE id = $1", entity_id)
        if not entity_row:
            return None
        counts = await conn.fetchrow(
            """
            SELECT
              (SELECT COUNT(*) FROM alerts WHERE entity_id = $1) AS connected_alerts,
              (SELECT COUNT(*) FROM documents WHERE entity_id = $1) AS connected_documents,
              (SELECT COUNT(*) FROM screening_results WHERE entity_id = $1 OR lower(entity_name)=lower($2)) AS connected_screening_hits,
              (SELECT COUNT(*) FROM cases WHERE primary_entity_id = $1) AS connected_cases
            """,
            entity_id,
            entity_row["name"],
        )
    graph = await get_graph_drilldown(f"entity:{entity_id}", hops=2, limit=20)
    high_risk_nodes = sum(1 for item in (graph.get("nodes") or []) if float(item.get("risk_score") or 0) >= 0.75)
    risk_score = min(
        0.99,
        round(
            (float(entity_row.get("risk_score") or 0.0) * 0.45)
            + min(high_risk_nodes, 10) * 0.04
            + min(int(counts["connected_screening_hits"] or 0), 6) * 0.05
            + min(int(counts["connected_cases"] or 0), 5) * 0.03,
            3,
        ),
    )
    watch_patterns = []
    if int(counts["connected_screening_hits"] or 0) > 0:
        watch_patterns.append({"pattern": "screening_overlap", "count": int(counts["connected_screening_hits"] or 0)})
    if high_risk_nodes >= 3:
        watch_patterns.append({"pattern": "dense_high_risk_neighbors", "count": high_risk_nodes})
    recommendations = []
    if risk_score >= 0.8:
        recommendations.append(
            {
                "key": "open_network_review",
                "title": "Escalate to network-focused review",
                "severity": "critical",
                "rationale": "This entity is connected to multiple high-risk nodes and supporting investigation activity.",
                "deep_link": f"/#entities",
                "metadata": {"entity_id": str(entity_id)},
            }
        )
    if int(counts["connected_screening_hits"] or 0) > 0:
        recommendations.append(
            {
                "key": "validate_screening_chain",
                "title": "Validate screening chain",
                "severity": "warning",
                "rationale": "Network-linked screening hits suggest the entity should be reviewed with its connected counterparties.",
                "deep_link": "/#screening",
                "metadata": {"entity_id": str(entity_id)},
            }
        )
    return {
        "entity_id": entity_id,
        "network_risk_score": risk_score,
        "connected_high_risk_nodes": high_risk_nodes,
        "connected_alerts": int(counts["connected_alerts"] or 0),
        "connected_cases": int(counts["connected_cases"] or 0),
        "connected_documents": int(counts["connected_documents"] or 0),
        "connected_screening_hits": int(counts["connected_screening_hits"] or 0),
        "watch_patterns": watch_patterns,
        "graph_recommendations": recommendations,
        "summary": [
            f"Network risk score is {risk_score:.2f} with {high_risk_nodes} high-risk connected node(s).",
            f"{int(counts['connected_cases'] or 0)} case link(s) and {int(counts['connected_screening_hits'] or 0)} screening hit(s) were found in the connected entity neighborhood.",
        ],
    }


async def get_model_tuning_summary(days: int = 90) -> dict[str, Any]:
    ops = await get_scorer_model_ops_summary()
    outcomes = await get_scorer_outcome_analytics(days=days)
    report = await get_management_reporting_overview(range_days=max(days, 90), snapshot_scope="manager")
    versions = list(outcomes.get("versions") or [])
    recommendations = []
    current_version = str((ops.get("deployment") or {}).get("runtime", {}).get("model_version") or (ops.get("deployment") or {}).get("deployed_version") or "")
    for item in versions[:5]:
        version = str(item.get("version") or "")
        false_positive_rate = float(item.get("false_positive_rate") or 0.0)
        sar_conversion_rate = float(item.get("sar_conversion_rate") or 0.0)
        if false_positive_rate >= 0.35:
            recommendations.append(
                {
                    "recommendation_key": f"reduce_noise::{version}",
                    "title": f"Reduce noisy scoring posture for version {version}",
                    "severity": "warning",
                    "rationale": f"False-positive rate is {false_positive_rate:.2f}, which is raising analyst workload without corresponding quality gain.",
                    "suggested_version": version,
                    "target_stage": "Staging",
                    "business_impact": {
                        "false_positive_rate": false_positive_rate,
                        "sar_conversion_rate": sar_conversion_rate,
                    },
                    "metadata": {"reason": "false_positive_rate"},
                }
            )
        elif sar_conversion_rate >= 0.12 and version != current_version:
            recommendations.append(
                {
                    "recommendation_key": f"advance_candidate::{version}",
                    "title": f"Advance version {version} for governance review",
                    "severity": "info",
                    "rationale": "This candidate shows stronger SAR conversion posture and is a good handoff candidate for governance review.",
                    "suggested_version": version,
                    "target_stage": "Staging",
                    "business_impact": {
                        "false_positive_rate": false_positive_rate,
                        "sar_conversion_rate": sar_conversion_rate,
                    },
                    "metadata": {"reason": "sar_conversion"},
                }
            )
    handoff_history = []
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, subject, metadata, created_at
            FROM notification_events
            WHERE notification_type = 'model_tuning_handoff'
            ORDER BY created_at DESC
            LIMIT 10
            """
        )
    for row in rows:
        handoff_history.append(
            {
                "id": str(row["id"]),
                "subject": row["subject"],
                "metadata": _normalize_json_dict(row["metadata"]),
                "created_at": row["created_at"],
            }
        )
    summary = [
        f"{len(recommendations)} tuning recommendation(s) are currently active.",
        f"Current deployed scorer version: {current_version or 'unknown'}.",
    ]
    if report.get("decision_quality", {}).get("quality_tuning_recommendations"):
        summary.append("Decision-quality posture is already feeding manager-side tuning recommendations.")
    return {
        "generated_at": _utcnow(),
        "range_days": days,
        "current_version": current_version or None,
        "recommendations": recommendations[:8],
        "handoff_history": handoff_history,
        "summary": summary,
    }


async def submit_model_tuning_handoff(
    *,
    actor: str | None,
    version: str | None,
    recommendation_key: str | None,
    target_stage: str,
    notes: str | None,
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO notification_events (
                notification_type, channel, severity, status, subject, target, metadata
            ) VALUES (
                'model_tuning_handoff', 'app', 'info', 'sent', $1, '/#model-ops', $2::jsonb
            )
            RETURNING id
            """,
            f"Model tuning handoff - {version or 'current scorer'}",
            json.dumps(
                {
                    "actor": actor,
                    "version": version,
                    "recommendation_key": recommendation_key,
                    "target_stage": target_stage,
                    "notes": notes,
                }
            ),
        )
    return {
        "status": "submitted",
        "version": version,
        "recommendation_key": recommendation_key,
        "target_stage": target_stage,
        "notification_id": row["id"] if row else None,
        "summary": ["Submitted the tuning recommendation into the governance handoff lane."],
    }
