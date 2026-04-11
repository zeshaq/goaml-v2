"""
Persistent Neo4j graph sync and query helpers for the AML investigation graph.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from neo4j import AsyncGraphDatabase

from core.config import settings
from core.database import get_pool

_graph_driver = None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _search_text(*parts: Any) -> str:
    values = []
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if text:
            values.append(text.lower())
    return " ".join(values)


def _clean_props(props: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in props.items():
        if value is None:
            continue
        if isinstance(value, (str, bool, int, float)):
            cleaned[key] = value
        elif isinstance(value, datetime):
            cleaned[key] = value.isoformat()
        elif isinstance(value, list):
            cleaned[key] = [item for item in value if isinstance(item, (str, bool, int, float))]
    return cleaned


async def get_graph_driver():
    global _graph_driver
    if _graph_driver is None:
        _graph_driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _graph_driver


async def close_graph_driver() -> None:
    global _graph_driver
    if _graph_driver is not None:
        await _graph_driver.close()
        _graph_driver = None


async def ensure_graph_schema() -> None:
    driver = await get_graph_driver()
    async with driver.session() as session:
        result = await session.run(
            "CREATE CONSTRAINT graph_node_uid IF NOT EXISTS FOR (n:GraphNode) REQUIRE n.uid IS UNIQUE"
        )
        await result.consume()
        result = await session.run(
            "CREATE INDEX graph_node_search IF NOT EXISTS FOR (n:GraphNode) ON (n.search_text)"
        )
        await result.consume()


def _node_uid(kind: str, value: Any) -> str:
    return f"{kind}:{value}"


def _build_graph_snapshot(rows: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}

    def add_node(uid: str, node_type: str, display_label: str, **props: Any) -> None:
        payload = {
            "uid": uid,
            "source_id": str(props.pop("source_id", uid.split(":", 1)[-1])),
            "node_type": node_type,
            "display_label": display_label,
            **_clean_props(props),
        }
        payload["search_text"] = _search_text(
            display_label,
            payload.get("source_id"),
            payload.get("account_number"),
            payload.get("account_name"),
            payload.get("name"),
            payload.get("title"),
            payload.get("ref"),
            payload.get("filename"),
            payload.get("dataset"),
            payload.get("matched_name"),
            payload.get("entity_name"),
        )
        if uid in nodes:
            current = nodes[uid]
            current.update({k: v for k, v in payload.items() if v is not None})
        else:
            nodes[uid] = payload

    def add_edge(source_uid: str, target_uid: str, label: str, **props: Any) -> None:
        key = (source_uid, target_uid, label)
        payload = {
            "source_uid": source_uid,
            "target_uid": target_uid,
            "label": label,
            "props": _clean_props(props),
        }
        edges[key] = payload

    account_name_map: dict[str, str] = {}

    for row in rows["accounts"]:
        uid = _node_uid("account", row["id"])
        label = row.get("account_number") or row.get("account_name") or str(row["id"])
        add_node(
            uid,
            "account",
            label,
            source_id=row["id"],
            account_number=row.get("account_number"),
            account_name=row.get("account_name"),
            country=row.get("country"),
            risk_level=row.get("risk_level"),
            risk_score=_safe_float(row.get("risk_score")),
        )
        account_name_map[str(row["id"])] = label

    entity_name_lookup: dict[str, str] = {}
    for row in rows["entities"]:
        uid = _node_uid("entity", row["id"])
        label = row.get("name") or str(row["id"])
        add_node(
            uid,
            "entity",
            label,
            source_id=row["id"],
            name=row.get("name"),
            entity_type=row.get("entity_type"),
            country=row.get("country"),
            nationality=row.get("nationality"),
            is_pep=bool(row.get("is_pep")),
            is_sanctioned=bool(row.get("is_sanctioned")),
            risk_level=row.get("risk_level"),
            risk_score=_safe_float(row.get("risk_score")),
        )
        entity_name_lookup[str(row.get("name") or "").strip().lower()] = uid

    for row in rows["transactions"]:
        uid = _node_uid("transaction", row["id"])
        add_node(
            uid,
            "transaction",
            row.get("transaction_ref") or str(row["id"]),
            source_id=row["id"],
            ref=row.get("transaction_ref"),
            status=row.get("status"),
            sender_name=row.get("sender_name"),
            receiver_name=row.get("receiver_name"),
            risk_level=row.get("risk_level"),
            risk_score=_safe_float(row.get("risk_score")),
            amount_usd=_safe_float(row.get("amount_usd")),
            transacted_at=_as_iso(row.get("transacted_at")),
        )
        if row.get("sender_account_id"):
            add_edge(uid, _node_uid("account", row["sender_account_id"]), "sent_from")
        if row.get("receiver_account_id"):
            add_edge(uid, _node_uid("account", row["receiver_account_id"]), "sent_to")

    for row in rows["alerts"]:
        uid = _node_uid("alert", row["id"])
        add_node(
            uid,
            "alert",
            row.get("alert_ref") or str(row["id"]),
            source_id=row["id"],
            ref=row.get("alert_ref"),
            title=row.get("title"),
            alert_type=row.get("alert_type"),
            severity=row.get("severity"),
            status=row.get("status"),
        )
        if row.get("transaction_id"):
            add_edge(uid, _node_uid("transaction", row["transaction_id"]), "flags")
        if row.get("account_id"):
            add_edge(uid, _node_uid("account", row["account_id"]), "targets_account")
        if row.get("entity_id"):
            add_edge(uid, _node_uid("entity", row["entity_id"]), "targets_entity")
        if row.get("case_id"):
            add_edge(uid, _node_uid("case", row["case_id"]), "belongs_to_case")

    for row in rows["cases"]:
        uid = _node_uid("case", row["id"])
        add_node(
            uid,
            "case",
            row.get("case_ref") or str(row["id"]),
            source_id=row["id"],
            ref=row.get("case_ref"),
            title=row.get("title"),
            status=row.get("status"),
            priority=row.get("priority"),
            assigned_to=row.get("assigned_to"),
            ai_summary=row.get("ai_summary"),
        )
        if row.get("primary_account_id"):
            add_edge(uid, _node_uid("account", row["primary_account_id"]), "focuses_on_account")
        if row.get("primary_entity_id"):
            add_edge(uid, _node_uid("entity", row["primary_entity_id"]), "focuses_on_entity")
        if row.get("sar_id"):
            add_edge(uid, _node_uid("sar", row["sar_id"]), "has_sar")

    for row in rows["account_entities"]:
        add_edge(
            _node_uid("account", row["account_id"]),
            _node_uid("entity", row["entity_id"]),
            "related_entity",
            role=row.get("role"),
            since=_as_iso(row.get("since")),
        )

    for row in rows["case_transactions"]:
        add_edge(
            _node_uid("case", row["case_id"]),
            _node_uid("transaction", row["transaction_id"]),
            "contains_transaction",
            added_at=_as_iso(row.get("added_at")),
        )

    tx_case_map: dict[str, list[str]] = {}
    for row in rows["case_transactions"]:
        tx_case_map.setdefault(str(row["transaction_id"]), []).append(str(row["case_id"]))

    for row in rows["case_alerts"]:
        add_edge(
            _node_uid("case", row["case_id"]),
            _node_uid("alert", row["alert_id"]),
            "contains_alert",
            added_at=_as_iso(row.get("added_at")),
        )

    for row in rows["documents"]:
        uid = _node_uid("document", row["id"])
        add_node(
            uid,
            "document",
            row.get("filename") or str(row["id"]),
            source_id=row["id"],
            filename=row.get("filename"),
            file_type=row.get("file_type"),
            uploaded_by=row.get("uploaded_by"),
            storage_path=row.get("storage_path"),
            pii_detected=bool(row.get("pii_detected")),
            parse_applied=bool(row.get("parse_applied")),
            embedded=bool(row.get("embedded")),
            created_at=_as_iso(row.get("created_at")),
        )
        if row.get("case_id"):
            add_edge(_node_uid("case", row["case_id"]), uid, "has_document")
        if row.get("entity_id"):
            add_edge(uid, _node_uid("entity", row["entity_id"]), "relates_to_entity")
        if row.get("transaction_id"):
            add_edge(uid, _node_uid("transaction", row["transaction_id"]), "relates_to_transaction")

    for row in rows["sar_reports"]:
        uid = _node_uid("sar", row["id"])
        add_node(
            uid,
            "sar",
            row.get("sar_ref") or str(row["id"]),
            source_id=row["id"],
            ref=row.get("sar_ref"),
            status=row.get("status"),
            filing_ref=row.get("filing_ref"),
            ai_drafted=bool(row.get("ai_drafted")),
            ai_model=row.get("ai_model"),
            filed_at=_as_iso(row.get("filed_at")),
        )
        if row.get("case_id"):
            add_edge(_node_uid("case", row["case_id"]), uid, "has_sar")

    for row in rows["screening_results"]:
        uid = _node_uid("screening_hit", row["id"])
        matched_name = row.get("matched_name") or row.get("entity_name") or str(row["id"])
        add_node(
            uid,
            "screening_hit",
            matched_name,
            source_id=row["id"],
            entity_name=row.get("entity_name"),
            matched_name=row.get("matched_name"),
            dataset=row.get("dataset"),
            match_type=row.get("match_type"),
            matched_country=row.get("matched_country"),
            match_score=_safe_float(row.get("match_score")),
            created_at=_as_iso(row.get("created_at")),
        )
        if row.get("entity_id"):
            add_edge(_node_uid("entity", row["entity_id"]), uid, "matched_on_screening")
        else:
            candidate = entity_name_lookup.get(str(row.get("entity_name") or "").strip().lower()) or entity_name_lookup.get(
                str(row.get("matched_name") or "").strip().lower()
            )
            if candidate:
                add_edge(candidate, uid, "matched_on_screening")
        if row.get("linked_txn_id"):
            add_edge(uid, _node_uid("transaction", row["linked_txn_id"]), "linked_to_transaction")
            for case_id in tx_case_map.get(str(row["linked_txn_id"]), []):
                add_edge(_node_uid("case", case_id), uid, "investigates_screening_hit")

    table_counts = {key: len(value) for key, value in rows.items()}
    return list(nodes.values()), list(edges.values()), table_counts


async def _fetch_snapshot_from_postgres() -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = {
            "accounts": [dict(row) for row in await conn.fetch("SELECT id, account_number, account_name, country, risk_level, risk_score FROM accounts")],
            "entities": [dict(row) for row in await conn.fetch("SELECT id, name, entity_type, country, nationality, is_pep, is_sanctioned, risk_level, risk_score FROM entities")],
            "account_entities": [dict(row) for row in await conn.fetch("SELECT account_id, entity_id, role, since FROM account_entities")],
            "transactions": [dict(row) for row in await conn.fetch("SELECT id, transaction_ref, status, sender_account_id, receiver_account_id, sender_name, receiver_name, risk_level, risk_score, amount_usd, transacted_at FROM transactions")],
            "alerts": [dict(row) for row in await conn.fetch("SELECT id, alert_ref, alert_type, severity, status, title, transaction_id, account_id, entity_id, case_id FROM alerts")],
            "cases": [dict(row) for row in await conn.fetch("SELECT id, case_ref, title, status, priority, assigned_to, primary_account_id, primary_entity_id, sar_id, ai_summary FROM cases")],
            "case_transactions": [dict(row) for row in await conn.fetch("SELECT case_id, transaction_id, added_at FROM case_transactions")],
            "case_alerts": [dict(row) for row in await conn.fetch("SELECT case_id, alert_id, added_at FROM case_alerts")],
            "screening_results": [dict(row) for row in await conn.fetch("SELECT id, entity_id, entity_name, matched_name, match_score, dataset, match_type, matched_country, linked_txn_id, created_at FROM screening_results")],
            "documents": [dict(row) for row in await conn.fetch("SELECT id, filename, file_type, case_id, entity_id, transaction_id, uploaded_by, storage_path, pii_detected, parse_applied, embedded, created_at FROM documents")],
            "sar_reports": [dict(row) for row in await conn.fetch("SELECT id, sar_ref, case_id, status, filing_ref, filed_at, ai_drafted, ai_model FROM sar_reports")],
        }
    return _build_graph_snapshot(rows)


async def sync_graph_from_postgres(clear_existing: bool = True) -> dict[str, Any]:
    await ensure_graph_schema()
    nodes, edges, table_counts = await _fetch_snapshot_from_postgres()
    driver = await get_graph_driver()

    async with driver.session() as session:
        if clear_existing:
            result = await session.run("MATCH (n:GraphNode) DETACH DELETE n")
            await result.consume()

        result = await session.run(
            """
            UNWIND $rows AS row
            MERGE (n:GraphNode {uid: row.uid})
            SET n += row
            """,
            rows=nodes,
        )
        await result.consume()

        result = await session.run(
            """
            UNWIND $rows AS row
            MATCH (source:GraphNode {uid: row.source_uid})
            MATCH (target:GraphNode {uid: row.target_uid})
            MERGE (source)-[rel:RELATED {source_uid: row.source_uid, target_uid: row.target_uid, label: row.label}]->(target)
            SET rel += row.props
            """,
            rows=edges,
        )
        await result.consume()

    return {
        "status": "ok",
        "clear_existing": clear_existing,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "table_counts": table_counts,
        "synced_at": datetime.utcnow().isoformat() + "Z",
    }


async def safe_resync_graph(clear_existing: bool = True) -> dict[str, Any] | None:
    try:
        return await sync_graph_from_postgres(clear_existing=clear_existing)
    except Exception:
        return None


def _node_row_to_payload(record: Any) -> dict[str, Any]:
    props = dict(record["props"] or {})
    metadata = {
        key: value
        for key, value in props.items()
        if key not in {"uid", "source_id", "node_type", "display_label", "search_text", "risk_score"}
    }
    return {
        "id": record["id"],
        "label": record["label"],
        "node_type": record["node_type"],
        "risk_score": _safe_float(record["risk_score"]),
        "metadata": metadata,
    }


def _edge_row_to_payload(record: Any) -> dict[str, Any]:
    return {
        "source": record["source"],
        "target": record["target"],
        "label": record["label"],
        "metadata": {
            key: value
            for key, value in dict(record["props"] or {}).items()
            if key not in {"source_uid", "target_uid", "label"}
        },
    }


def _graph_type_summary(nodes: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    for node in nodes:
        node_type = node.get("node_type") or "node"
        counts[node_type] = counts.get(node_type, 0) + 1

    order = [
        "case",
        "alert",
        "transaction",
        "account",
        "entity",
        "document",
        "screening_hit",
        "sar",
    ]
    labels = {
        "case": "case",
        "alert": "alert",
        "transaction": "transaction",
        "account": "account",
        "entity": "entity",
        "document": "document",
        "screening_hit": "screening hit",
        "sar": "sar",
    }
    summary: list[str] = []
    for node_type in order:
        count = counts.get(node_type, 0)
        if count:
            label = labels.get(node_type, node_type.replace("_", " "))
            if count == 1:
                summary.append(f"{count} {label} in graph")
            elif label.endswith("y"):
                summary.append(f"{count} {label[:-1]}ies in graph")
            else:
                summary.append(f"{count} {label}s in graph")
    return summary or ["0 graph nodes returned"]


async def _resolve_graph_focus_node(node_id: str) -> dict[str, Any] | None:
    await ensure_graph_schema()
    driver = await get_graph_driver()
    lowered = str(node_id or "").strip().lower()
    if not lowered:
        return None

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n:GraphNode)
            WHERE n.uid = $node_id
               OR n.source_id = $node_id
               OR toLower(n.display_label) = $lowered
            RETURN n.uid AS id,
                   n.display_label AS label,
                   n.node_type AS node_type,
                   n.risk_score AS risk_score,
                   properties(n) AS props
            ORDER BY
              CASE
                WHEN n.uid = $node_id THEN 0
                WHEN n.source_id = $node_id THEN 1
                ELSE 2
              END,
              coalesce(n.risk_score, 0.0) DESC,
              n.display_label ASC
            LIMIT 1
            """,
            node_id=node_id,
            lowered=lowered,
        )
        record = await result.single()
        if record:
            return _node_row_to_payload(record)

        result = await session.run(
            """
            MATCH (n:GraphNode)
            WHERE n.search_text CONTAINS $lowered
            RETURN n.uid AS id,
                   n.display_label AS label,
                   n.node_type AS node_type,
                   n.risk_score AS risk_score,
                   properties(n) AS props
            ORDER BY coalesce(n.risk_score, 0.0) DESC, n.display_label ASC
            LIMIT 1
            """,
            lowered=lowered,
        )
        record = await result.single()
        return _node_row_to_payload(record) if record else None


