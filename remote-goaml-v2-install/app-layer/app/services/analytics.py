"""
goAML-V2 — ClickHouse analytics write service
Streams transaction and alert events to ClickHouse
"""

from datetime import datetime, timezone
from uuid import UUID

from core.clickhouse import get_ch_client
from models.transaction import TransactionIngest, ScorerResponse
from services.scorer import to_usd


def write_transaction_event(
    txn: TransactionIngest,
    score: ScorerResponse,
    transaction_id: UUID,
    transaction_ref: str,
    alert_created: bool,
    processed_at: datetime,
) -> None:
    """Write transaction to ClickHouse transaction_events table."""
    try:
        client = get_ch_client()
        amount_usd = to_usd(txn.amount, txn.currency)
        transacted_at = txn.transacted_at.replace(tzinfo=timezone.utc) \
            if txn.transacted_at.tzinfo is None else txn.transacted_at

        client.insert(
            "transaction_events",
            [[
                str(transaction_id),
                transaction_ref,
                txn.external_id or "",
                txn.sender_account_ref,
                txn.sender_country or "",
                txn.receiver_account_ref,
                txn.receiver_country or "",
                float(txn.amount),
                txn.currency,
                round(amount_usd, 4),
                txn.transaction_type.value,
                txn.channel or "",
                score.risk_score,
                score.risk_level,
                score.risk_factors,
                score.risk_score,
                1 if score.risk_score >= 0.45 else 0,
                1 if alert_created else 0,
                transacted_at,
                processed_at,
            ]],
            column_names=[
                "transaction_id", "transaction_ref", "external_id",
                "sender_account", "sender_country",
                "receiver_account", "receiver_country",
                "amount", "currency", "amount_usd",
                "transaction_type", "channel",
                "risk_score", "risk_level", "risk_factors", "ml_score_raw",
                "is_flagged", "is_alerted",
                "transacted_at", "processed_at",
            ],
        )
    except Exception as e:
        # ClickHouse write failure must never break the main flow
        import logging
        logging.getLogger(__name__).error(f"ClickHouse write failed: {e}")


def write_alert_event(
    alert_id: UUID,
    alert_ref: str,
    alert_type: str,
    severity: str,
    account_id: UUID | None,
    transaction_id: UUID,
    created_at: datetime,
) -> None:
    """Write alert event to ClickHouse alert_events table."""
    try:
        client = get_ch_client()
        client.insert(
            "alert_events",
            [[
                str(alert_id),
                alert_ref,
                alert_type,
                severity,
                "open",
                str(account_id) if account_id else "",
                str(transaction_id),
                "ml_scorer_v1",
                created_at,
                None,
            ]],
            column_names=[
                "alert_id", "alert_ref", "alert_type", "severity", "status",
                "account_id", "transaction_id", "rule_id",
                "created_at", "closed_at",
            ],
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"ClickHouse alert write failed: {e}")


def write_risk_score_history(
    account_id: str,
    risk_score: float,
    risk_level: str,
    trigger_id: str,
    scored_at: datetime,
) -> None:
    """Write risk score change to history table."""
    try:
        client = get_ch_client()
        client.insert(
            "risk_score_history",
            [[account_id, risk_score, risk_level, "transaction", trigger_id, scored_at]],
            column_names=["account_id", "risk_score", "risk_level",
                          "trigger_type", "trigger_id", "scored_at"],
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"ClickHouse risk history write failed: {e}")
