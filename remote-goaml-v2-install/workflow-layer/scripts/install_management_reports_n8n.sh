#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKFLOW_DIR="${SCRIPT_DIR%/scripts}/n8n"
DAILY_FILE="${WORKFLOW_DIR}/manager_report_daily_csv.json"
WEEKLY_FILE="${WORKFLOW_DIR}/executive_report_weekly_pdf.json"
SNAPSHOT_FILE="${WORKFLOW_DIR}/reporting_snapshot_daily.json"
DISTRIBUTION_DAILY_FILE="${WORKFLOW_DIR}/report_distribution_daily.json"
DISTRIBUTION_WEEKLY_FILE="${WORKFLOW_DIR}/report_distribution_weekly.json"
ALERTS_DAILY_FILE="${WORKFLOW_DIR}/reporting_alerts_daily.json"
DISTRIBUTION_MONTHLY_FILE="${WORKFLOW_DIR}/report_distribution_monthly.json"
DISTRIBUTION_QUARTERLY_FILE="${WORKFLOW_DIR}/report_distribution_quarterly.json"

for file in "$DAILY_FILE" "$WEEKLY_FILE" "$SNAPSHOT_FILE" "$DISTRIBUTION_DAILY_FILE" "$DISTRIBUTION_WEEKLY_FILE" "$ALERTS_DAILY_FILE" "$DISTRIBUTION_MONTHLY_FILE" "$DISTRIBUTION_QUARTERLY_FILE"; do
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
  'goAML Manager Report Daily CSV',
  'goAML Executive Report Weekly PDF',
  'goAML Reporting Snapshot Daily',
  'goAML Reporting Alerts Daily',
  'goAML Scheduled Report Distribution Daily',
  'goAML Scheduled Report Distribution Weekly',
  'goAML Scheduled Report Distribution Monthly',
  'goAML Scheduled Report Distribution Quarterly'
);
" >/dev/null

docker cp "$DAILY_FILE" goaml-n8n:/tmp/manager_report_daily_csv.json
docker cp "$WEEKLY_FILE" goaml-n8n:/tmp/executive_report_weekly_pdf.json
docker cp "$SNAPSHOT_FILE" goaml-n8n:/tmp/reporting_snapshot_daily.json
docker cp "$DISTRIBUTION_DAILY_FILE" goaml-n8n:/tmp/report_distribution_daily.json
docker cp "$DISTRIBUTION_WEEKLY_FILE" goaml-n8n:/tmp/report_distribution_weekly.json
docker cp "$ALERTS_DAILY_FILE" goaml-n8n:/tmp/reporting_alerts_daily.json
docker cp "$DISTRIBUTION_MONTHLY_FILE" goaml-n8n:/tmp/report_distribution_monthly.json
docker cp "$DISTRIBUTION_QUARTERLY_FILE" goaml-n8n:/tmp/report_distribution_quarterly.json
docker exec goaml-n8n n8n import:workflow --input=/tmp/manager_report_daily_csv.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/executive_report_weekly_pdf.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/reporting_snapshot_daily.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/report_distribution_daily.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/report_distribution_weekly.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/reporting_alerts_daily.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/report_distribution_monthly.json --projectId="${PROJECT_ID}"
docker exec goaml-n8n n8n import:workflow --input=/tmp/report_distribution_quarterly.json --projectId="${PROJECT_ID}"

docker exec goaml-postgres psql -U goaml -d goaml -c "
UPDATE workflow_entity
SET active = TRUE, \"updatedAt\" = NOW()
WHERE name IN (
  'goAML Manager Report Daily CSV',
  'goAML Executive Report Weekly PDF',
  'goAML Reporting Snapshot Daily',
  'goAML Reporting Alerts Daily',
  'goAML Scheduled Report Distribution Daily',
  'goAML Scheduled Report Distribution Weekly',
  'goAML Scheduled Report Distribution Monthly',
  'goAML Scheduled Report Distribution Quarterly'
);
" >/dev/null

docker restart goaml-n8n >/dev/null
sleep 3

docker exec goaml-postgres psql -U goaml -d goaml -At -c "
SELECT id, name, active
FROM workflow_entity
WHERE name IN (
  'goAML Manager Report Daily CSV',
  'goAML Executive Report Weekly PDF',
  'goAML Reporting Snapshot Daily',
  'goAML Reporting Alerts Daily',
  'goAML Scheduled Report Distribution Daily',
  'goAML Scheduled Report Distribution Weekly',
  'goAML Scheduled Report Distribution Monthly',
  'goAML Scheduled Report Distribution Quarterly'
)
ORDER BY name;
"