async def _resolve_graph_target_candidates(target_query: str, limit: int) -> list[dict[str, Any]]:
    await ensure_graph_schema()
    driver = await get_graph_driver()
    lowered = str(target_query or "").strip().lower()
    if not lowered:
        return []

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n:GraphNode)
            WHERE n.search_text CONTAINS $lowered
            RETURN n.uid AS id,
                   n.display_label AS label,
                   n.node_type AS node_type,
                   n.risk_score AS risk_score,
                   properties(n) AS props
            ORDER BY coalesce(n.risk_score, 0.0) DESC, n.display_label ASC
            LIMIT $limit
            """,
            lowered=lowered,
            limit=limit,
        )
        rows = [record async for record in result]
    return [_node_row_to_payload(record) for record in rows]


async def query_persisted_graph(query: str, hops: int = 2, limit: int = 30) -> dict[str, Any]:
    await ensure_graph_schema()
    driver = await get_graph_driver()
    lowered = str(query or "").strip().lower()
    if not lowered:
        return {
            "query": query,
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "summary": ["0 cases in graph", "0 alerts in graph", "0 transactions in graph", "0 sanctions hits in graph"],
        }

    hop_count = max(1, min(int(hops), 4))
    node_limit = max(limit * max(1, hop_count) * 6, limit)
    edge_limit = max(limit * max(1, hop_count) * 8, limit)
    node_query = f"""
            MATCH (seed:GraphNode)
            WHERE seed.uid IN $seed_uids
            OPTIONAL MATCH p=(seed)-[*0..{hop_count}]-(node:GraphNode)
            WITH collect(DISTINCT seed) + collect(DISTINCT node) AS raw_nodes
            UNWIND raw_nodes AS node
            WITH DISTINCT node
            WHERE node IS NOT NULL
            RETURN node.uid AS id,
                   node.display_label AS label,
                   node.node_type AS node_type,
                   node.risk_score AS risk_score,
                   properties(node) AS props
            LIMIT $node_limit
            """
    edge_query = f"""
            MATCH (seed:GraphNode)
            WHERE seed.uid IN $seed_uids
            OPTIONAL MATCH p=(seed)-[*1..{hop_count}]-(node:GraphNode)
            UNWIND relationships(p) AS rel
            WITH DISTINCT rel
            RETURN rel.source_uid AS source,
                   rel.target_uid AS target,
                   coalesce(rel.label, 'related') AS label,
                   properties(rel) AS props
            LIMIT $edge_limit
            """

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n:GraphNode)
            WHERE n.search_text CONTAINS $search_query
            RETURN n.uid AS uid
            ORDER BY coalesce(n.risk_score, 0.0) DESC, n.display_label ASC
            LIMIT $limit
            """,
            search_query=lowered,
            limit=limit,
        )
        seed_uids = [record["uid"] async for record in result]
        if not seed_uids:
            return {
                "query": query,
                "node_count": 0,
                "edge_count": 0,
                "nodes": [],
                "edges": [],
                "summary": ["0 cases in graph", "0 alerts in graph", "0 transactions in graph", "0 sanctions hits in graph"],
            }

        result = await session.run(
            node_query,
            seed_uids=seed_uids,
            node_limit=node_limit,
        )
        node_rows = [record async for record in result]

        result = await session.run(
            edge_query,
            seed_uids=seed_uids,
            edge_limit=edge_limit,
        )
        edge_rows = [record async for record in result]

    nodes = [_node_row_to_payload(record) for record in node_rows]
    edges = [_edge_row_to_payload(record) for record in edge_rows if record["source"] and record["target"]]
    summary = _graph_type_summary(nodes)

    return {
        "query": query,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "summary": summary,
    }


