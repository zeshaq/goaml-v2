"""
Case investigation context built from linked records, vector retrieval, reranking,
screening, and graph expansion.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import httpx

from core.config import settings
from core.database import get_pool
from services.graph import explore_graph

EMBED_MODEL = "llama-nemotron-embed-1b-v2"
RERANK_MODEL = "llama-nemotron-rerank-1b-v2"
MILVUS_COLLECTION = "document_chunks"


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def _api_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


def _normalize_document_row(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("structured_data", "pii_entities", "metadata"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                row[key] = json.loads(value)
            except Exception:
                row[key] = {}
        elif value is None:
            row[key] = {}
    if row.get("embedding_ids") is None:
        row["embedding_ids"] = []
    return row


def _document_item(
    row: dict[str, Any] | None,
    *,
    source: str,
    snippet: str | None = None,
    retrieval_score: float | None = None,
    rerank_score: float | None = None,
    embedding_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    row = row or {}
    text = snippet or row.get("extracted_text") or ""
    compact = " ".join(str(text).split())
    return {
        "document_id": row.get("id"),
        "filename": filename or row.get("filename") or "Retrieved evidence",
        "source": source,
        "snippet": compact[:320] if compact else None,
        "created_at": row.get("created_at"),
        "case_id": row.get("case_id"),
        "entity_id": row.get("entity_id"),
        "transaction_id": row.get("transaction_id"),
        "ocr_applied": row.get("ocr_applied"),
        "parse_applied": row.get("parse_applied"),
        "pii_detected": row.get("pii_detected"),
        "embedded": row.get("embedded"),
        "retrieval_score": retrieval_score,
        "rerank_score": rerank_score,
        "embedding_id": embedding_id,
        "metadata": metadata or {},
    }


def _build_retrieval_query(
    case_row: dict[str, Any],
    alerts: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    primary_entity_name: str | None,
    primary_account_label: str | None,
) -> tuple[str, list[str], str]:
    focus_queries: list[str] = []
    for value in (
        primary_entity_name,
        primary_account_label,
        case_row.get("case_ref"),
        *[row.get("alert_ref") for row in alerts[:3]],
        *[row.get("transaction_ref") for row in transactions[:3]],
    ):
        if value and value not in focus_queries:
            focus_queries.append(str(value))

    lines: list[str] = []
    for value in (
        case_row.get("case_ref"),
        case_row.get("title"),
        case_row.get("description"),
        case_row.get("ai_summary"),
        primary_entity_name,
        primary_account_label,
    ):
        if value:
            lines.append(str(value))

    for alert in alerts[:5]:
        lines.append(
            " | ".join(
                [
                    str(alert.get("alert_ref") or ""),
                    str(alert.get("severity") or ""),
                    str(alert.get("title") or ""),
                    str(alert.get("description") or ""),
                ]
            ).strip(" |")
        )

    for txn in transactions[:8]:
        lines.append(
            " | ".join(
                [
                    str(txn.get("transaction_ref") or ""),
                    str(txn.get("sender_name") or ""),
                    str(txn.get("receiver_name") or ""),
                    str(txn.get("amount_usd") or ""),
                ]
            ).strip(" |")
        )

    retrieval_query = "\n".join(line for line in lines if line).strip()[:6000]
    display_query = " | ".join(focus_queries[:4]) if focus_queries else str(case_row.get("case_ref") or case_row.get("title") or "case")
    graph_query = str(primary_entity_name or primary_account_label or case_row.get("case_ref") or case_row.get("title") or display_query)
    return retrieval_query, focus_queries, graph_query


async def _embed_text(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            _api_url(settings.EMBED_URL, "/embeddings"),
            json={"model": EMBED_MODEL, "input": text[:8000]},
        )
        resp.raise_for_status()
        data = resp.json()
    return data["data"][0]["embedding"]


def _milvus_search_sync(vector: list[float], limit: int) -> list[dict[str, Any]]:
    from pymilvus import Collection, connections, utility

    connections.connect(alias="default", host=settings.MILVUS_HOST, port=str(settings.MILVUS_PORT))
    if not utility.has_collection(MILVUS_COLLECTION):
        return []

    collection = Collection(MILVUS_COLLECTION)
    collection.load()
    results = collection.search(
        data=[vector],
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {}},
        limit=limit,
        output_fields=["document_label", "content"],
    )

    hits: list[dict[str, Any]] = []
    for hit in results[0]:
        entity = getattr(hit, "entity", None)
        if entity is not None and hasattr(entity, "get"):
            label = entity.get("document_label")
            content = entity.get("content")
        else:
            label = None
            content = None

        hits.append(
            {
                "embedding_id": str(getattr(hit, "id", None) or ""),
                "retrieval_score": _safe_float(getattr(hit, "score", None) or getattr(hit, "distance", None)),
                "filename": label,
                "content": content,
            }
        )
    return hits


async def _retrieve_vector_hits(query_text: str, limit: int) -> list[dict[str, Any]]:
    if not query_text.strip():
        return []
    try:
        vector = await _embed_text(query_text)
        return await asyncio.to_thread(_milvus_search_sync, vector, limit)
    except Exception:
        return []


async def _rerank_documents(query_text: str, documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not query_text.strip() or not documents:
        return documents

    doc_texts = [doc.get("snippet") or "" for doc in documents]
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                _api_url(settings.RERANK_URL, "/rerank"),
                json={"model": RERANK_MODEL, "query": query_text[:4000], "documents": doc_texts},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return sorted(documents, key=lambda item: item.get("retrieval_score") or 0.0, reverse=True)

    scores: dict[int, float] = {}
    for item in data.get("results", []):
        index = item.get("index")
        if isinstance(index, int):
            scores[index] = _safe_float(item.get("relevance_score")) or 0.0

    ranked: list[dict[str, Any]] = []
    for index, doc in enumerate(documents):
        doc["rerank_score"] = scores.get(index)
        ranked.append(doc)

    return sorted(
        ranked,
        key=lambda item: (
            item.get("rerank_score") is not None,
            item.get("rerank_score") or 0.0,
            item.get("retrieval_score") or 0.0,
        ),
        reverse=True,
    )


async def _fetch_direct_documents(
    conn: Any,
    case_id: UUID,
    transaction_ids: list[UUID],
    primary_entity_id: UUID | None,
    limit: int,
) -> list[dict[str, Any]]:
    args: list[Any] = [case_id]
    conditions = ["case_id = $1"]
    if transaction_ids:
        args.append(transaction_ids)
        conditions.append(f"transaction_id = ANY(${len(args)}::uuid[])")
    if primary_entity_id:
        args.append(primary_entity_id)
        conditions.append(f"entity_id = ${len(args)}")

    args.append(limit)
    rows = await conn.fetch(
        f"""
        SELECT *
        FROM documents
        WHERE {" OR ".join(conditions)}
        ORDER BY created_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    return [_normalize_document_row(dict(row)) for row in rows]


