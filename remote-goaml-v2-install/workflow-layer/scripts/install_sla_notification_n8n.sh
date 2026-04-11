#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_DIR="${SCRIPT_DIR%/scripts}/n8n"
WORKFLOW_FILE="${WORKFLOW_DIR}/sla_breach_notifications_daily.json"

if [[ ! -f "$WORKFLOW_FILE" ]]; then
  echo "Workflow definition file is missing: ${WORKFLOW_FILE}" >&2
  exit 1
fi

PROJECT_ID="$(docker exec goaml-postgres psql -U goaml -d goaml -At -c "select id from project where type = 'personal' order by \"createdAt\" asc limit 1")"
if [[ -z "$PROJECT_ID" ]]; then
  echo "Could not determine the target n8n project id" >&2
  exit 1
fi

docker exec goaml-postgres psql -U goaml -d goaml -c "
DELETE FROM workflow_entity
WHERE name IN (
  'goAML SAR SLA Notifications Daily'
);
" >/dev/null

docker cp "$WORKFLOW_FILE" goaml-n8n:/tmp/sla_breach_notifications_daily.json
docker exec goaml-n8n n8n import:workflow --input=/tmp/sla_breach_notifications_daily.json --projectId="${PROJECT_ID}"

docker exec goaml-postgres psql -U goaml -d goaml -c "
UPDATE workflow_entity
SET active = TRUE, \"updatedAt\" = NOW()
WHERE name IN (
  'goAML SAR SLA Notifications Daily'
);
" >/dev/null

docker restart goaml-n8n >/dev/null
sleep 3

docker exec goaml-postgres psql -U goaml -d goaml -At -c "
SELECT id, name, active
FROM workflow_entity
WHERE name IN (
  'goAML SAR SLA Notifications Daily'
)
ORDER BY name;
"
