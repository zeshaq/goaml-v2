# Case Command Center Implementation Tasks

> Status: implemented and deployed on `2026-04-11`. This document now serves as the historical task breakdown for the Command Center work that is live on `goaml-v2`.

## Objective

This Command Center initiative was completed by doing two things:

1. make the Command Center the default case-open experience everywhere
2. evolve the current low-fidelity prototype into a higher-fidelity investigation workspace with:
   - tabs
   - pinned evidence
   - a dedicated filing-readiness panel

This document remains broken down into backend, frontend, and workflow/orchestration work so a future engineer can see exactly what was delivered and what the natural follow-ons are.

## Current State

Implemented and live today:

- Command Center is the default case-open experience across case-linked flows
- tabbed center workspace:
  - `Overview`
  - `Evidence`
  - `Graph`
  - `Documents`
  - `Timeline`
  - `SAR`
- persistent right rail with:
  - filing readiness
  - action rail
  - case-specific workflow state
  - SAR preview
- case workspace aggregation APIs
- pinned evidence model and endpoints
- case-specific workflow state, process history, and deeplinked notifications
- reviewer-grade SAR editing and narrative comparison
- routed workload, SLA views, n8n dashboards, and Camunda dashboards
- graph evidence, document intelligence, watchlist escalation, and SAR review queues

Residual follow-ons after completion:

- pinned evidence is not yet fed directly into summary and SAR prompt composition
- filing-readiness snapshots are computed on demand, not stored historically
- specialist exports such as filing-ready evidence packs are still future work
- classic timeline is still available as a fallback path for transition/debug use

## Delivery Strategy

The implementation was delivered in four slices:

1. navigation and routing default
2. backend aggregation and readiness primitives
3. high-fidelity Command Center UI
4. workflow-aware reviewer polish

Each slice was kept deployable on its own, which is why the Command Center could be expanded live without breaking the older case workspace.

## Implemented Outcomes

### Backend Outcomes

Delivered:

- `GET /api/v1/cases/{case_id}/workspace`
- `GET /api/v1/cases/{case_id}/workflow`
- `GET /api/v1/cases/{case_id}/filing-readiness`
- `GET /api/v1/cases/{case_id}/evidence`
- `POST /api/v1/cases/{case_id}/evidence/pin`
- `PATCH /api/v1/cases/{case_id}/evidence/{evidence_id}`
- `DELETE /api/v1/cases/{case_id}/evidence/{evidence_id}`
- `PATCH /api/v1/cases/{case_id}/sar`
- persisted `case_evidence` support in PostgreSQL
- case-scoped workflow payloads with:
  - expected role
  - process history
  - latest automation touches
  - quick links

### Frontend Outcomes

Delivered:

- Command Center as the primary case-open route
- classic timeline retained as secondary fallback
- tabbed high-fidelity workspace
- pinned evidence board and evidence controls
- filing-readiness panel with jump-to-tab actions
- case-specific workflow rail with deeplinked notifications
- reviewer-grade SAR workspace with:
  - editable structured fields
  - draft-save path
  - evidence-in-filing view
  - narrative comparison
- hash/deeplink routing for `/#case-command?case=...`

### Workflow Outcomes

Delivered:

- Command Center workflow state now mirrors live Camunda state closely enough for daily use
- workflow notifications can jump directly back into the correct case workspace
- right-rail quick actions now expose:
  - `Open Workflow Ops`
  - `Open n8n Monitor`
  - `Open Camunda`

## Backend Tasks

## 1. Case Workspace Aggregation

### Goal

Create one API response that gives the frontend the full case workspace model in a stable shape.

### Tasks

- Add `GET /api/v1/cases/{case_id}/workspace`
- Return:
  - case header
  - routing
  - assignment
  - SLA state
  - linked alerts
  - linked transactions
  - direct documents
  - retrieved documents
  - screening hits
  - graph summary
  - graph relationship evidence
  - graph path defaults
  - notes
  - tasks
  - SAR state
  - workflow summary
  - Camunda state
  - recent notifications
  - AI summary and risk factors
  - filing readiness snapshot
- Reuse existing services where possible instead of duplicating logic
- Keep existing endpoints intact so the old case page does not break

### Acceptance Criteria

- frontend can load one case workspace with one primary API call plus optional graph/path interactions
- response shape is consistent even when some subsystems have no data

## 2. Pinned Evidence Model

### Goal

Allow analysts and reviewers to explicitly mark evidence as important for investigation and filing.

### Tasks

- Choose storage strategy:
  - preferred: add a `case_evidence` table
  - fallback: store in `cases.metadata.pinned_evidence`