async def _fetch_screening_hits(
    conn: Any,
    primary_entity_id: UUID | None,
    transaction_ids: list[UUID],
    entity_names: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    args: list[Any] = []
    conditions: list[str] = []

    if primary_entity_id:
        args.append(primary_entity_id)
        conditions.append(f"entity_id = ${len(args)}")
    if transaction_ids:
        args.append(transaction_ids)
        conditions.append(f"linked_txn_id = ANY(${len(args)}::uuid[])")
    if entity_names:
        args.append([name.lower() for name in entity_names])
        conditions.append(f"lower(entity_name) = ANY(${len(args)}::text[])")

    if not conditions:
        return []

    args.append(limit)
    rows = await conn.fetch(
        f"""
        SELECT *
        FROM screening_results
        WHERE {" OR ".join(conditions)}
        ORDER BY match_score DESC NULLS LAST, created_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    results = [dict(row) for row in rows]
    for row in results:
        row["matched_detail"] = _normalize_json_dict(row.get("matched_detail"))
        row["match_score"] = _safe_float(row.get("match_score"))
    return results


async def _map_vector_hits_to_documents(
    conn: Any,
    vector_hits: list[dict[str, Any]],
    exclude_ids: set[str],
    limit: int,
) -> list[dict[str, Any]]:
    vector_ids = [hit["embedding_id"] for hit in vector_hits if hit.get("embedding_id")]
    if not vector_ids:
        return []

    rows = await conn.fetch(
        """
        SELECT *
        FROM documents
        WHERE embedding_ids && $1::text[]
        ORDER BY created_at DESC
        """,
        vector_ids,
    )
    docs = [_normalize_document_row(dict(row)) for row in rows]

    embedding_map: dict[str, dict[str, Any]] = {}
    for row in docs:
        for embedding_id in row.get("embedding_ids", []):
            if embedding_id in vector_ids and embedding_id not in embedding_map:
                embedding_map[embedding_id] = row

    results: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set(exclude_ids)

    for hit in vector_hits:
        embedding_id = hit.get("embedding_id")
        mapped = embedding_map.get(embedding_id or "")
        if mapped is not None:
            doc_id = str(mapped.get("id"))
            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            results.append(
                _document_item(
                    mapped,
                    source="semantic_retrieval",
                    snippet=hit.get("content"),
                    retrieval_score=_safe_float(hit.get("retrieval_score")),
                    embedding_id=embedding_id,
                    metadata={"match_type": "vector_search"},
                )
            )
        else:
            results.append(
                _document_item(
                    None,
                    source="semantic_retrieval",
                    filename=hit.get("filename"),
                    snippet=hit.get("content"),
                    retrieval_score=_safe_float(hit.get("retrieval_score")),
                    embedding_id=embedding_id,
                    metadata={"match_type": "vector_search", "unmapped": True},
                )
            )
        if len(results) >= limit:
            break

    return results


def _build_summary(
    alerts: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    screening_hits: list[dict[str, Any]],
    direct_documents: list[dict[str, Any]],
    related_documents: list[dict[str, Any]],
    graph: dict[str, Any] | None,
) -> list[str]:
    summary: list[str] = []

    if alerts:
        summary.append(f"{len(alerts)} linked alerts are already attached to this case.")
    if transactions:
        total = sum(_safe_float(txn.get("amount_usd")) or 0.0 for txn in transactions)
        summary.append(f"{len(transactions)} linked transactions total about ${total:,.0f}.")
    if screening_hits:
        top_hit = screening_hits[0]
        matched_name = top_hit.get("matched_name") or top_hit.get("entity_name") or "matched party"
        dataset = top_hit.get("dataset") or "sanctions source"
        summary.append(f"{len(screening_hits)} screening hits found; strongest hit is {matched_name} from {dataset}.")
    if direct_documents:
        summary.append(f"{len(direct_documents)} documents are directly linked to the case, transactions, or primary entity.")
    if related_documents:
        if any(doc.get("rerank_score") is not None for doc in related_documents):
            summary.append(f"{len(related_documents)} semantically related documents were retrieved from Milvus and reranked.")
        else:
            summary.append(f"{len(related_documents)} semantically related documents were retrieved from Milvus.")
    if graph:
        summary.append(f"Graph expansion returned {graph.get('node_count', 0)} nodes and {graph.get('edge_count', 0)} edges.")
    if not summary:
        summary.append("No linked evidence has been attached yet; semantic retrieval may still provide context once more documents are indexed.")
    return summary


async def get_case_context(case_id: UUID, document_limit: int = 4, related_limit: int = 6) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        case_row = await conn.fetchrow("SELECT * FROM cases WHERE id = $1", case_id)
        if not case_row:
            return None

        alerts = [
            dict(row)
            for row in await conn.fetch(
                """
                SELECT a.id, a.alert_ref, a.title, a.severity, a.status, a.description, a.created_at
                FROM case_alerts ca
                JOIN alerts a ON a.id = ca.alert_id
                WHERE ca.case_id = $1
                ORDER BY a.created_at DESC
                LIMIT 20
                """,
                case_id,
            )
        ]
        transactions = [
            dict(row)
            for row in await conn.fetch(
                """
                SELECT t.id, t.transaction_ref, t.amount_usd, t.risk_score, t.status,
                       t.sender_name, t.receiver_name, t.transacted_at
                FROM case_transactions ct
                JOIN transactions t ON t.id = ct.transaction_id
                WHERE ct.case_id = $1
                ORDER BY t.transacted_at DESC NULLS LAST, t.created_at DESC
                LIMIT 20
                """,
                case_id,
            )
        ]

        primary_entity_name = None
        if case_row["primary_entity_id"]:
            primary_entity_name = await conn.fetchval(
                "SELECT name FROM entities WHERE id = $1",
                case_row["primary_entity_id"],
            )

        primary_account_label = None
        if case_row["primary_account_id"]:
            primary_account_label = await conn.fetchval(
                "SELECT COALESCE(account_number, account_name, id::text) FROM accounts WHERE id = $1",
                case_row["primary_account_id"],
            )

        linked_entity_names = [str(primary_entity_name)] if primary_entity_name else []
        extra_entity_rows = await conn.fetch(
            """
            SELECT DISTINCT e.name
            FROM case_alerts ca
            JOIN alerts a ON a.id = ca.alert_id
            JOIN entities e ON e.id = a.entity_id
            WHERE ca.case_id = $1
            LIMIT 10
            """,
            case_id,
        )
        for row in extra_entity_rows:
            name = row["name"]
            if name and name not in linked_entity_names:
                linked_entity_names.append(str(name))

        transaction_ids = [row["id"] for row in transactions]
        direct_document_rows = await _fetch_direct_documents(
            conn,
            case_id,
            transaction_ids,
            case_row["primary_entity_id"],
            max(document_limit * 3, document_limit),
        )
        direct_documents = [
            _document_item(row, source="direct_link", metadata={"match_type": "direct_link"})
            for row in direct_document_rows[:document_limit]
        ]

        screening_hits = await _fetch_screening_hits(
            conn,
            case_row["primary_entity_id"],
            transaction_ids,
            linked_entity_names,
            related_limit,
        )

        retrieval_query, focus_queries, graph_query = _build_retrieval_query(
            dict(case_row),
            alerts,
            transactions,
            primary_entity_name,
            primary_account_label,
        )

        vector_hits = await _retrieve_vector_hits(retrieval_query, max(related_limit * 3, related_limit))
        related_documents = await _map_vector_hits_to_documents(
            conn,
            vector_hits,
            {str(item["document_id"]) for item in direct_documents if item.get("document_id")},
            max(related_limit * 2, related_limit),
        )

    related_documents = await _rerank_documents(retrieval_query, related_documents)
    related_documents = related_documents[:related_limit]

    graph: dict[str, Any] | None = None
    try:
        graph = await explore_graph(graph_query, hops=2, limit=20)
    except Exception:
        graph = None

    return {
        "case_id": case_id,
        "query": graph_query,
        "focus_queries": focus_queries,
        "summary": _build_summary(
            alerts=alerts,
            transactions=transactions,
            screening_hits=screening_hits,
            direct_documents=direct_documents,
            related_documents=related_documents,
            graph=graph,
        ),
        "alerts": alerts,
        "transactions": [
            {
                **row,
                "amount_usd": _safe_float(row.get("amount_usd")),
                "risk_score": _safe_float(row.get("risk_score")),
            }
            for row in transactions
        ],
        "screening_hits": screening_hits,
        "direct_documents": direct_documents,
        "related_documents": related_documents,
        "graph": graph,
    }
