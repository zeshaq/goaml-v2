#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_DIR="${SCRIPT_DIR%/scripts}/n8n"
PLAYBOOK_FILE="${WORKFLOW_DIR}/playbook_compliance_daily.json"

if [[ ! -f "$PLAYBOOK_FILE" ]]; then
  echo "Workflow definition file is missing: ${PLAYBOOK_FILE}" >&2
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
  'goAML Playbook Compliance Automation Daily'
);
" >/dev/null

docker cp "$PLAYBOOK_FILE" goaml-n8n:/tmp/playbook_compliance_daily.json
docker exec goaml-n8n n8n import:workflow --input=/tmp/playbook_compliance_daily.json --projectId="${PROJECT_ID}"

docker exec goaml-postgres psql -U goaml -d goaml -c "
UPDATE workflow_entity
SET active = TRUE, \"updatedAt\" = NOW()
WHERE name IN (
  'goAML Playbook Compliance Automation Daily'
);
" >/dev/null

docker restart goaml-n8n >/dev/null
sleep 3

docker exec goaml-postgres psql -U goaml -d goaml -At -c "
SELECT id, name, active
FROM workflow_entity
WHERE name IN (
  'goAML Playbook Compliance Automation Daily'
)
ORDER BY name;
"
