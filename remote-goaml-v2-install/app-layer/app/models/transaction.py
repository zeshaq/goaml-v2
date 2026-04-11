"""
goAML-V2 Pydantic models — Transactions & Alerts
"""

from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────
# Enums (mirror PostgreSQL enums)
# ─────────────────────────────────────────

class TransactionType(str, Enum):
    wire_transfer       = "wire_transfer"
    cash_deposit        = "cash_deposit"
    cash_withdrawal     = "cash_withdrawal"
    crypto              = "crypto"
    ach                 = "ach"
    check               = "check"
    internal_transfer   = "internal_transfer"
    international_wire  = "international_wire"
    other               = "other"


class TransactionStatus(str, Enum):
    pending     = "pending"
    completed   = "completed"
    failed      = "failed"
    reversed    = "reversed"
    flagged     = "flagged"


class RiskLevel(str, Enum):
    low      = "low"
    medium   = "medium"
    high     = "high"
    critical = "critical"


class AlertType(str, Enum):
    structuring         = "structuring"
    velocity            = "velocity"
    sanctions_match     = "sanctions_match"
    unusual_geography   = "unusual_geography"
    large_cash          = "large_cash"
    rapid_movement      = "rapid_movement"
    crypto_mixing       = "crypto_mixing"
    layering            = "layering"
    pep_exposure        = "pep_exposure"
    unusual_pattern     = "unusual_pattern"
    ml_flag             = "ml_flag"


# ─────────────────────────────────────────
# Transaction schemas
# ─────────────────────────────────────────

class TransactionIngest(BaseModel):
    """Payload for POST /api/v1/transactions"""

    # Parties
    sender_account_ref:   str = Field(..., description="Sender account number or ref")
    sender_name:          str | None = None
    sender_country:       str | None = Field(None, max_length=2)
    receiver_account_ref: str = Field(..., description="Receiver account number or ref")
    receiver_name:        str | None = None
    receiver_country:     str | None = Field(None, max_length=2)

    # Amount
    amount:   Decimal = Field(..., gt=0)
    currency: str     = Field("USD", max_length=3)

    # Classification
    transaction_type: TransactionType
    status:           TransactionStatus = TransactionStatus.completed
    channel:          str | None = None
    description:      str | None = None
    reference:        str | None = None

    # Source metadata
    external_id:  str | None = None
    ip_address:   str | None = None
    device_id:    str | None = None
    transacted_at: datetime = Field(default_factory=datetime.utcnow)
    metadata:     dict[str, Any] = Field(default_factory=dict)

    @field_validator("currency")
    @classmethod
    def currency_upper(cls, v: str) -> str:
        return v.upper()

    @field_validator("sender_country", "receiver_country")
    @classmethod
    def country_upper(cls, v: str | None) -> str | None:
        return v.upper() if v else v


class TransactionResponse(BaseModel):
    """Response from POST /api/v1/transactions"""

    id:              UUID
    transaction_ref: str
    status:          str
    risk_score:      float
    risk_level:      str
    risk_factors:    list[str]
    ml_score_raw:    float | None
    alert_created:   bool
    alert_ref:       str | None
    transacted_at:   datetime
    created_at:      datetime

    model_config = {"from_attributes": True}


class TransactionListItem(BaseModel):
    id:              UUID
    transaction_ref: str
    transaction_type: str
    sender_account_ref: str | None
    receiver_account_ref: str | None
    amount:          Decimal
    currency:        str
    amount_usd:      Decimal | None
    risk_score:      float
    risk_level:      str
    risk_factors:    list[str]
    status:          str
    transacted_at:   datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────
# Alert schemas
# ─────────────────────────────────────────

class AlertResponse(BaseModel):
    id:             UUID
    alert_ref:      str
    alert_type:     str
    severity:       str
    status:         str
    title:          str
    description:    str | None
    transaction_id: UUID | None
    account_id:     UUID | None
    created_at:     datetime

    model_config = {"from_attributes": True}


# ─────────────────────────────────────────
# Scorer schemas
# ─────────────────────────────────────────

class ScorerRequest(BaseModel):
    """Payload sent to XGBoost scorer at :8010"""
    amount_usd:         float
    transaction_type:   str
    sender_country:     str
    receiver_country:   str
    currency:           str
    channel:            str
    hour_of_day:        int
    day_of_week:        int
    is_international:   int
    is_cash:            int
    is_crypto:          int


class ScorerResponse(BaseModel):
    """Response from XGBoost scorer"""
    risk_score:  float
    risk_level:  str
    risk_factors: list[str] = []
    features:    dict[str, Any] = {}
