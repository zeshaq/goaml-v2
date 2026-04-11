#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_DIR="${SCRIPT_DIR%/scripts}/n8n"
WORKFLOW_FILE="${WORKFLOW_DIR}/sar_queue_rebalance_daily.json"

if [[ ! -f "$WORKFLOW_FILE" ]]; then
  echo "Workflow definition file is missing: ${WORKFLOW_FILE}" >&2
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
  'goAML SAR Queue Rebalance Daily'
);
"

docker cp "$WORKFLOW_FILE" goaml-n8n:/tmp/sar_queue_rebalance_daily.json
docker exec goaml-n8n n8n import:workflow --input=/tmp/sar_queue_rebalance_daily.json --projectId="${PROJECT_ID}"

docker exec goaml-postgres psql -U goaml -d goaml -v ON_ERROR_STOP=1 -c "
UPDATE workflow_entity
SET active = true, \"updatedAt\" = CURRENT_TIMESTAMP
WHERE name IN (
  'goAML SAR Queue Rebalance Daily'
);
"

docker restart goaml-n8n >/dev/null
sleep 5

docker exec goaml-postgres psql -U goaml -d goaml -c "
SELECT id, name, active
FROM workflow_entity
WHERE name IN (
  'goAML SAR Queue Rebalance Daily'
)
ORDER BY name;
"