- Support evidence types:
  - alert
  - transaction
  - document
  - screening_hit
  - graph_finding
  - note-derived evidence
- Add fields:
  - `case_id`
  - `evidence_type`
  - `evidence_id`
  - `title`
  - `summary`
  - `source`
  - `importance`
  - `pinned_by`
  - `pinned_at`
  - `include_in_sar`
  - `metadata`
- Add endpoints:
  - `GET /api/v1/cases/{case_id}/evidence`
  - `POST /api/v1/cases/{case_id}/evidence/pin`
  - `PATCH /api/v1/cases/{case_id}/evidence/{evidence_id}`
  - `DELETE /api/v1/cases/{case_id}/evidence/{evidence_id}`

### Acceptance Criteria

- an analyst can pin any important item from the case workspace
- pinned evidence survives refresh and appears in a dedicated section
- SAR workspace can distinguish all evidence from filing evidence

## 3. Filing Readiness Engine

### Goal

Make filing readiness explicit and reviewable rather than implicit.

### Tasks

- Add `GET /api/v1/cases/{case_id}/filing-readiness`
- Compute readiness dimensions:
  - case assigned
  - status appropriate for filing stage
  - SAR exists
  - SAR narrative exists
  - reviewer note present
  - approver state valid
  - required evidence pinned
  - minimum evidence diversity satisfied
  - screening reviewed
  - graph review completed
  - documents reviewed
  - filing reference provided or auto-generatable
- Return:
  - `overall_status`
  - `score`
  - `blocking_items`
  - `warning_items`
  - `passed_checks`
  - `recommended_next_actions`

### Acceptance Criteria

- reviewers can tell instantly why a case is or is not ready to file
- file action can optionally use readiness status to warn or block

## 4. Case-Specific Workflow State

### Goal

Expose workflow state scoped to a single case so the Command Center does not need to infer it from global ops views.

### Tasks

- Add `GET /api/v1/cases/{case_id}/workflow`
- Include:
  - routing metadata
  - owner load snapshot
  - SLA status and due date
  - notification history for that case
  - active Camunda process
  - active Camunda task
  - process history summary
  - latest n8n touches relevant to the case if available

### Acceptance Criteria

- workflow panel no longer depends on scanning global workflow payloads
- case-specific task and process state is cleanly isolated

## 5. Optional Summary Improvements

### Goal

Let pinned evidence feed AI outputs later.

### Tasks

- add optional `use_pinned_evidence_only` or `prioritize_pinned_evidence` in case summary and SAR generation services
- do not block current drafting flow on this

## Frontend Tasks

## 1. Make Command Center the Default Open Path

### Goal

Every case-open action should land in the Command Center unless a user explicitly asks for the classic page.

### Tasks

- replace case row primary action with `openCaseCommandCenter`
- update:
  - case list rows
  - alert investigation case opens
  - screening case creation opens
  - SAR queue `Open case workspace`
  - watchlist-linked case opens
  - entity profile related case opens
  - graph evidence case pivots
- keep a secondary `Classic workspace` button for fallback during transition

### Acceptance Criteria

- analysts reach the Command Center by default from all case-entry points
- classic page remains accessible during rollout

## 2. Command Center Information Architecture Upgrade

### Goal

Move from a long prototype page to a higher-fidelity structured workspace.

### Tasks

- introduce tabs in the center workspace:
  - `Overview`
  - `Evidence`
  - `Graph`
  - `Documents`
  - `Timeline`
  - `SAR`
- keep the right rail persistent across tabs
- keep header sticky
- maintain responsive fallback for tablet/mobile

### Acceptance Criteria

- case review feels navigable instead of scroll-heavy
- the most common evidence and action flows take fewer clicks than today

## 3. Pinned Evidence UX

### Goal

Make important evidence visible and actionable.

### Tasks

- add `Pin evidence` buttons to:
  - linked alerts
  - transactions
  - direct documents
  - retrieved documents
  - screening hits
  - graph relationship evidence
- add a dedicated `Pinned Evidence` panel in `Overview`
- allow:
  - reorder by importance
  - mark `include in SAR`
  - remove pin
- visually separate:
  - all evidence
  - pinned evidence
  - filing evidence

### Acceptance Criteria

- pinned evidence appears immediately after action
- reviewers can tell what the analyst thinks matters most

## 4. Filing Readiness Panel

### Goal

Create a clear reviewer/approver decision surface.

### Tasks

- add a dedicated `Filing Readiness` card in the right rail or SAR tab
- show:
  - readiness score
  - blockers
  - warnings
  - passed checks
  - next recommended action
