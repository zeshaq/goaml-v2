"""
LLM-backed case summary generation using the investigation context service.
"""

from __future__ import annotations

import json
import re
from typing import Any
from uuid import UUID

import httpx

from core.config import settings
from core.database import get_pool
from services.case_context import get_case_context
from services.cases import get_case_detail
from services.graph_sync import safe_resync_graph


def _api_url(base_url: str, path: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return f"{base}{path}"
    return f"{base}/v1{path}"


def _first_json_object(text: str) -> dict[str, Any] | None:
    text = str(text or "").strip()
    if not text:
        return None

    candidates = [text]
    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    candidates.extend(fenced)

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _normalize_risk_factors(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:8]
    if isinstance(value, str):
        lines = [
            re.sub(r"^[\-\*\d\.\)\s]+", "", item).strip()
            for item in value.splitlines()
            if item.strip()
        ]
        return lines[:8]
    return []


def _fallback_case_summary(case_detail: dict[str, Any], context: dict[str, Any]) -> tuple[str, list[str], str, bool]:
    transactions = context.get("transactions", [])
    alerts = context.get("alerts", [])
    screening_hits = context.get("screening_hits", [])
    documents = context.get("direct_documents", []) + context.get("related_documents", [])
    graph = context.get("graph") or {}

    lines: list[str] = []
    title = case_detail.get("title") or case_detail.get("case_ref") or "this case"
    status = case_detail.get("status") or "open"
    priority = case_detail.get("priority") or "medium"
    lines.append(f"{title} is currently a {priority} priority case in {status} status.")

    if transactions:
        total = sum(float(item.get("amount_usd") or 0) for item in transactions)
        lines.append(
            f"The case currently includes {len(transactions)} linked transaction{'s' if len(transactions) != 1 else ''} totaling about ${total:,.0f}."
        )
    if alerts:
        severe = [a for a in alerts if str(a.get('severity') or '').lower() in {'high', 'critical'}]
        lines.append(
            f"{len(alerts)} linked alert{'s are' if len(alerts) != 1 else ' is'} attached"
            + (f", including {len(severe)} high-severity indicators." if severe else ".")
        )
    if screening_hits:
        top = screening_hits[0]
        matched = top.get("matched_name") or top.get("entity_name") or "a matched party"
        lines.append(f"Screening evidence includes a match involving {matched}.")
    if documents:
        lines.append(f"{len(documents)} linked or retrieved document{'s were' if len(documents) != 1 else ' was'} pulled into the investigation context.")
    if graph.get("node_count"):
        lines.append(f"Graph expansion surfaced {graph.get('node_count', 0)} connected nodes for additional investigation context.")

    risk_factors: list[str] = []
    if transactions:
        risk_factors.append("Large or unusual transaction activity is linked to the case.")
    if alerts:
        risk_factors.append("Alert evidence has already escalated the case into analyst review.")
    if screening_hits:
        risk_factors.append("Sanctions or watchlist screening produced related matches that require analyst review.")
    if documents:
        risk_factors.append("Supporting documents contain extracted evidence that may corroborate the suspicious activity pattern.")
    if graph.get("edge_count"):
        risk_factors.append("Graph relationships connect the case to additional entities or transactions that may expand investigative scope.")

    summary = " ".join(lines) if lines else "This case is open for AML analyst review."
    return summary, risk_factors[:5], "template-v1", False


def _build_case_summary_prompt(case_detail: dict[str, Any], context: dict[str, Any]) -> str:
    tx_lines = [
        " | ".join(
            [
                f"ref={item.get('transaction_ref')}",
                f"amount_usd={item.get('amount_usd')}",
                f"risk_score={item.get('risk_score')}",
                f"sender={item.get('sender_name') or 'unknown'}",
                f"receiver={item.get('receiver_name') or 'unknown'}",
                f"transacted_at={item.get('transacted_at')}",
            ]
        )
        for item in context.get("transactions", [])[:8]
    ]
    alert_lines = [
        " | ".join(
            [
                f"ref={item.get('alert_ref')}",
                f"severity={item.get('severity')}",
                f"title={item.get('title')}",
                f"status={item.get('status')}",
            ]
        )
        for item in context.get("alerts", [])[:8]
    ]
    screening_lines = [
        " | ".join(
            [
                f"entity={item.get('entity_name')}",
                f"match={item.get('matched_name')}",
                f"dataset={item.get('dataset')}",
                f"score={item.get('match_score')}",
            ]
        )
        for item in context.get("screening_hits", [])[:6]
    ]
    document_lines = [
        " | ".join(
            [
                f"filename={item.get('filename')}",
                f"source={item.get('source')}",
                f"rerank={item.get('rerank_score')}",
                f"vector={item.get('retrieval_score')}",
                f"snippet={item.get('snippet')}",
            ]
        )
        for item in (context.get("direct_documents", []) + context.get("related_documents", []))[:8]
    ]
    graph_summary = context.get("graph", {}).get("summary") or []

    return (
        "Generate an AML case summary for an analyst workbench.\n\n"
        f"Case ref: {case_detail.get('case_ref')}\n"
        f"Title: {case_detail.get('title')}\n"
        f"Status: {case_detail.get('status')}\n"
        f"Priority: {case_detail.get('priority')}\n"
        f"Assigned analyst: {case_detail.get('assigned_to') or 'unassigned'}\n"
        f"Context focus terms: {', '.join(context.get('focus_queries') or []) or context.get('query')}\n\n"
        "Context summary bullets:\n"
        f"{chr(10).join(context.get('summary') or ['None'])}\n\n"
        "Linked alerts:\n"
        f"{chr(10).join(alert_lines) if alert_lines else 'None'}\n\n"
        "Linked transactions:\n"
        f"{chr(10).join(tx_lines) if tx_lines else 'None'}\n\n"
        "Screening hits:\n"
        f"{chr(10).join(screening_lines) if screening_lines else 'None'}\n\n"
        "Relevant documents:\n"
        f"{chr(10).join(document_lines) if document_lines else 'None'}\n\n"
        "Graph summary:\n"
        f"{chr(10).join(graph_summary) if graph_summary else 'None'}\n\n"
        "Return valid JSON with this exact shape:\n"
        '{\n'
        '  "summary": "2-4 sentences in a concise, factual AML investigation tone",\n'
        '  "risk_factors": ["short factor 1", "short factor 2", "short factor 3"]\n'
        '}\n'
        "Do not wrap the JSON in markdown. Do not invent facts beyond the supplied case context."
    )


async def generate_case_summary(
    case_id: UUID,
    *,
    generated_by: str | None = None,
    persist: bool = True,
    document_limit: int = 4,
    related_limit: int = 6,
) -> dict[str, Any] | None:
    case_detail = await get_case_detail(case_id)
    if not case_detail:
        return None

    context = await get_case_context(case_id, document_limit=document_limit, related_limit=related_limit)
    if not context:
        return None

    fallback_summary, fallback_risk_factors, fallback_model, fallback_ai = _fallback_case_summary(case_detail, context)
    model_name = settings.LLM_PRIMARY_MODEL
    ai_generated = False
    summary_text = fallback_summary
    risk_factors = fallback_risk_factors

    body = {
        "model": model_name,
        "temperature": 0.2,
        "max_tokens": 500,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You generate concise AML investigation summaries for analysts. "
                    "Stay factual, mention suspicious patterns and corroborating evidence, and keep the tone operational."
                ),
            },
            {"role": "user", "content": _build_case_summary_prompt(case_detail, context)},
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
            resp = await client.post(_api_url(settings.LLM_PRIMARY_URL, "/chat/completions"), json=body)
            resp.raise_for_status()
            data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        parsed = _first_json_object(content)
        if parsed:
            parsed_summary = str(parsed.get("summary") or "").strip()
            parsed_risk_factors = _normalize_risk_factors(parsed.get("risk_factors"))
            if parsed_summary:
                summary_text = parsed_summary
                risk_factors = parsed_risk_factors or fallback_risk_factors
                ai_generated = True
        if not ai_generated and str(content).strip():
            summary_text = str(content).strip()
            ai_generated = True
            risk_factors = fallback_risk_factors
    except Exception:
        model_name = fallback_model
        ai_generated = fallback_ai

    if persist:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE cases
                    SET ai_summary = $2, ai_risk_factors = $3, updated_at = NOW()
                    WHERE id = $1
                    """,
                    case_id,
                    summary_text,
                    risk_factors,
                )
                await conn.execute(
                    """
                    INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                    VALUES ($1, 'ai_summary_generated', $2, $3, $4)
                    """,
                    case_id,
                    generated_by,
                    "AI case summary generated",
                    json.dumps(
                        {
                            "model": model_name,
                            "ai_generated": ai_generated,
                            "risk_factor_count": len(risk_factors),
                        }
                    ),
                )
        await safe_resync_graph(clear_existing=True)

    return {
        "case_id": case_id,
        "summary": summary_text,
        "risk_factors": risk_factors,
        "model": model_name,
        "ai_generated": ai_generated,
        "persisted": persist,
        "focus_queries": context.get("focus_queries", []),
        "context_summary": context.get("summary", []),
    }
