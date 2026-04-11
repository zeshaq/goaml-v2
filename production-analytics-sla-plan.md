# Production Analytics and SLA Plan

This plan turns the current live queue analytics into persistent operational reporting that team leads, compliance operations, and auditors can actually use.

## Goal

Build production-facing SLA analytics in layers:

1. persist queue state over time
2. surface trend dashboards in the analyst UI
3. automate capture on a schedule
4. add management drilldown, breach reasons, and exportable reports

## Current Baseline

Already live:

- SAR review and approval queues
- live queue analytics and workload balancing
- SLA breach notifications
- Workflow Ops dashboard
- n8n and Camunda monitoring

Current gap:

- today’s analytics are strong for "right now"
- there is little persisted historical context for "how are we trending over time?"

## Implementation Phases

### Phase A. Historical SLA Snapshots

Deliverables:

- persist SAR queue snapshots in PostgreSQL
- add a snapshot capture endpoint
- add a trend-history endpoint
- bootstrap an initial demo-safe baseline when history is empty

Outcome:

- the platform can answer backlog, breach, and queue-age questions over time instead of only at the current moment

### Phase B. Queue Trend Dashboards

Deliverables:

- add historical trend views to:
  - SAR Review Queue
  - Workflow Ops
- show active queue backlog over time
- show breached and due-soon counts over time
- show selected-queue pressure and age trend
- add a manual `Capture Snapshot Now` action

Outcome:

- analysts and managers can see queue direction, not just queue state

### Phase C. Automated Snapshot Capture

Deliverables:

- schedule recurring snapshot capture through n8n
- retain capture cadence documentation in repo
- track whether history is live-only or still partially bootstrapped

Outcome:

- trend dashboards fill automatically without manual intervention

### Phase D. Manager and SLA Operations Analytics

Deliverables:

- queue trend drilldown by:
  - analyst
  - team
  - region
  - priority
- breach reason model
- stalled-case and stuck-workflow reporting
- trend comparison by queue stage:
  - draft
  - review
  - approval
  - filed

Outcome:

- operations leads can identify exactly where work is backing up

### Phase E. Reporting and Audit Outputs

Deliverables:

- exportable SLA reports
- weekly and monthly management summaries
- audit-ready evidence of:
  - breach events
  - assignment changes
  - notification dispatch
  - filing readiness progression

Outcome:

- the platform supports compliance reporting and management oversight directly

## First Slice Being Implemented Now

This implementation starts with:

- PostgreSQL `sar_queue_snapshots`
- `POST /api/v1/workflow/sla/snapshots/capture`
- `GET /api/v1/workflow/sla/trends`
- UI trend panels in:
  - `SAR Review Queue`
  - `Workflow Ops`

## Verification Checklist

- snapshot table exists and accepts rows
- trend endpoint returns persisted points
- empty-history environments bootstrap a visible baseline
- SAR Queue page renders historical charts
- Workflow Ops page renders operational SLA trends
- manual capture creates a fresh point and refreshes the UI

## Next After This Slice

1. n8n scheduled snapshot capture
2. team/region workload trend breakdown
3. breach reason analytics
4. management exports and audit reporting