- color-code:
  - blocked
  - needs review
  - ready
- link blockers to their relevant UI areas
  - missing reviewer note -> SAR tab
  - no pinned evidence -> Evidence tab
  - no attached document -> Documents tab

### Acceptance Criteria

- a reviewer can explain why a case is blocked by reading one panel
- the `File SAR` action can display readiness context inline

## 5. Higher-Fidelity Reviewer Workspace

### Goal

Make the screen reviewer-grade, not just analyst-grade.

### Tasks

- add a dedicated `Reviewer Notes` section separate from analyst notes
- add `Approver Notes`
- add `Evidence Included in Filing`
- add a `compare draft vs final` presentation for SAR narrative
- show current Camunda task in the SAR header

### Acceptance Criteria

- reviewer and approver roles can work from the same page without confusion

## 6. Transition and Usability Polish

### Goal

Make the new default feel intentional.

### Tasks

- add subtle first-load helper text:
  - where evidence lives
  - how to use tabs
  - where filing readiness appears
- preserve keyboard focus when tabs change
- persist last-opened tab per case in session memory
- add loading skeletons for workspace panels

## Workflow and Orchestration Tasks

## 1. Align Camunda to the New Reviewer Experience

### Goal

Ensure the Command Center presents the formal workflow state in a way that mirrors Camunda.

### Tasks

- expose clearer mapping from:
  - case status
  - SAR status
  - Camunda task
  - filing readiness
- include current human task label and expected role in case workflow API
- make review buttons display the active process step

### Acceptance Criteria

- the UI workflow story matches the Camunda process state without ambiguity

## 2. Notification-to-Workspace Links

### Goal

Let ops and reviewers jump directly into the right case context.

### Tasks

- include case command center deeplinks in:
  - SLA notifications
  - watchlist escalation notifications
  - future email/Slack notifications
- update notification history rendering to surface the deeplink later when channels are configured

## 3. n8n and Camunda Visibility from the Case

### Goal

Keep specialist tooling visible without forcing context switching.

### Tasks

- add right-rail quick actions:
  - `Open Workflow Ops`
  - `Open n8n Monitor`
  - `Open Camunda`
- add case-specific process summary from orchestration tables
- show last notification event for the case

## Data and Model Considerations

## Database Changes

Implement one of:

- preferred:
  - new `case_evidence` table
  - optional `case_readiness_snapshots` table later
- acceptable first pass:
  - extend `cases.metadata`

Preferred because:

- easier querying
- cleaner audit trail
- less metadata blob drift

## Model/AI Changes

Not required for first Command Center release, but strongly recommended in the next pass:

- prioritize pinned evidence in AI case summary generation
- prioritize pinned evidence in SAR drafting
- generate a short `why this evidence matters` text for pinned items

## Rollout Outcome

## Phase 1

Completed:

- backend `workspace`, `evidence`, and `filing-readiness` APIs landed first
- old case behavior remained intact during rollout

## Phase 2

Completed:

- built the higher-fidelity tabbed Command Center
- kept the classic case page available as fallback

## Phase 3

Completed:

- made the Command Center the default everywhere practical
- left the classic page as fallback

## Phase 4

Current posture:

- classic-entry behavior is no longer primary
- classic workspace remains available for transition/debug use

## Suggested Build Order

1. backend `workspace` endpoint
2. backend pinned evidence support
3. backend filing readiness endpoint
4. frontend tabs and workspace composition
5. frontend pinned evidence actions
6. frontend filing readiness panel
7. switch default case open behavior everywhere
8. workflow polish and deeplinks

## Completion Check

This initiative is complete when:

- every case entry path opens the Command Center by default
- the Command Center is tabbed and not overly scroll-heavy
- analysts can pin evidence directly from the workspace
- reviewers can see a dedicated filing-readiness panel
- Camunda state is clearly visible inside the case
- the classic case page becomes optional rather than primary

Current status:

- achieved

## Risks and Mitigations

### Risk

The frontend becomes overly dependent on many separate API calls.

### Mitigation

Prioritize the `workspace` endpoint first.

### Risk

Pinned evidence semantics become messy across alerts, docs, graph findings, and screening hits.

### Mitigation

Use a normalized evidence model early.

### Risk

Readiness rules become too rigid before policy decisions are finalized.

### Mitigation

Start with warnings plus optional hard blockers only for essential SAR states.

## Recommended Next Step After Completion

The strongest follow-ons now are:

1. prioritize pinned evidence in AI summary and SAR prompt composition
2. add filing-ready evidence packs and export surfaces
3. deepen reviewer automation and workflow orchestration on top of the completed Command Center
