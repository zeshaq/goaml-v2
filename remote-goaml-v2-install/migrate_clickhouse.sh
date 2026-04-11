#!/bin/bash
# =============================================================
# goAML-V2 — Apply ClickHouse schema
# Splits each statement and sends individually via HTTP API
# =============================================================

set -e

CH_USER="goaml"
CH_PASS="Asdf@1234"
CH_URL="http://localhost:8123/"

run_ch() {
    local sql="$1"
    local result
    result=$(curl -s -w "\n%{http_code}" \
        "$CH_URL" \
        --user "$CH_USER:$CH_PASS" \
        --data-binary "$sql")
    local http_code
    http_code=$(echo "$result" | tail -n1)
    local body
    body=$(echo "$result" | head -n-1)
    if [ "$http_code" != "200" ]; then
        echo "✗ ERROR (HTTP $http_code): $body"
        echo "  SQL: ${sql:0:80}..."
        exit 1
    fi
    if [ -n "$body" ]; then
        echo "  $body"
    fi
}

echo "=================================================="
echo " goAML-V2 ClickHouse Schema Migration"
echo "=================================================="

echo ""
echo "→ Creating database..."
run_ch "CREATE DATABASE IF NOT EXISTS goaml"
echo "✓ Database goaml ready"

echo ""
echo "→ Creating transaction_events table..."
run_ch "CREATE TABLE IF NOT EXISTS goaml.transaction_events (
    transaction_id      UUID,
    transaction_ref     String,
    external_id         String DEFAULT '',
    sender_account      String,
    sender_country      LowCardinality(String),
    receiver_account    String,
    receiver_country    LowCardinality(String),
    amount              Decimal(20, 4),
    currency            LowCardinality(String),
    amount_usd          Decimal(20, 4),
    transaction_type    LowCardinality(String),
    channel             LowCardinality(String) DEFAULT '',
    risk_score          Float32,
    risk_level          LowCardinality(String),
    risk_factors        Array(String),
    ml_score_raw        Float32,
    is_flagged          UInt8 DEFAULT 0,
    is_alerted          UInt8 DEFAULT 0,
    transacted_at       DateTime64(3, 'UTC'),
    processed_at        DateTime64(3, 'UTC'),
    inserted_at         DateTime64(3, 'UTC') DEFAULT now64()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(transacted_at)
ORDER BY (transacted_at, sender_account, receiver_account)
TTL toDateTime(transacted_at) + INTERVAL 7 YEAR
SETTINGS index_granularity = 8192"
echo "✓ transaction_events"

echo ""
echo "→ Creating alert_events table..."
run_ch "CREATE TABLE IF NOT EXISTS goaml.alert_events (
    alert_id        UUID,
    alert_ref       String,
    alert_type      LowCardinality(String),
    severity        LowCardinality(String),
    status          LowCardinality(String),
    account_id      String,
    transaction_id  UUID,
    rule_id         String DEFAULT '',
    created_at      DateTime64(3, 'UTC'),
    closed_at       Nullable(DateTime64(3, 'UTC')),
    inserted_at     DateTime64(3, 'UTC') DEFAULT now64()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (created_at, alert_type, severity)
TTL toDateTime(created_at) + INTERVAL 7 YEAR
SETTINGS index_granularity = 8192"
echo "✓ alert_events"

echo ""
echo "→ Creating risk_score_history table..."
run_ch "CREATE TABLE IF NOT EXISTS goaml.risk_score_history (
    account_id      String,
    risk_score      Float32,
    risk_level      LowCardinality(String),
    trigger_type    LowCardinality(String),
    trigger_id      String DEFAULT '',
    scored_at       DateTime64(3, 'UTC'),
    inserted_at     DateTime64(3, 'UTC') DEFAULT now64()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(scored_at)
ORDER BY (account_id, scored_at)
TTL toDateTime(scored_at) + INTERVAL 3 YEAR
SETTINGS index_granularity = 8192"
echo "✓ risk_score_history"

echo ""
echo "→ Creating screening_events table..."
run_ch "CREATE TABLE IF NOT EXISTS goaml.screening_events (
    screening_id    UUID,
    entity_name     String,
    match_score     Float32,
    dataset         LowCardinality(String),
    match_found     UInt8,
    trigger         LowCardinality(String),
    screened_at     DateTime64(3, 'UTC'),
    inserted_at     DateTime64(3, 'UTC') DEFAULT now64()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(screened_at)
ORDER BY (screened_at, dataset)
TTL toDateTime(screened_at) + INTERVAL 5 YEAR
SETTINGS index_granularity = 8192"
echo "✓ screening_events"

echo ""
echo "→ Creating materialized view: txn_volume_hourly..."
run_ch "CREATE MATERIALIZED VIEW IF NOT EXISTS goaml.txn_volume_hourly
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (hour, transaction_type, currency, risk_level)
AS SELECT
    toStartOfHour(transacted_at)    AS hour,
    transaction_type,
    currency,
    risk_level,
    count()                          AS txn_count,
    sum(amount_usd)                  AS total_amount_usd,
    sum(is_flagged)                  AS flagged_count,
    sum(is_alerted)                  AS alerted_count,
    avg(risk_score)                  AS avg_risk_score,
    max(risk_score)                  AS max_risk_score
FROM goaml.transaction_events
GROUP BY hour, transaction_type, currency, risk_level"
echo "✓ txn_volume_hourly"

echo ""
echo "→ Creating materialized view: txn_volume_daily..."
run_ch "CREATE MATERIALIZED VIEW IF NOT EXISTS goaml.txn_volume_daily
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(day)
ORDER BY (day, transaction_type, sender_country, receiver_country)
AS SELECT
    toStartOfDay(transacted_at)     AS day,
    transaction_type,
    sender_country,
    receiver_country,
    count()                          AS txn_count,
    sum(amount_usd)                  AS total_amount_usd,
    sum(is_flagged)                  AS flagged_count,
    avg(risk_score)                  AS avg_risk_score
FROM goaml.transaction_events
GROUP BY day, transaction_type, sender_country, receiver_country"
echo "✓ txn_volume_daily"

echo ""
echo "→ Creating materialized view: alert_summary_daily..."
run_ch "CREATE MATERIALIZED VIEW IF NOT EXISTS goaml.alert_summary_daily
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(day)
ORDER BY (day, alert_type, severity)
AS SELECT
    toStartOfDay(created_at)        AS day,
    alert_type,
    severity,
    count()                          AS alert_count
FROM goaml.alert_events
GROUP BY day, alert_type, severity"
echo "✓ alert_summary_daily"

echo ""
echo "→ Creating materialized view: account_velocity_hourly..."
run_ch "CREATE MATERIALIZED VIEW IF NOT EXISTS goaml.account_velocity_hourly
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(hour)
ORDER BY (hour, sender_account)
AS SELECT
    toStartOfHour(transacted_at)    AS hour,
    sender_account,
    count()                          AS outbound_count,
    sum(amount_usd)                  AS outbound_amount_usd,
    uniq(receiver_account)           AS unique_counterparties,
    uniq(receiver_country)           AS unique_countries
FROM goaml.transaction_events
GROUP BY hour, sender_account"
echo "✓ account_velocity_hourly"

echo ""
echo "→ Verifying tables..."
run_ch "SHOW TABLES FROM goaml"

echo ""
echo "=================================================="
echo " ClickHouse migration complete"
echo "=================================================="
