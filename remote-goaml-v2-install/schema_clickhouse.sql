-- =============================================================
-- goAML-V2 ClickHouse Schema
-- Database: goaml
-- Purpose: Time-series analytics, aggregations, Superset dashboards
-- =============================================================

CREATE DATABASE IF NOT EXISTS goaml;

-- =============================================================
-- TRANSACTION EVENTS
-- Core fact table — every transaction written here in real-time
-- =============================================================

CREATE TABLE IF NOT EXISTS goaml.transaction_events (
    -- IDs
    transaction_id      UUID,
    transaction_ref     String,
    external_id         String DEFAULT '',

    -- Parties
    sender_account      String,
    sender_country      LowCardinality(String),
    receiver_account    String,
    receiver_country    LowCardinality(String),

    -- Amounts
    amount              Decimal(20, 4),
    currency            LowCardinality(String),
    amount_usd          Decimal(20, 4),

    -- Classification
    transaction_type    LowCardinality(String),
    channel             LowCardinality(String) DEFAULT '',

    -- Risk
    risk_score          Float32,
    risk_level          LowCardinality(String),
    risk_factors        Array(String),
    ml_score_raw        Float32,
    is_flagged          UInt8 DEFAULT 0,
    is_alerted          UInt8 DEFAULT 0,

    -- Timestamps
    transacted_at       DateTime64(3, 'UTC'),
    processed_at        DateTime64(3, 'UTC'),
    inserted_at         DateTime64(3, 'UTC') DEFAULT now64()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(transacted_at)
ORDER BY (transacted_at, sender_account, receiver_account)
TTL toDateTime(transacted_at) + INTERVAL 7 YEAR
SETTINGS index_granularity = 8192;

-- =============================================================
-- ALERT EVENTS
-- =============================================================

CREATE TABLE IF NOT EXISTS goaml.alert_events (
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
SETTINGS index_granularity = 8192;

-- =============================================================
-- RISK SCORE HISTORY
-- Track how account risk evolves over time
-- =============================================================

CREATE TABLE IF NOT EXISTS goaml.risk_score_history (
    account_id      String,
    risk_score      Float32,
    risk_level      LowCardinality(String),
    trigger_type    LowCardinality(String),   -- transaction, screening, manual
    trigger_id      String DEFAULT '',
    scored_at       DateTime64(3, 'UTC'),
    inserted_at     DateTime64(3, 'UTC') DEFAULT now64()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(scored_at)
ORDER BY (account_id, scored_at)
TTL toDateTime(scored_at) + INTERVAL 3 YEAR
SETTINGS index_granularity = 8192;

-- =============================================================
-- SCREENING EVENTS
-- Every entity screening call logged here
-- =============================================================

CREATE TABLE IF NOT EXISTS goaml.screening_events (
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
SETTINGS index_granularity = 8192;

-- =============================================================
-- MATERIALIZED VIEWS — pre-aggregated for Superset dashboards
-- =============================================================

-- Hourly transaction volume
CREATE MATERIALIZED VIEW IF NOT EXISTS goaml.txn_volume_hourly
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
GROUP BY hour, transaction_type, currency, risk_level;

-- Daily transaction volume
CREATE MATERIALIZED VIEW IF NOT EXISTS goaml.txn_volume_daily
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
GROUP BY day, transaction_type, sender_country, receiver_country;

-- Daily alert summary
CREATE MATERIALIZED VIEW IF NOT EXISTS goaml.alert_summary_daily
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(day)
ORDER BY (day, alert_type, severity)
AS SELECT
    toStartOfDay(created_at)        AS day,
    alert_type,
    severity,
    count()                          AS alert_count
FROM goaml.alert_events
GROUP BY day, alert_type, severity;

-- Account velocity — rolling 24h transaction count per account
CREATE MATERIALIZED VIEW IF NOT EXISTS goaml.account_velocity_hourly
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
GROUP BY hour, sender_account;
