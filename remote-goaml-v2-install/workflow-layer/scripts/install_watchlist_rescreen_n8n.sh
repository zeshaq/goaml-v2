#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_DIR="${SCRIPT_DIR%/scripts}/n8n"

DAILY_FILE="${WORKFLOW_DIR}/watchlist_rescreen_daily_due.json"
WEEKLY_FILE="${WORKFLOW_DIR}/watchlist_rescreen_weekly_full.json"

if [[ ! -f "$DAILY_FILE" || ! -f "$WEEKLY_FILE" ]]; then
  echo "Workflow definition files are missing under ${WORKFLOW_DIR}" >&2
  exit 1
fi

PROJECT_ID="$(docker exec goaml-postgres psql -U goaml -d goaml -Atqc "select id from project where type = 'personal' order by id limit 1;")"
if [[ -z "${PROJECT_ID}" ]]; then
  echo "Could not determine the target n8n project id" >&2
  exit 1
fi

docker exec goaml-postgres psql -U goaml -d goaml -v ON_ERROR_STOP=1 -c "
DELETE FROM workflow_entity
WHERE name IN (
  'goAML Watchlist Re-screen Daily Due',
  'goAML Watchlist Re-screen Weekly Full'
);
"

docker cp "$DAILY_FILE" goaml-n8n:/tmp/watchlist_rescreen_daily_due.json
docker cp "$WEEKLY_FILE" goaml-n8n:/tmp/watchlist_rescreen_weekly_full.json

docker exec goaml-n8n n8n import:workflow --input=/tmp/watchlist_rescreen_daily_due.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/watchlist_rescreen_weekly_full.json --projectId="${PROJECT_ID}"

docker exec goaml-postgres psql -U goaml -d goaml -v ON_ERROR_STOP=1 -c "
UPDATE workflow_entity
SET active = true, \"updatedAt\" = CURRENT_TIMESTAMP
WHERE name IN (
  'goAML Watchlist Re-screen Daily Due',
  'goAML Watchlist Re-screen Weekly Full'
);
"

docker restart goaml-n8n >/dev/null

sleep 5

docker exec goaml-postgres psql -U goaml -d goaml -c "
SELECT id, name, active
FROM workflow_entity
WHERE name IN (
  'goAML Watchlist Re-screen Daily Due',
  'goAML Watchlist Re-screen Weekly Full'
)
ORDER BY name;
"