async def get_graph_drilldown(node_id: str, hops: int = 1, limit: int = 25) -> dict[str, Any]:
    focus_node = await _resolve_graph_focus_node(node_id)
    if not focus_node:
        return {
            "focus_node": None,
            "node_count": 0,
            "edge_count": 0,
            "nodes": [],
            "edges": [],
            "relationship_evidence": [],
            "summary": [f'No graph node found for "{node_id}"'],
        }

    await ensure_graph_schema()
    driver = await get_graph_driver()
    hop_count = max(1, min(int(hops), 3))
    node_limit = max(limit * max(1, hop_count) * 6, limit)
    edge_limit = max(limit * max(1, hop_count) * 8, limit)

    node_query = f"""
            MATCH (focus:GraphNode {{uid: $focus_uid}})
            OPTIONAL MATCH p=(focus)-[*0..{hop_count}]-(node:GraphNode)
            WITH collect(DISTINCT focus) + collect(DISTINCT node) AS raw_nodes
            UNWIND raw_nodes AS node
            WITH DISTINCT node
            WHERE node IS NOT NULL
            RETURN node.uid AS id,
                   node.display_label AS label,
                   node.node_type AS node_type,
                   node.risk_score AS risk_score,
                   properties(node) AS props
            LIMIT $node_limit
            """
    edge_query = f"""
            MATCH (focus:GraphNode {{uid: $focus_uid}})
            OPTIONAL MATCH p=(focus)-[*1..{hop_count}]-(node:GraphNode)
            UNWIND relationships(p) AS rel
            WITH DISTINCT rel
            RETURN rel.source_uid AS source,
                   rel.target_uid AS target,
                   coalesce(rel.label, 'related') AS label,
                   properties(rel) AS props
            LIMIT $edge_limit
            """

    async with driver.session() as session:
        result = await session.run(node_query, focus_uid=focus_node["id"], node_limit=node_limit)
        node_rows = [record async for record in result]

        result = await session.run(edge_query, focus_uid=focus_node["id"], edge_limit=edge_limit)
        edge_rows = [record async for record in result]

    nodes = [_node_row_to_payload(record) for record in node_rows]
    edges = [_edge_row_to_payload(record) for record in edge_rows if record["source"] and record["target"]]
    node_lookup = {node["id"]: node for node in nodes}

    focus_id = focus_node["id"]
    def evidence_rank(item: dict[str, Any]) -> tuple[int, float, str]:
        touches_focus = 0 if item["source_id"] == focus_id or item["target_id"] == focus_id else 1
        counterparty = item if item["source_id"] != focus_id else {
            "target_type": item["target_type"],
            "target_label": item["target_label"],
        }
        counterparty_type = counterparty.get("target_type") or counterparty.get("source_type") or ""
        type_rank = {
            "account": 0,
            "entity": 1,
            "transaction": 2,
            "alert": 3,
            "screening_hit": 4,
            "document": 5,
            "sar": 6,
            "case": 7,
        }.get(counterparty_type, 8)
        related_node = node_lookup.get(item["target_id"]) or node_lookup.get(item["source_id"]) or {}
        risk = related_node.get("risk_score") or 0.0
        label = item["target_label"] if item["target_id"] != focus_id else item["source_label"]
        return (touches_focus, type_rank, -(risk or 0.0), label or "")

    relationship_evidence: list[dict[str, Any]] = []
    for edge in edges:
        source_node = node_lookup.get(edge["source"])
        target_node = node_lookup.get(edge["target"])
        if not source_node or not target_node:
            continue
        relationship_evidence.append(
            {
                "source_id": source_node["id"],
                "source_label": source_node["label"],
                "source_type": source_node["node_type"],
                "target_id": target_node["id"],
                "target_label": target_node["label"],
                "target_type": target_node["node_type"],
                "label": edge["label"],
                "metadata": edge["metadata"],
            }
        )
    relationship_evidence = sorted(relationship_evidence, key=evidence_rank)[:limit]

    summary = [f'Focus: {focus_node["label"]} ({focus_node["node_type"]})']
    summary.extend(_graph_type_summary(nodes))
    if relationship_evidence:
        summary.append(f"{len(relationship_evidence)} relationship evidence items ready for drill-down")

    return {
        "focus_node": focus_node,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": nodes,
        "edges": edges,
        "relationship_evidence": relationship_evidence,
        "summary": summary,
    }


