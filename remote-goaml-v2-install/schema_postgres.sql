-- =============================================================
-- goAML-V2 PostgreSQL Schema
-- Database: goaml
-- =============================================================

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";   -- fuzzy text search on entity names

-- =============================================================
-- ENUMS
-- =============================================================

CREATE TYPE transaction_type AS ENUM (
    'wire_transfer',
    'cash_deposit',
    'cash_withdrawal',
    'crypto',
    'ach',
    'check',
    'internal_transfer',
    'international_wire',
    'other'
);

CREATE TYPE transaction_status AS ENUM (
    'pending',
    'completed',
    'failed',
    'reversed',
    'flagged'
);

CREATE TYPE risk_level AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);

CREATE TYPE alert_status AS ENUM (
    'open',
    'reviewing',
    'escalated',
    'closed',
    'false_positive'
);

CREATE TYPE alert_type AS ENUM (
    'structuring',
    'velocity',
    'sanctions_match',
    'unusual_geography',
    'large_cash',
    'rapid_movement',
    'crypto_mixing',
    'layering',
    'pep_exposure',
    'unusual_pattern',
    'ml_flag'
);

CREATE TYPE case_status AS ENUM (
    'open',
    'reviewing',
    'pending_sar',
    'sar_filed',
    'closed',
    'referred'
);

CREATE TYPE case_priority AS ENUM (
    'low',
    'medium',
    'high',
    'critical'
);

CREATE TYPE entity_type AS ENUM (
    'individual',
    'company',
    'trust',
    'government',
    'ngo',
    'financial_institution',
    'unknown'
);

CREATE TYPE sar_status AS ENUM (
    'draft',
    'pending_review',
    'approved',
    'filed',
    'rejected'
);

-- =============================================================
-- ACCOUNTS
-- =============================================================

CREATE TABLE accounts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_number  VARCHAR(64) UNIQUE NOT NULL,
    account_name    VARCHAR(255) NOT NULL,
    account_type    VARCHAR(64),
    currency        CHAR(3) DEFAULT 'USD',
    institution     VARCHAR(255),
    country         CHAR(2),
    opened_at       TIMESTAMPTZ,
    risk_score      NUMERIC(5,4) DEFAULT 0.0,
    risk_level      risk_level DEFAULT 'low',
    is_monitored    BOOLEAN DEFAULT FALSE,
    is_blocked      BOOLEAN DEFAULT FALSE,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_accounts_number ON accounts(account_number);
CREATE INDEX idx_accounts_risk_score ON accounts(risk_score DESC);
CREATE INDEX idx_accounts_risk_level ON accounts(risk_level);
CREATE INDEX idx_accounts_country ON accounts(country);

-- =============================================================
-- ENTITIES
-- =============================================================

CREATE TABLE entities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(512) NOT NULL,
    name_normalized VARCHAR(512),           -- lowercase, stripped for matching
    entity_type     entity_type DEFAULT 'unknown',
    date_of_birth   DATE,
    nationality     CHAR(2),
    country         CHAR(2),
    id_number       VARCHAR(128),           -- passport, national ID, etc.
    id_type         VARCHAR(64),
    is_pep          BOOLEAN DEFAULT FALSE,  -- Politically Exposed Person
    is_sanctioned   BOOLEAN DEFAULT FALSE,
    sanctions_list  VARCHAR(255)[],         -- OFAC, EU, UN, etc.
    risk_score      NUMERIC(5,4) DEFAULT 0.0,
    risk_level      risk_level DEFAULT 'low',
    embedding_id    VARCHAR(255),           -- Milvus vector ID
    neo4j_id        VARCHAR(255),           -- Neo4j node ID
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_entities_name ON entities USING gin(name gin_trgm_ops);
CREATE INDEX idx_entities_name_normalized ON entities(name_normalized);
CREATE INDEX idx_entities_is_sanctioned ON entities(is_sanctioned);
CREATE INDEX idx_entities_is_pep ON entities(is_pep);
CREATE INDEX idx_entities_risk_level ON entities(risk_level);

-- Link accounts to entities (many-to-many)
CREATE TABLE account_entities (
    account_id  UUID REFERENCES accounts(id) ON DELETE CASCADE,
    entity_id   UUID REFERENCES entities(id) ON DELETE CASCADE,
    role        VARCHAR(64) DEFAULT 'owner',  -- owner, signatory, beneficiary, etc.
    since       TIMESTAMPTZ,
    PRIMARY KEY (account_id, entity_id)
);

