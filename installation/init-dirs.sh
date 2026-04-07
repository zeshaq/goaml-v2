#!/bin/bash
# =============================================================================
# goAML-V2 — Volume directory initialiser
# Run once before: docker compose up
# Usage: bash init-dirs.sh
# =============================================================================
BASE=/home/ze/goaml-v2

dirs=(
  # Storage
  postgres/data postgres/init
  clickhouse/data clickhouse/logs clickhouse/config
  redis/data
  # Graph + Vector
  neo4j/data neo4j/logs neo4j/import neo4j/plugins
  milvus/etcd milvus/minio milvus/data
  # Docs
  opensanctions/data
  # NIM shared cache
  nim-cache
  # Triton
  triton/models triton/logs
  # Agent
  mlflow/artifacts
  # Workflow
  n8n/data
  camunda/config camunda/deployments
  # App
  superset/config superset/data
  fastapi/app
  nginx/conf nginx/ssl nginx/logs
)

for d in "${dirs[@]}"; do
  mkdir -p "$BASE/$d"
done

echo "All directories created under $BASE"
