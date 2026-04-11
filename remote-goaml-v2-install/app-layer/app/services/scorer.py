"""
goAML-V2 — XGBoost Risk Scorer Service
Calls goaml-scorer at 160.30.63.152:8010
"""

import httpx
from decimal import Decimal
from datetime import datetime

from core.config import settings
from models.transaction import TransactionIngest, ScorerRequest, ScorerResponse

# USD exchange rate fallback (in production, pull from FX API)
FX_RATES: dict[str, float] = {
    "USD": 1.0, "EUR": 1.09, "GBP": 1.27, "JPY": 0.0067,
    "CHF": 1.13, "AED": 0.27, "SAR": 0.27, "BDT": 0.0091,
    "SGD": 0.74, "HKD": 0.13,
}

CASH_TYPES    = {"cash_deposit", "cash_withdrawal"}
CRYPTO_TYPES  = {"crypto"}


def _risk_level_from_score(score: float) -> str:
    if score >= 0.75:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def to_usd(amount: Decimal, currency: str) -> float:
    rate = FX_RATES.get(currency.upper(), 1.0)
    return float(amount) * rate


def build_scorer_request(txn: TransactionIngest) -> ScorerRequest:
    now = txn.transacted_at or datetime.utcnow()
    return ScorerRequest(
        amount_usd         = to_usd(txn.amount, txn.currency),
        transaction_type   = txn.transaction_type.value,
        sender_country     = txn.sender_country or "XX",
        receiver_country   = txn.receiver_country or "XX",
        currency           = txn.currency,
        channel            = txn.channel or "unknown",
        hour_of_day        = now.hour,
        day_of_week        = now.weekday(),
        is_international   = int(
            txn.sender_country != txn.receiver_country
            if txn.sender_country and txn.receiver_country else 0
        ),
        is_cash            = int(txn.transaction_type.value in CASH_TYPES),
        is_crypto          = int(txn.transaction_type.value in CRYPTO_TYPES),
    )


def build_legacy_feature_vector(req: ScorerRequest) -> list[list[float]]:
    """
    Legacy scorer compatibility payload for older /score contracts.
    """
    return [[
        float(req.amount_usd),
        float(req.is_international),
        float(req.is_cash),
        float(req.is_crypto),
        float(req.hour_of_day),
        float(req.day_of_week),
        1.0 if str(req.sender_country).upper() != str(req.receiver_country).upper() else 0.0,
    ]]


def _build_scorer_response(data: dict, request: ScorerRequest, scoring_mode: str) -> ScorerResponse:
    raw_score = data.get("risk_score")
    if raw_score is None:
        scores = data.get("scores") or []
        if isinstance(scores, list) and scores:
            raw_score = scores[0]
    score = float(raw_score or 0.0)
    risk_level = data.get("risk_level") or _risk_level_from_score(score)
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    return ScorerResponse(
        risk_score=score,
        risk_level=risk_level,
        risk_factors=data.get("risk_factors", []),
        features=data.get("features", request.model_dump()),
        scoring_mode=data.get("scoring_mode") or scoring_mode,
        model_name=data.get("model_name"),
        registered_model_name=data.get("registered_model_name"),
        model_version=str(data.get("model_version")) if data.get("model_version") not in (None, "") else None,
        model_stage=data.get("model_stage"),
        metadata=metadata,
    )


async def score_transaction(txn: TransactionIngest) -> ScorerResponse:
    """
    Call the XGBoost scorer. Falls back to a rule-based score
    if the scorer is unavailable, ensuring the pipeline never blocks.
    """
    request = build_scorer_request(txn)
    amount_usd = request.amount_usd

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.post(
                f"{settings.SCORER_URL}/score",
                json=request.model_dump(),
            )
            if resp.status_code == 422:
                legacy_resp = await client.post(
                    f"{settings.SCORER_URL}/score",
                    json={"features": build_legacy_feature_vector(request)},
                )
                legacy_resp.raise_for_status()
                return _build_scorer_response(legacy_resp.json(), request, "legacy_service")
            resp.raise_for_status()
            return _build_scorer_response(resp.json(), request, "service")

    except Exception:
        # Scorer unavailable — apply rule-based fallback
        return _rule_based_score(request, amount_usd)


def _rule_based_score(req: ScorerRequest, amount_usd: float) -> ScorerResponse:
    """Simple rule-based fallback when ML scorer is unreachable."""
    score = 0.0
    factors: list[str] = []

    if amount_usd >= 10_000:
        score += 0.3
        factors.append("HIGH_AMT")
    if amount_usd >= 50_000:
        score += 0.2
        factors.append("VERY_HIGH_AMT")
    if req.is_cash:
        score += 0.2
        factors.append("CASH")
    if req.is_crypto:
        score += 0.25
        factors.append("CRYPTO")
    if req.is_international:
        score += 0.1
        factors.append("INTERNATIONAL")
    if req.sender_country in {"IR", "KP", "SY", "CU"}:
        score += 0.4
        factors.append("SANCTIONED_COUNTRY")
    if req.hour_of_day < 5:
        score += 0.05
        factors.append("ODD_HOURS")

    score = min(score, 1.0)

    if score >= 0.75:
        level = "high"
    elif score >= 0.45:
        level = "medium"
    else:
        level = "low"

    return ScorerResponse(
        risk_score   = round(score, 4),
        risk_level   = level,
        risk_factors = factors,
        features     = req.model_dump(),
        scoring_mode = "rule_fallback",
        model_name   = "rule-fallback-v1",
        registered_model_name = settings.SCORER_REGISTERED_MODEL_NAME,
        model_version = None,
        model_stage = None,
        metadata = {"source": "app_fallback"},
    )
