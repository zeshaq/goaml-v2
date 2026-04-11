"""
Shared case evidence grounding for AI summaries, SAR drafting, and filing packs.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from core.database import get_pool
from services.case_context import get_case_context


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


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any, *, limit: int = 320) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split()).strip()
    if not text:
        return None
    return text[:limit]


def _dedupe_key(item: dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("evidence_type") or ""),
            str(item.get("source_evidence_id") or ""),
            str(item.get("title") or ""),
        ]
    )


async def _fetch_case_evidence_rows(case_id: UUID) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM case_evidence
            WHERE case_id = $1
            ORDER BY include_in_sar DESC, importance DESC, updated_at DESC, pinned_at DESC
            """,
            case_id,
        )
    items: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["metadata"] = _normalize_json_dict(item.get("metadata"))
        items.append(item)
    return items


def _pinned_item(row: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(row.get("metadata") or {})
    metadata.setdefault("case_evidence_id", str(row.get("id")))
    if row.get("pinned_by"):
        metadata.setdefault("pinned_by", row.get("pinned_by"))
    if row.get("pinned_at"):
        metadata.setdefault("pinned_at", str(row.get("pinned_at")))
    if row.get("updated_at"):
        metadata.setdefault("updated_at", str(row.get("updated_at")))
    return {
        "evidence_type": str(row.get("evidence_type") or "pinned_evidence"),
        "title": str(row.get("title") or "Pinned evidence"),
        "summary": _clean_text(row.get("summary")),
        "source": row.get("source") or "case_evidence",
        "source_evidence_id": str(row.get("source_evidence_id") or row.get("id") or ""),
        "importance": int(row.get("importance") or 50),
        "include_in_sar": bool(row.get("include_in_sar")),
        "metadata": metadata,
    }


def _alert_item(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_type": "alert",
        "title": str(row.get("alert_ref") or row.get("title") or "Linked alert"),
        "summary": _clean_text(
            " | ".join(
                part
                for part in [
                    row.get("title"),
                    f"severity={row.get('severity')}" if row.get("severity") else None,
                    f"status={row.get('status')}" if row.get("status") else None,
                    row.get("description"),
                ]
                if part
            )
        ),
        "source": "linked_alert",
        "source_evidence_id": str(row.get("id") or row.get("alert_ref") or ""),
        "importance": 72 if str(row.get("severity") or "").lower() in {"high", "critical"} else 60,
        "include_in_sar": str(row.get("severity") or "").lower() in {"high", "critical"},
        "metadata": {
            "alert_ref": row.get("alert_ref"),
            "severity": row.get("severity"),
            "status": row.get("status"),
        },
    }


def _transaction_item(row: dict[str, Any]) -> dict[str, Any]:
    amount = _safe_float(row.get("amount_usd"))
    return {
        "evidence_type": "transaction",
        "title": str(row.get("transaction_ref") or "Linked transaction"),
        "summary": _clean_text(
            " | ".join(
                part
                for part in [
                    f"amount_usd={amount:,.2f}" if amount is not None else None,
                    f"risk_score={row.get('risk_score')}" if row.get("risk_score") is not None else None,
                    f"sender={row.get('sender_name')}" if row.get("sender_name") else None,
                    f"receiver={row.get('receiver_name')}" if row.get("receiver_name") else None,
                    f"transacted_at={row.get('transacted_at')}" if row.get("transacted_at") else None,
                ]
                if part
            )
        ),
        "source": "linked_transaction",
        "source_evidence_id": str(row.get("id") or row.get("transaction_ref") or ""),
        "importance": 78 if (row.get("risk_score") or 0) >= 0.75 else 64,
        "include_in_sar": (row.get("risk_score") or 0) >= 0.65,
        "metadata": {
            "transaction_ref": row.get("transaction_ref"),
            "amount_usd": amount,
            "risk_score": _safe_float(row.get("risk_score")),
        },
    }


def _screening_item(row: dict[str, Any]) -> dict[str, Any]:
    score = _safe_float(row.get("match_score"))
    return {
        "evidence_type": "screening_hit",
        "title": str(row.get("matched_name") or row.get("entity_name") or "Screening hit"),
        "summary": _clean_text(
            " | ".join(
                part
                for part in [
                    f"entity={row.get('entity_name')}" if row.get("entity_name") else None,
                    f"dataset={row.get('dataset')}" if row.get("dataset") else None,
                    f"match_type={row.get('match_type')}" if row.get("match_type") else None,
                    f"score={score}" if score is not None else None,
                ]
                if part
            )
        ),
        "source": "screening",
        "source_evidence_id": str(row.get("id") or ""),
        "importance": 88 if score and score >= 0.85 else 74,
        "include_in_sar": True,
        "metadata": {
            "entity_name": row.get("entity_name"),
            "matched_name": row.get("matched_name"),
            "dataset": row.get("dataset"),
            "match_type": row.get("match_type"),
            "match_score": score,
        },
    }


def _document_item(row: dict[str, Any], *, direct: bool) -> dict[str, Any]:
    metadata = dict(row.get("metadata") or {})
    if row.get("document_id"):
        metadata.setdefault("document_id", str(row.get("document_id")))
    if row.get("retrieval_score") is not None:
        metadata.setdefault("retrieval_score", _safe_float(row.get("retrieval_score")))
    if row.get("rerank_score") is not None:
        metadata.setdefault("rerank_score", _safe_float(row.get("rerank_score")))
    return {
        "evidence_type": "document",
        "title": str(row.get("filename") or "Document evidence"),
        "summary": _clean_text(row.get("snippet") or "Document evidence retrieved for this case."),
        "source": row.get("source") or ("direct_document" if direct else "retrieved_document"),
        "source_evidence_id": str(row.get("document_id") or row.get("filename") or ""),
        "importance": 76 if direct else 62,
        "include_in_sar": direct,
        "metadata": metadata,
    }


def _graph_item(summary_text: str, index: int) -> dict[str, Any]:
    return {
        "evidence_type": "graph_summary",
        "title": f"Graph finding {index + 1}",
        "summary": _clean_text(summary_text),
        "source": "graph_context",
        "source_evidence_id": f"graph-summary-{index + 1}",
        "importance": 58,
        "include_in_sar": False,
        "metadata": {"graph_summary": True},
    }


def _context_candidates(context: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for row in context.get("alerts", [])[:6]:
        candidates.append(_alert_item(row))
    for row in context.get("transactions", [])[:8]:
        candidates.append(_transaction_item(row))
    for row in context.get("screening_hits", [])[:6]:
        candidates.append(_screening_item(row))
    for row in context.get("direct_documents", [])[:6]:
        candidates.append(_document_item(row, direct=True))
    for row in context.get("related_documents", [])[:6]:
        candidates.append(_document_item(row, direct=False))
    for index, summary_text in enumerate((context.get("graph") or {}).get("summary") or []):
        candidates.append(_graph_item(summary_text, index))
    return candidates


async def build_case_grounding(
    case_id: UUID,
    *,
    context: dict[str, Any] | None = None,
    prioritize_pinned_evidence: bool = True,
    filing_only: bool = False,
    limit: int = 8,
) -> dict[str, Any]:
    context_data = context or await get_case_context(case_id, document_limit=4, related_limit=6)
    pinned_rows = await _fetch_case_evidence_rows(case_id)

    pinned_items = [_pinned_item(row) for row in pinned_rows]
    pinned_filing_items = [item for item in pinned_items if item.get("include_in_sar")]
    context_items = _context_candidates(context_data or {})

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_pinned = False
    used_context = False

    def add_items(items: list[dict[str, Any]]) -> None:
        nonlocal used_pinned, used_context
        for item in items:
            if len(selected) >= limit:
                break
            key = _dedupe_key(item)
            if key in seen:
                continue
            selected.append(item)
            seen.add(key)
            if item.get("source") == "case_evidence":
                used_pinned = True
            else:
                used_context = True

    if filing_only:
        add_items(pinned_filing_items)
        add_items([item for item in pinned_items if _dedupe_key(item) not in seen])
        add_items([item for item in context_items if item.get("include_in_sar")])
        add_items(context_items)
    elif prioritize_pinned_evidence:
        add_items(pinned_items)
        add_items(context_items)
    else:
        add_items(context_items)
        add_items(pinned_items)

    if filing_only and pinned_filing_items:
        grounding_mode = "filing_evidence_priority" if not used_context else "filing_evidence_plus_context"
    elif used_pinned and used_context:
        grounding_mode = "pinned_plus_context"
    elif used_pinned:
        grounding_mode = "pinned_evidence_priority"
    else:
        grounding_mode = "context_fallback"

    return {
        "grounding_mode": grounding_mode,
        "used_evidence": selected[:limit],
        "pinned_evidence_count": len(pinned_items),
        "filing_evidence_count": len(pinned_filing_items),
    }
