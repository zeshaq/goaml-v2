# ─────────────────────────────────────────
# goAML-V2 — Workflow Layer Environment
# ─────────────────────────────────────────

# PostgreSQL (shared from storage layer)
# RAW password (not URL-encoded) — n8n and Camunda handle encoding internally
POSTGRES_USER=goaml
POSTGRES_PASSWORD_RAW=Asdf@1234
POSTGRES_DB=goaml

# Redis (shared from storage layer)
REDIS_PASSWORD=Asdf@1234

# n8n encryption key — used to encrypt credentials stored in DB
# Generate with: openssl rand -hex 32
#N8N_ENCRYPTION_KEY=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
N8N_ENCRYPTION_KEY=d6d69a9c7ba4c9aa685d1acbf5e20a1cbc923425cdad14f452206228eda8a82a
