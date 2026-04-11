"""
Entity profile, watchlist, and merge-resolution services for the analyst workspace.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from core.database import get_pool
from services.graph_sync import get_graph_drilldown, safe_resync_graph

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
        counts_row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE coalesce(metadata->'watchlist_state'->>'status', '') = 'active')::int AS active,
                COUNT(*) FILTER (WHERE coalesce(metadata->'watchlist_state'->>'status', '') = 'removed')::int AS removed,
                COUNT(*) FILTER (
                    WHERE coalesce(metadata->'watchlist_state'->>'status', '') = 'active'
                      AND EXISTS (
                          SELECT 1
                          FROM cases c
                          WHERE c.primary_entity_id = entities.id
                            AND coalesce(c.metadata->>'entity_workflow', '') = 'watchlist_review'
                            AND c.status <> 'closed'
                      )
                )::int AS with_open_case,
                COUNT(*) FILTER (
                    WHERE coalesce(metadata->'watchlist_state'->>'status', '') = 'active'
                        AND risk_level = 'critical'
                )::int AS critical,
                COUNT(*) FILTER (WHERE coalesce(metadata->'watchlist_state'->>'status', '') <> '')::int AS total
            FROM entities
            WHERE coalesce(metadata->>'resolution_status', '') <> 'merged'
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
        item["risk_score"] = float(item["risk_score"]) if item.get("risk_score") is not None else None
        item["resolution_status"] = _resolution_status_from_metadata(metadata)
        item["watchlist_status"] = watchlist_state.get("status")
        item["watchlist_source"] = watchlist_state.get("source")
        item["watchlist_reason"] = watchlist_state.get("reason")
        item["watchlist_added_by"] = watchlist_state.get("added_by")
        item["watchlist_added_at"] = watchlist_state.get("added_at")
        items.append(item)

    return {"status": status_key, "counts": dict(counts_row or {}), "items": items}


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

    if watchlist_case_row:
        watchlist_state.setdefault("status", "active")
        watchlist_state["case_id"] = watchlist_case_row["id"]
        watchlist_state["case_ref"] = watchlist_case_row["case_ref"]

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
    case_metadata = {
        "entity_workflow": "watchlist_review",
        "linked_entity_id": str(entity_row["id"]),
        "watchlist_reason": watchlist_reason,
        "watchlist_source": watchlist_state.get("source") or "internal",
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
        actor,
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
    return await get_entity_profile(profile_entity_id)