async def find_graph_paths(
    source_node_id: str,
    target_node_id: str | None = None,
    target_query: str | None = None,
    max_hops: int = 4,
    limit: int = 5,
) -> dict[str, Any]:
    source_node = await _resolve_graph_focus_node(source_node_id)
    if not source_node:
        return {
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "target_query": target_query,
            "path_count": 0,
            "paths": [],
            "summary": [f'No source graph node found for "{source_node_id}"'],
        }

    target_candidates: list[dict[str, Any]] = []
    if target_node_id:
        resolved = await _resolve_graph_focus_node(target_node_id)
        if resolved:
            target_candidates = [resolved]
    elif target_query:
        target_candidates = await _resolve_graph_target_candidates(target_query, max(limit * 3, limit))

    target_candidates = [
        candidate
        for candidate in target_candidates
        if candidate["id"] != source_node["id"]
    ]
    if not target_candidates:
        return {
            "source_node_id": source_node["id"],
            "target_node_id": target_node_id,
            "target_query": target_query,
            "path_count": 0,
            "paths": [],
            "summary": [f'No target graph nodes found for "{target_query or target_node_id or ""}"'],
        }

    await ensure_graph_schema()
    driver = await get_graph_driver()
    hop_count = max(1, min(int(max_hops), 5))
    path_query = f"""
            MATCH (source:GraphNode {{uid: $source_uid}})
            MATCH (target:GraphNode)
            WHERE target.uid IN $target_uids AND target.uid <> source.uid
            MATCH p = shortestPath((source)-[:RELATED*..{hop_count}]-(target))
            RETURN target.uid AS target_uid,
                   [node IN nodes(p) | {{
                       id: node.uid,
                       label: node.display_label,
                       node_type: node.node_type,
                       risk_score: node.risk_score,
                       props: properties(node)
                   }}] AS nodes,
                   [rel IN relationships(p) | {{
                       source: rel.source_uid,
                       target: rel.target_uid,
                       label: coalesce(rel.label, 'related'),
                       props: properties(rel)
                   }}] AS edges,
                   length(p) AS hops
            ORDER BY hops ASC, target.display_label ASC
            LIMIT $limit
            """

    async with driver.session() as session:
        result = await session.run(
            path_query,
            source_uid=source_node["id"],
            target_uids=[candidate["id"] for candidate in target_candidates],
            limit=limit,
        )
        path_rows = [record async for record in result]

    paths: list[dict[str, Any]] = []
    for record in path_rows:
        path_nodes = [
            _node_row_to_payload(
                {
                    "id": item.get("id"),
                    "label": item.get("label"),
                    "node_type": item.get("node_type"),
                    "risk_score": item.get("risk_score"),
                    "props": item.get("props") or {},
                }
            )
            for item in record["nodes"] or []
        ]
        path_edges = [
            _edge_row_to_payload(
                {
                    "source": item.get("source"),
                    "target": item.get("target"),
                    "label": item.get("label"),
                    "props": item.get("props") or {},
                }
            )
            for item in record["edges"] or []
            if item.get("source") and item.get("target")
        ]
        paths.append(
            {
                "hops": int(record["hops"] or 0),
                "nodes": path_nodes,
                "edges": path_edges,
            }
        )

    summary = [f'Source: {source_node["label"]} ({source_node["node_type"]})']
    if target_query:
        summary.append(f'Target search: "{target_query}"')
    if paths:
        summary.append(f"Found {len(paths)} path{'s' if len(paths) != 1 else ''} within {hop_count} hops")
        shortest = min(path["hops"] for path in paths)
        summary.append(f"Shortest path length: {shortest} hop{'s' if shortest != 1 else ''}")
    else:
        summary.append(f"No path found within {hop_count} hops")

    return {
        "source_node_id": source_node["id"],
        "target_node_id": target_candidates[0]["id"] if target_node_id and target_candidates else target_node_id,
        "target_query": target_query,
        "path_count": len(paths),
        "paths": paths,
        "summary": summary,
    }
