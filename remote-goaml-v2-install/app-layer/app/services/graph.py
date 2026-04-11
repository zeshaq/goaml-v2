"""
Analyst-facing graph exploration built from the live AML relational data.
"""

from __future__ import annotations

from typing import Any

from core.database import get_pool
from services.graph_sync import query_persisted_graph


def _node_id(kind: str, value: Any) -> str:
    return f"{kind}:{value}"


async def _explore_graph_relational(query: str, hops: int = 2, limit: int = 30) -> dict[str, Any]:
    pool = get_pool()
    q = f"%{query.lower()}%"

    nodes: dict[str, dict[str, Any]] = {}
    edges: dict[tuple[str, str, str], dict[str, Any]] = {}
    seed_accounts: set[str] = set()
    seed_transactions: set[str] = set()
    seed_alerts: set[str] = set()
    seed_cases: set[str] = set()
    seed_entities: set[str] = set()
    summary: list[str] = []

    def add_node(node_id: str, label: str, node_type: str, risk_score: float | None = None, metadata: dict[str, Any] | None = None) -> None:
        current = nodes.get(node_id)
        if current is None:
            nodes[node_id] = {
                "id": node_id,
                "label": label,
                "node_type": node_type,
                "risk_score": risk_score,
                "metadata": metadata or {},
            }
            return
        if risk_score is not None and current.get("risk_score") is None:
            current["risk_score"] = risk_score
        if metadata:
            current["metadata"].update(metadata)

    def add_edge(source: str, target: str, label: str, metadata: dict[str, Any] | None = None) -> None:
        key = (source, target, label)
        if key not in edges:
            edges[key] = {
                "source": source,
                "target": target,
                "label": label,
                "metadata": metadata or {},
            }

    async with pool.acquire() as conn:
        accounts = await conn.fetch(
            """
            SELECT id, account_number, account_name, risk_score, country
            FROM accounts
            WHERE lower(account_number) LIKE $1 OR lower(coalesce(account_name, '')) LIKE $1
            ORDER BY risk_score DESC NULLS LAST, created_at DESC
            LIMIT $2
            """,
            q,
            limit,
        )
        for row in accounts:
            node = _node_id("account", row["id"])
            seed_accounts.add(str(row["id"]))
            add_node(
                node,
                row["account_number"] or row["account_name"] or str(row["id"]),
                "account",
                float(row["risk_score"]) if row["risk_score"] is not None else None,
                {"country": row["country"]},
            )

        entities = await conn.fetch(
            """
            SELECT id, name, entity_type, risk_score, is_sanctioned, country
            FROM entities
            WHERE lower(name) LIKE $1
            ORDER BY is_sanctioned DESC, risk_score DESC NULLS LAST, created_at DESC
            LIMIT $2
            """,
            q,
            limit,
        )
        for row in entities:
            node = _node_id("entity", row["id"])
            seed_entities.add(str(row["id"]))
            add_node(
                node,
                row["name"],
                "entity",
                float(row["risk_score"]) if row["risk_score"] is not None else None,
                {"entity_type": row["entity_type"], "country": row["country"], "is_sanctioned": row["is_sanctioned"]},
            )

        txns = await conn.fetch(
            """
            SELECT id, transaction_ref, sender_account_id, receiver_account_id, amount_usd, risk_score
            FROM transactions
            WHERE lower(transaction_ref) LIKE $1
               OR lower(coalesce(sender_name, '')) LIKE $1
               OR lower(coalesce(receiver_name, '')) LIKE $1
               OR lower(coalesce(sender_account_ref, '')) LIKE $1
               OR lower(coalesce(receiver_account_ref, '')) LIKE $1
            ORDER BY transacted_at DESC
            LIMIT $2
            """,
            q,
            limit,
        )
        for row in txns:
            node = _node_id("transaction", row["id"])
            seed_transactions.add(str(row["id"]))
            add_node(
                node,
                row["transaction_ref"],
                "transaction",
                float(row["risk_score"]) if row["risk_score"] is not None else None,
                {"amount_usd": float(row["amount_usd"]) if row["amount_usd"] is not None else None},
            )
            if row["sender_account_id"]:
                account_node = _node_id("account", row["sender_account_id"])
                seed_accounts.add(str(row["sender_account_id"]))
                add_node(account_node, "Sender account", "account")
                add_edge(account_node, node, "sent")
            if row["receiver_account_id"]:
                account_node = _node_id("account", row["receiver_account_id"])
                seed_accounts.add(str(row["receiver_account_id"]))
                add_node(account_node, "Receiver account", "account")
                add_edge(node, account_node, "received_by")

        alerts = await conn.fetch(
            """
            SELECT id, alert_ref, title, severity, status, transaction_id, account_id, entity_id, case_id
            FROM alerts
            WHERE lower(alert_ref) LIKE $1 OR lower(title) LIKE $1 OR lower(coalesce(description, '')) LIKE $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            q,
            limit,
        )
        for row in alerts:
            node = _node_id("alert", row["id"])
            seed_alerts.add(str(row["id"]))
            add_node(node, row["alert_ref"], "alert", None, {"title": row["title"], "severity": row["severity"], "status": row["status"]})
            if row["transaction_id"]:
                add_node(_node_id("transaction", row["transaction_id"]), "Linked transaction", "transaction")
                add_edge(node, _node_id("transaction", row["transaction_id"]), "flags")
                seed_transactions.add(str(row["transaction_id"]))
            if row["account_id"]:
                add_node(_node_id("account", row["account_id"]), "Linked account", "account")
                add_edge(node, _node_id("account", row["account_id"]), "targets")
                seed_accounts.add(str(row["account_id"]))
            if row["entity_id"]:
                add_node(_node_id("entity", row["entity_id"]), "Linked entity", "entity")
                add_edge(node, _node_id("entity", row["entity_id"]), "targets")
                seed_entities.add(str(row["entity_id"]))
            if row["case_id"]:
                add_node(_node_id("case", row["case_id"]), "Linked case", "case")
                add_edge(node, _node_id("case", row["case_id"]), "belongs_to")
                seed_cases.add(str(row["case_id"]))

        cases = await conn.fetch(
            """
            SELECT id, case_ref, title, status, priority, primary_account_id, primary_entity_id
            FROM cases
            WHERE lower(case_ref) LIKE $1 OR lower(title) LIKE $1 OR lower(coalesce(description, '')) LIKE $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            q,
            limit,
        )
        for row in cases:
            node = _node_id("case", row["id"])
            seed_cases.add(str(row["id"]))
            add_node(node, row["case_ref"], "case", None, {"title": row["title"], "status": row["status"], "priority": row["priority"]})
            if row["primary_account_id"]:
                add_node(_node_id("account", row["primary_account_id"]), "Primary account", "account")
                add_edge(node, _node_id("account", row["primary_account_id"]), "focuses_on")
                seed_accounts.add(str(row["primary_account_id"]))
            if row["primary_entity_id"]:
                add_node(_node_id("entity", row["primary_entity_id"]), "Primary entity", "entity")
                add_edge(node, _node_id("entity", row["primary_entity_id"]), "focuses_on")
                seed_entities.add(str(row["primary_entity_id"]))

        if seed_accounts:
            rows = await conn.fetch(
                """
                SELECT ae.account_id, ae.entity_id, ae.role, e.name, e.entity_type, e.is_sanctioned, e.risk_score
                FROM account_entities ae
                JOIN entities e ON e.id = ae.entity_id
                WHERE ae.account_id = ANY($1::uuid[])
                LIMIT $2
                """,
                list(seed_accounts),
                limit * max(1, hops),
            )
            for row in rows:
                account_node = _node_id("account", row["account_id"])
                entity_node = _node_id("entity", row["entity_id"])
                add_node(entity_node, row["name"], "entity", float(row["risk_score"]) if row["risk_score"] is not None else None, {"entity_type": row["entity_type"], "is_sanctioned": row["is_sanctioned"]})
                add_edge(account_node, entity_node, row["role"] or "related_to")

        if seed_cases:
            rows = await conn.fetch(
                """
                SELECT ct.case_id, ct.transaction_id, t.transaction_ref, t.amount_usd, t.risk_score
                FROM case_transactions ct
                JOIN transactions t ON t.id = ct.transaction_id
                WHERE ct.case_id = ANY($1::uuid[])
                LIMIT $2
                """,
                list(seed_cases),
                limit * max(1, hops),
            )
            for row in rows:
                case_node = _node_id("case", row["case_id"])
                txn_node = _node_id("transaction", row["transaction_id"])
                add_node(txn_node, row["transaction_ref"], "transaction", float(row["risk_score"]) if row["risk_score"] is not None else None, {"amount_usd": float(row["amount_usd"]) if row["amount_usd"] is not None else None})
                add_edge(case_node, txn_node, "contains")

            rows = await conn.fetch(
                """
                SELECT ca.case_id, ca.alert_id, a.alert_ref, a.severity, a.status
                FROM case_alerts ca
                JOIN alerts a ON a.id = ca.alert_id
                WHERE ca.case_id = ANY($1::uuid[])
                LIMIT $2
                """,
                list(seed_cases),
                limit * max(1, hops),
            )
            for row in rows:
                case_node = _node_id("case", row["case_id"])
                alert_node = _node_id("alert", row["alert_id"])
                add_node(alert_node, row["alert_ref"], "alert", None, {"severity": row["severity"], "status": row["status"]})
                add_edge(case_node, alert_node, "contains")

        if seed_entities:
            rows = await conn.fetch(
                """
                SELECT id, entity_name, matched_name, dataset, matched_country, created_at
                FROM screening_results
                WHERE entity_id = ANY($1::uuid[])
                   OR lower(entity_name) LIKE $2
                ORDER BY created_at DESC
                LIMIT $3
                """,
                list(seed_entities),
                q,
                limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, entity_name, matched_name, dataset, matched_country, created_at
                FROM screening_results
                WHERE lower(entity_name) LIKE $1 OR lower(coalesce(matched_name, '')) LIKE $1
                ORDER BY created_at DESC
                LIMIT $2
                """,
                q,
                limit,
            )
        for row in rows:
            matched_name = row["matched_name"] or row["entity_name"]
            sanction_node = _node_id("sanction_hit", row["id"])
            add_node(
                sanction_node,
                matched_name,
                "sanction_hit",
                None,
                {"dataset": row["dataset"], "matched_country": row["matched_country"], "created_at": row["created_at"].isoformat()},
            )
            for entity_node in [node_id for node_id, node in nodes.items() if node["node_type"] == "entity" and query.lower() in node["label"].lower()]:
                add_edge(entity_node, sanction_node, "matched_on_screening")
            for case_node, node in nodes.items():
                if node["node_type"] == "case" and query.lower() in str(node.get("metadata", {}).get("title", "")).lower():
                    add_edge(case_node, sanction_node, "investigates")

    if not edges and len(nodes) > 1:
        non_hit_nodes = [node["id"] for node in nodes.values() if node["node_type"] != "sanction_hit"]
        hit_nodes = [node["id"] for node in nodes.values() if node["node_type"] == "sanction_hit"]
        if non_hit_nodes and hit_nodes:
            anchor = non_hit_nodes[0]
            for hit in hit_nodes[: min(len(hit_nodes), 5)]:
                add_edge(anchor, hit, "related_match")

    summary.append(f"{len([n for n in nodes.values() if n['node_type'] == 'case'])} cases in graph")
    summary.append(f"{len([n for n in nodes.values() if n['node_type'] == 'alert'])} alerts in graph")
    summary.append(f"{len([n for n in nodes.values() if n['node_type'] == 'transaction'])} transactions in graph")
    summary.append(f"{len([n for n in nodes.values() if n['node_type'] == 'sanction_hit'])} sanctions hits in graph")

    return {
        "query": query,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "nodes": list(nodes.values()),
        "edges": list(edges.values()),
        "summary": summary,
    }


async def explore_graph(query: str, hops: int = 2, limit: int = 30) -> dict[str, Any]:
    try:
        data = await query_persisted_graph(query, hops=hops, limit=limit)
        if data.get("node_count"):
            return data
    except Exception:
        pass
    return await _explore_graph_relational(query, hops=hops, limit=limit)