-- =============================================================
-- TRANSACTIONS
-- =============================================================

CREATE TABLE transactions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id         VARCHAR(255) UNIQUE,            -- source system reference
    transaction_ref     VARCHAR(128) UNIQUE NOT NULL,   -- e.g. TXN-8841209
    transaction_type    transaction_type NOT NULL,
    status              transaction_status DEFAULT 'completed',

    -- Parties
    sender_account_id   UUID REFERENCES accounts(id),
    sender_account_ref  VARCHAR(64),                    -- raw ref if account not in DB
    sender_name         VARCHAR(512),
    sender_country      CHAR(2),
    receiver_account_id UUID REFERENCES accounts(id),
    receiver_account_ref VARCHAR(64),
    receiver_name       VARCHAR(512),
    receiver_country    CHAR(2),

    -- Amounts
    amount              NUMERIC(20,4) NOT NULL,
    currency            CHAR(3) NOT NULL DEFAULT 'USD',
    amount_usd          NUMERIC(20,4),                  -- normalized to USD

    -- Risk
    risk_score          NUMERIC(5,4) DEFAULT 0.0,
    risk_level          risk_level DEFAULT 'low',
    risk_factors        TEXT[],                         -- e.g. STRUCT, VELOCITY, GEO
    ml_score_raw        NUMERIC(10,6),                  -- raw XGBoost output
    ml_features         JSONB DEFAULT '{}',             -- feature vector used for scoring

    -- Metadata
    description         TEXT,
    reference           VARCHAR(512),
    channel             VARCHAR(64),                    -- online, branch, api, etc.
    ip_address          INET,
    device_id           VARCHAR(255),
    geo_lat             NUMERIC(9,6),
    geo_lon             NUMERIC(9,6),
    metadata            JSONB DEFAULT '{}',

    -- Timestamps
    transacted_at       TIMESTAMPTZ NOT NULL,
    processed_at        TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_txn_sender_account ON transactions(sender_account_id);
CREATE INDEX idx_txn_receiver_account ON transactions(receiver_account_id);
CREATE INDEX idx_txn_transacted_at ON transactions(transacted_at DESC);
CREATE INDEX idx_txn_risk_score ON transactions(risk_score DESC);
CREATE INDEX idx_txn_risk_level ON transactions(risk_level);
CREATE INDEX idx_txn_amount ON transactions(amount DESC);
CREATE INDEX idx_txn_type ON transactions(transaction_type);
CREATE INDEX idx_txn_status ON transactions(status);
CREATE INDEX idx_txn_ref ON transactions(transaction_ref);
CREATE INDEX idx_txn_external_id ON transactions(external_id);
CREATE INDEX idx_txn_transacted_at_risk ON transactions(transacted_at DESC, risk_score DESC);

-- =============================================================
-- ALERTS
-- =============================================================

CREATE TABLE alerts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_ref       VARCHAR(64) UNIQUE NOT NULL,    -- e.g. ALT-4421
    alert_type      alert_type NOT NULL,
    status          alert_status DEFAULT 'open',
    severity        risk_level NOT NULL,

    -- Linked objects
    transaction_id  UUID REFERENCES transactions(id),
    account_id      UUID REFERENCES accounts(id),
    entity_id       UUID REFERENCES entities(id),
    case_id         UUID,                           -- FK added after cases table

    -- Content
    title           VARCHAR(512) NOT NULL,
    description     TEXT,
    evidence        JSONB DEFAULT '{}',             -- raw data supporting the alert
    rule_id         VARCHAR(128),                   -- which rule/model triggered this
    ml_explanation  TEXT,                           -- LLM-generated explanation

    -- Assignment
    assigned_to     VARCHAR(255),
    reviewed_by     VARCHAR(255),
    reviewed_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ,
    resolution_note TEXT,

    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_alerts_status ON alerts(status);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_type ON alerts(alert_type);
CREATE INDEX idx_alerts_account ON alerts(account_id);
CREATE INDEX idx_alerts_transaction ON alerts(transaction_id);
CREATE INDEX idx_alerts_created_at ON alerts(created_at DESC);
CREATE INDEX idx_alerts_case ON alerts(case_id);

-- =============================================================
-- CASES
-- =============================================================

