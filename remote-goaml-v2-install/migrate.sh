#!/bin/bash
# =============================================================
# goAML-V2 — Apply database schemas
# Run from the app server — uses docker exec, no psql needed
# =============================================================

set -e

POSTGRES_USER="goaml"
POSTGRES_DB="goaml"
CLICKHOUSE_USER="goaml"
CLICKHOUSE_PASSWORD="Asdf@1234"
CLICKHOUSE_PORT="8123"

echo "=================================================="
echo " goAML-V2 Schema Migration"
echo "=================================================="

# PostgreSQL via docker exec
echo ""
echo "→ Applying PostgreSQL schema..."
docker exec -i goaml-postgres psql \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    < schema_postgres.sql
echo "✓ PostgreSQL schema applied"

# ClickHouse via HTTP API
echo ""
echo "→ Applying ClickHouse schema..."
curl -s \
    "http://localhost:$CLICKHOUSE_PORT/" \
    --user "$CLICKHOUSE_USER:$CLICKHOUSE_PASSWORD" \
    --data-binary @schema_clickhouse.sql
echo "✓ ClickHouse schema applied"

# Verify PostgreSQL tables
echo ""
echo "→ PostgreSQL tables:"
docker exec goaml-postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
    -c "\dt" | grep -E "accounts|entities|transactions|alerts|cases|sar|documents|screening"

# Verify ClickHouse tables
echo ""
echo "→ ClickHouse tables:"
curl -s \
    "http://localhost:$CLICKHOUSE_PORT/?query=SHOW+TABLES+FROM+goaml" \
    --user "$CLICKHOUSE_USER:$CLICKHOUSE_PASSWORD"

echo ""
echo "=================================================="
echo " Migration complete"
echo "=================================================="
