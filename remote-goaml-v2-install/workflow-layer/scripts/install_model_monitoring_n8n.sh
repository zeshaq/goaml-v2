#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_DIR="${SCRIPT_DIR%/scripts}/n8n"
DRIFT_FILE="${WORKFLOW_DIR}/scorer_drift_monitor_daily.json"
CHALLENGER_FILE="${WORKFLOW_DIR}/scorer_challenger_weekly.json"

for file in "$DRIFT_FILE" "$CHALLENGER_FILE"; do
  if [[ ! -f "$file" ]]; then
    echo "Workflow definition file is missing: ${file}" >&2
    exit 1
  fi
done

PROJECT_ID="$(docker exec goaml-postgres psql -U goaml -d goaml -At -c "select id from project where type = 'personal' order by \"createdAt\" asc limit 1")"
if [[ -z "$PROJECT_ID" ]]; then
  echo "Could not determine the target n8n project id" >&2
  exit 1
fi

docker exec goaml-postgres psql -U goaml -d goaml -c "
DELETE FROM workflow_entity
WHERE name IN (
  'goAML Scorer Drift Monitor Daily',
  'goAML Scorer Challenger Weekly'
);
" >/dev/null

docker cp "$DRIFT_FILE" goaml-n8n:/tmp/scorer_drift_monitor_daily.json
docker cp "$CHALLENGER_FILE" goaml-n8n:/tmp/scorer_challenger_weekly.json
docker exec goaml-n8n n8n import:workflow --input=/tmp/scorer_drift_monitor_daily.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/scorer_challenger_weekly.json --projectId="${PROJECT_ID}"

docker exec goaml-postgres psql -U goaml -d goaml -c "
UPDATE workflow_entity
SET active = TRUE, \"updatedAt\" = NOW()
WHERE name IN (
  'goAML Scorer Drift Monitor Daily',
  'goAML Scorer Challenger Weekly'
);
" >/dev/null

docker restart goaml-n8n >/dev/null
sleep 3

docker exec goaml-postgres psql -U goaml -d goaml -At -c "
SELECT id, name, active
FROM workflow_entity
WHERE name IN (
  'goAML Scorer Drift Monitor Daily',
  'goAML Scorer Challenger Weekly'
)
ORDER BY name;
"
