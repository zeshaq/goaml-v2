"""
goAML-V2 — Transaction API endpoints
POST /api/v1/transactions  — ingest + score + alert
GET  /api/v1/transactions  — list with filters
"""

from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from models.transaction import (
    TransactionIngest,
    TransactionResponse,
    TransactionListItem,
)
from services.auth import AuthenticatedUser, require_permissions
from services.scorer import score_transaction
from services.transaction_db import create_transaction, create_alert
from services.analytics import (
    write_transaction_event,
    write_alert_event,
    write_risk_score_history,
)
from core.database import get_pool
from services.graph_sync import safe_resync_graph

router = APIRouter()


# ─────────────────────────────────────────
# POST /api/v1/transactions
# ─────────────────────────────────────────

@router.post(
    "/transactions",
    response_model=TransactionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a transaction — scores risk and creates alert if needed",
)
async def ingest_transaction(
    payload: TransactionIngest,
    current_user: AuthenticatedUser = Depends(require_permissions("ingest_transactions")),
):
    processed_at = datetime.now(timezone.utc)

    # 1. Score with XGBoost (non-blocking fallback if scorer is down)
    score = await score_transaction(payload)

    # 2. Write to PostgreSQL
    try:
        txn_record = await create_transaction(payload, score)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist transaction: {str(e)}",
        )

    transaction_id  = txn_record["id"]
    transaction_ref = txn_record["transaction_ref"]
    sender_id       = txn_record["sender_id"]
    amount_usd      = txn_record["amount_usd"]

    # 3. Create alert if risk exceeds threshold
    alert_record = await create_alert(
        transaction_id  = transaction_id,
        transaction_ref = transaction_ref,
        account_id      = sender_id,
        score           = score,
        amount_usd      = amount_usd,
    )
    alert_created = alert_record is not None

    # 4. Stream to ClickHouse (fire-and-forget, never blocks response)
    write_transaction_event(
        txn             = payload,
        score           = score,
        transaction_id  = transaction_id,
        transaction_ref = transaction_ref,
        alert_created   = alert_created,
        processed_at    = processed_at,
    )

    if alert_record:
        write_alert_event(
            alert_id       = alert_record["id"],
            alert_ref      = alert_record["alert_ref"],
            alert_type     = _infer_alert_type(score.risk_factors),
            severity       = "high" if score.risk_score >= 0.75 else "medium",
            account_id     = sender_id,
            transaction_id = transaction_id,
            created_at     = alert_record["created_at"],
        )

    # 5. Record risk score history in ClickHouse
    write_risk_score_history(
        account_id  = payload.sender_account_ref,
        risk_score  = score.risk_score,
        risk_level  = score.risk_level,
        trigger_id  = str(transaction_id),
        scored_at   = processed_at,
    )

    await safe_resync_graph(clear_existing=True)

    return TransactionResponse(
        id              = transaction_id,
        transaction_ref = transaction_ref,
        status          = payload.status.value,
        risk_score      = score.risk_score,
        risk_level      = score.risk_level,
        risk_factors    = score.risk_factors,
        ml_score_raw    = score.risk_score,
        scoring_mode    = score.scoring_mode,
        scorer_model_name = score.model_name,
        scorer_model_version = score.model_version,
        scorer_model_stage = score.model_stage,
        scorer_registered_model_name = score.registered_model_name,
        alert_created   = alert_created,
        alert_ref       = alert_record["alert_ref"] if alert_record else None,
        transacted_at   = payload.transacted_at,
        created_at      = txn_record["created_at"],
    )


# ─────────────────────────────────────────
# GET /api/v1/transactions
# ─────────────────────────────────────────

@router.get(
    "/transactions",
    response_model=list[TransactionListItem],
    summary="List transactions with optional filters",
)
async def list_transactions(
    limit:      Annotated[int, Query(ge=1, le=200)] = 50,
    offset:     Annotated[int, Query(ge=0)]         = 0,
    risk_level: str | None  = Query(None, description="low | medium | high | critical"),
    account:    str | None  = Query(None, description="Filter by sender/receiver account ref"),
    min_risk:   float | None = Query(None, ge=0.0, le=1.0),
    current_user: AuthenticatedUser = Depends(require_permissions("view_transactions")),
):
    pool = get_pool()

    conditions = ["1=1"]
    args: list = []
    idx = 1

    if risk_level:
        conditions.append(f"risk_level = ${idx}")
        args.append(risk_level)
        idx += 1

    if account:
        conditions.append(f"(sender_account_ref = ${idx} OR receiver_account_ref = ${idx})")
        args.append(account)
        idx += 1

    if min_risk is not None:
        conditions.append(f"risk_score >= ${idx}")
        args.append(min_risk)
        idx += 1

    where = " AND ".join(conditions)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                id, transaction_ref, transaction_type,
                sender_account_ref, receiver_account_ref,
                amount, currency, amount_usd,
                risk_score, risk_level, risk_factors,
                status, transacted_at
            FROM transactions
            WHERE {where}
            ORDER BY transacted_at DESC
            LIMIT ${idx} OFFSET ${idx+1}
            """,
            *args, limit, offset,
        )

    return [
        TransactionListItem(
            id                   = r["id"],
            transaction_ref      = r["transaction_ref"],
            transaction_type     = r["transaction_type"],
            sender_account_ref   = r["sender_account_ref"],
            receiver_account_ref = r["receiver_account_ref"],
            amount               = r["amount"],
            currency             = r["currency"],
            amount_usd           = r["amount_usd"],
            risk_score           = float(r["risk_score"]),
            risk_level           = r["risk_level"],
            risk_factors         = r["risk_factors"] or [],
            status               = r["status"],
            transacted_at        = r["transacted_at"],
        )
        for r in rows
    ]


# ─────────────────────────────────────────
# GET /api/v1/transactions/{id}
# ─────────────────────────────────────────

@router.get(
    "/transactions/{transaction_id}",
    summary="Get transaction detail by ID or ref",
)
async def get_transaction(
    transaction_id: str,
    current_user: AuthenticatedUser = Depends(require_permissions("view_transactions")),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        # Try UUID first, then transaction_ref
        try:
            uid = UUID(transaction_id)
            row = await conn.fetchrow(
                "SELECT * FROM transactions WHERE id = $1", uid
            )
        except ValueError:
            row = await conn.fetchrow(
                "SELECT * FROM transactions WHERE transaction_ref = $1",
                transaction_id,
            )

    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return dict(row)


def _infer_alert_type(factors: list[str]) -> str:
    if "STRUCT" in factors:                      return "structuring"
    if "SANCTIONED_COUNTRY" in factors:          return "sanctions_match"
    if "CRYPTO" in factors:                      return "crypto_mixing"
    if "VELOCITY" in factors:                    return "velocity"
    if "GEO" in factors:                         return "unusual_geography"
    if "CASH" in factors:                        return "large_cash"
    return "ml_flag"