CREATE TABLE cases (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_ref        VARCHAR(64) UNIQUE NOT NULL,    -- e.g. CASE-2024-0892
    title           VARCHAR(512) NOT NULL,
    description     TEXT,
    status          case_status DEFAULT 'open',
    priority        case_priority DEFAULT 'medium',

    -- Assignment
    assigned_to     VARCHAR(255),
    created_by      VARCHAR(255),
    closed_by       VARCHAR(255),
    closed_at       TIMESTAMPTZ,

    -- Linked objects
    primary_account_id  UUID REFERENCES accounts(id),
    primary_entity_id   UUID REFERENCES entities(id),

    -- SAR
    sar_required    BOOLEAN DEFAULT FALSE,
    sar_id          UUID,                           -- FK added after sar table

    -- Summary (LLM-generated)
    ai_summary      TEXT,
    ai_risk_factors TEXT[],

    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cases_status ON cases(status);
CREATE INDEX idx_cases_priority ON cases(priority);
CREATE INDEX idx_cases_assigned ON cases(assigned_to);
CREATE INDEX idx_cases_created_at ON cases(created_at DESC);

-- Add FK from alerts to cases (now that cases table exists)
ALTER TABLE alerts ADD CONSTRAINT fk_alerts_case
    FOREIGN KEY (case_id) REFERENCES cases(id);

-- Case ↔ Transaction link (many-to-many)
CREATE TABLE case_transactions (
    case_id         UUID REFERENCES cases(id) ON DELETE CASCADE,
    transaction_id  UUID REFERENCES transactions(id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ DEFAULT NOW(),
    note            TEXT,
    PRIMARY KEY (case_id, transaction_id)
);

-- Case ↔ Alert link (many-to-many)
CREATE TABLE case_alerts (
    case_id         UUID REFERENCES cases(id) ON DELETE CASCADE,
    alert_id        UUID REFERENCES alerts(id) ON DELETE CASCADE,
    added_at        TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (case_id, alert_id)
);

-- Case timeline / audit log
CREATE TABLE case_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id     UUID REFERENCES cases(id) ON DELETE CASCADE,
    event_type  VARCHAR(64) NOT NULL,   -- created, status_change, note_added, sar_filed, etc.
    actor       VARCHAR(255),
    detail      TEXT,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_case_events_case ON case_events(case_id);
CREATE INDEX idx_case_events_created ON case_events(created_at DESC);

-- =============================================================
-- SAR REPORTS
-- =============================================================

CREATE TABLE sar_reports (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sar_ref         VARCHAR(64) UNIQUE NOT NULL,    -- e.g. SAR-2024-0041
    case_id         UUID REFERENCES cases(id),
    status          sar_status DEFAULT 'draft',

    -- Subjects
    subject_name    VARCHAR(512),
    subject_type    entity_type,
    subject_account VARCHAR(64),

    -- Report content
    narrative       TEXT,                           -- LLM-drafted, human-reviewed
    activity_type   VARCHAR(255),
    activity_amount NUMERIC(20,4),
    activity_from   TIMESTAMPTZ,
    activity_to     TIMESTAMPTZ,
    filing_agency   VARCHAR(128) DEFAULT 'FinCEN',

    -- Workflow
    drafted_by      VARCHAR(255),
    drafted_at      TIMESTAMPTZ,
    reviewed_by     VARCHAR(255),
    reviewed_at     TIMESTAMPTZ,
    approved_by     VARCHAR(255),
    approved_at     TIMESTAMPTZ,
    filed_at        TIMESTAMPTZ,
    filing_ref      VARCHAR(255),                   -- official filing reference

    ai_drafted      BOOLEAN DEFAULT FALSE,          -- was narrative AI-generated
    ai_model        VARCHAR(128),                   -- which model drafted it

    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_sar_status ON sar_reports(status);
CREATE INDEX idx_sar_case ON sar_reports(case_id);
CREATE INDEX idx_sar_created ON sar_reports(created_at DESC);

-- Add FK from cases to SAR
ALTER TABLE cases ADD CONSTRAINT fk_cases_sar
    FOREIGN KEY (sar_id) REFERENCES sar_reports(id);

-- =============================================================
-- SCREENING RESULTS
-- =============================================================

CREATE TABLE screening_results (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID REFERENCES entities(id),
    entity_name     VARCHAR(512) NOT NULL,          -- name as searched

    -- Match details
    matched_name    VARCHAR(512),
    match_score     NUMERIC(5,4),                   -- 0.0 - 1.0
    dataset         VARCHAR(128),                   -- OFAC SDN, EU Sanctions, etc.
    dataset_id      VARCHAR(255),                   -- ID in source dataset
    match_type      VARCHAR(64),                    -- name, alias, id_number, etc.

    -- Matched entity details
    matched_country CHAR(2),
    matched_type    entity_type,
    matched_detail  JSONB DEFAULT '{}',

    -- Context
    screened_by     VARCHAR(255),
    trigger         VARCHAR(128),                   -- manual, transaction, onboarding
    linked_txn_id   UUID REFERENCES transactions(id),

    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_screening_entity ON screening_results(entity_id);
CREATE INDEX idx_screening_score ON screening_results(match_score DESC);
CREATE INDEX idx_screening_dataset ON screening_results(dataset);
CREATE INDEX idx_screening_created ON screening_results(created_at DESC);

-- =============================================================
-- DOCUMENTS
-- =============================================================

CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    filename        VARCHAR(512) NOT NULL,
    file_type       VARCHAR(64),
    file_size       BIGINT,
    storage_path    VARCHAR(1024),                  -- MinIO path
    checksum        VARCHAR(128),

    -- Extraction
    extracted_text  TEXT,
    ocr_applied     BOOLEAN DEFAULT FALSE,
    ocr_model       VARCHAR(128),
    parse_applied   BOOLEAN DEFAULT FALSE,
    structured_data JSONB DEFAULT '{}',             -- Nemotron-Parse output

    -- PII
    pii_detected    BOOLEAN DEFAULT FALSE,
    pii_entities    JSONB DEFAULT '{}',             -- gliner-PII output
    pii_redacted    BOOLEAN DEFAULT FALSE,

    -- Embeddings
    embedded        BOOLEAN DEFAULT FALSE,
    embedding_ids   TEXT[],                         -- Milvus vector IDs

    -- Links
    case_id         UUID REFERENCES cases(id),
    entity_id       UUID REFERENCES entities(id),
    transaction_id  UUID REFERENCES transactions(id),
    uploaded_by     VARCHAR(255),

    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_docs_case ON documents(case_id);
CREATE INDEX idx_docs_entity ON documents(entity_id);
CREATE INDEX idx_docs_created ON documents(created_at DESC);

-- =============================================================
-- SEQUENCE GENERATORS (for human-readable refs)
-- =============================================================

CREATE SEQUENCE txn_ref_seq START 8000000;
CREATE SEQUENCE alert_ref_seq START 4000;
CREATE SEQUENCE case_ref_seq START 800;
CREATE SEQUENCE sar_ref_seq START 40;

-- =============================================================
-- HELPER FUNCTIONS
-- =============================================================

-- Auto-generate transaction reference
CREATE OR REPLACE FUNCTION generate_txn_ref()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.transaction_ref IS NULL OR NEW.transaction_ref = '' THEN
        NEW.transaction_ref := 'TXN-' || LPAD(nextval('txn_ref_seq')::TEXT, 7, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_txn_ref
    BEFORE INSERT ON transactions
    FOR EACH ROW EXECUTE FUNCTION generate_txn_ref();

-- Auto-generate alert reference
CREATE OR REPLACE FUNCTION generate_alert_ref()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.alert_ref IS NULL OR NEW.alert_ref = '' THEN
        NEW.alert_ref := 'ALT-' || LPAD(nextval('alert_ref_seq')::TEXT, 4, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_alert_ref
    BEFORE INSERT ON alerts
    FOR EACH ROW EXECUTE FUNCTION generate_alert_ref();

-- Auto-generate case reference
CREATE OR REPLACE FUNCTION generate_case_ref()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.case_ref IS NULL OR NEW.case_ref = '' THEN
        NEW.case_ref := 'CASE-' || EXTRACT(YEAR FROM NOW()) || '-' || LPAD(nextval('case_ref_seq')::TEXT, 4, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_case_ref
    BEFORE INSERT ON cases
    FOR EACH ROW EXECUTE FUNCTION generate_case_ref();

-- Auto-update updated_at
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_accounts_updated_at BEFORE UPDATE ON accounts FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_entities_updated_at BEFORE UPDATE ON entities FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_alerts_updated_at BEFORE UPDATE ON alerts FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_cases_updated_at BEFORE UPDATE ON cases FOR EACH ROW EXECUTE FUNCTION update_updated_at();
CREATE TRIGGER trg_sar_updated_at BEFORE UPDATE ON sar_reports FOR EACH ROW EXECUTE FUNCTION update_updated_at();
