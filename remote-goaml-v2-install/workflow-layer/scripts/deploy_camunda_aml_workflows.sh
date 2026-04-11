#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAMUNDA_DIR="${SCRIPT_DIR%/scripts}/camunda"
CAMUNDA_URL="${CAMUNDA_URL:-http://localhost:8085/engine-rest}"

SAR_BPMN="${CAMUNDA_DIR}/goaml-sar-formal-review.bpmn"
WATCHLIST_BPMN="${CAMUNDA_DIR}/goaml-watchlist-escalation.bpmn"

if [[ ! -f "$SAR_BPMN" || ! -f "$WATCHLIST_BPMN" ]]; then
  echo "Camunda BPMN files are missing under ${CAMUNDA_DIR}" >&2
  exit 1
fi

deploy_file() {
  local deployment_name="$1"
  local file_path="$2"
  local field_name
  field_name="$(basename "$file_path")"
  curl -fsS -X POST "${CAMUNDA_URL}/deployment/create" \
    -F "deployment-name=${deployment_name}" \
    -F "deploy-changed-only=true" \
    -F "enable-duplicate-filtering=true" \
    -F "${field_name}=@${file_path};type=text/xml"
  echo
}

echo "Deploying goAML Camunda workflows..."
deploy_file "goAML SAR Formal Review" "$SAR_BPMN"
deploy_file "goAML Watchlist Escalation" "$WATCHLIST_BPMN"

echo "Latest process definitions:"
curl -fsS "${CAMUNDA_URL}/process-definition?latestVersion=true" | tr -d '\n'
echo
