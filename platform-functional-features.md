# goAML-v2 Functional Features of the Full Platform

> Functional feature inventory for the full goAML-v2 platform, organized by business capability and platform layer.

## 1. Purpose

This document is the functional feature map for the entire platform.

Use it when you need to answer:

- what the platform can do
- which features are already live
- where capabilities sit across app, workflow, data, and model layers

## 2. Investigation and Operations Features

### Alerts

- alert ingestion and listing
- alert detail view
- alert note history
- closed-loop alert feedback
- investigate
- dismiss
- false positive
- escalate
- linked case creation / reopen
- bulk triage
- saved alert views
- bulk-action preview
- queue next / previous navigation
- note templates
- keyboard shortcuts

### Cases

- case creation
- case listing
- case detail
- case update
- case timeline / events
- case notes
- case tasks
- task updates
- AI summary generation
- filing readiness
- workflow state tracking

### Case Command Center

- default case-open experience
- overview tab
- evidence tab
- graph tab
- documents tab
- timeline tab
- SAR tab
- pinned evidence board
- filing readiness panel
- AI-used evidence panel
- closed-loop case quality feedback

### SAR Workflow

- SAR draft generation
- SAR preview
- submit for review
- approve
- reject
- file
- reviewer queue
- approver queue
- saved SAR views
- bulk SAR actions
- filing pack generation
- filing pack export

## 3. Intelligence Features

### Documents

- document upload
- OCR
- parse
- PII extraction
- embeddings
- vector indexing
- raw object storage in MinIO
- case attach
- graph candidate extraction
- duplicate candidates
- related documents
- provenance trail
- filing-pack impact visibility

### Retrieval and RAG

- semantic retrieval from Milvus
- reranking
- case context assembly
- grounded evidence-aware AI summary
- grounded evidence-aware SAR draft

### Graph

- persisted Neo4j sync
- graph explore
- graph drilldown
- graph pathfinding
- graph evidence in alert/case/entity/transaction workflows

### Screening

- sanctions screening
- screening result persistence
- screening-linked graph visibility
- watchlist support

### Entity Operations

- entity profile
- entity graph evidence
- watchlist dashboard
- watchlist case creation
- watchlist removal
- entity merge workflow
- merge impact handling
- network risk score
- watch patterns
- graph-driven recommendations

## 4. Playbook and Guided Investigation Features

### Typology Playbooks

- structuring
- sanctions match
- layering
- PEP exposure
- large cash
- crypto mixing

### Checklist and Rules

- checklist progress
- blocked steps
- required evidence rules
- per-priority SLA targets
- auto-generated case tasks

### Playbook Analytics

- compliance by typology
- typology outcomes
- most missed steps
- blocked-step trends
- team playbook performance
- region playbook performance
- worst offending step heatmaps

### Playbook Automation

- stuck checklist automation
- evidence-gap escalation
- recurring n8n automation
- manager tuning of thresholds

## 5. Queue, Inbox, and Productivity Features

### Analyst Inbox

- notification center
- work item list
- bulk inbox actions
- desk deep links
- presets

### Saved Views and Bulk Actions

- saved alert views
- saved SAR views
- role defaults
- team presets
- bulk triage
- bulk queue actions
- bulk-action preview
- queue navigation helpers
- action note templates

### Manager Console

- queue filters
- backlog heatmap
- workload board
- mass reassignment
- saved manager workspaces
- balancing rules
- intervention suggestions
- playbook hotspot views
- SLA and intervention tuning
- management outcome visibility

## 6. Workflow and Automation Features

### Workflow Control

- n8n monitor
- Camunda monitor
- Workflow Ops page
- notification event history
- workflow overview
- workflow exceptions
- guided states
- exception intervention actions

### Scheduled Automation

- watchlist re-screen daily
- watchlist re-screen weekly
- SAR queue rebalance
- scorer drift monitor
- scorer challenger evaluation
- playbook compliance automation
- manager report daily CSV
- executive report weekly PDF

### Formal Orchestration

- Camunda SAR formal review flow
- Camunda watchlist escalation flow

## 7. Model and Risk Features

### Transaction Scoring

- XGBoost risk scoring
- scorer lineage on transactions
- model metadata propagation

### MLflow Governance

- model registration
- evaluation gates
- approval workflow
- promotion
- deploy
- rollback
- version catalog
- tuning recommendations
- governance handoff

### Monitoring

- champion/challenger evaluation
- drift baseline capture
- drift observation
- monitoring automation
- model alerts
- outcome analytics by model version

## 8. Reporting and Oversight Features

### Reporting Studio

- SLA history
- review trend
- operational funnel
- owner workload distribution
- playbook compliance analytics
- team/region performance
- hotspot heatmaps
- executive KPI layer
- monthly operational summary
- typology mix
- watchlist and screening posture
- model and workflow health summary
- playbook effectiveness by typology and priority
- false-positive reporting by team, typology, and owner
- case-to-SAR and filed SAR outcome reporting
- backlog aging and breach trends
- persisted reporting snapshots for audit-friendly trend history
- daily, weekly, and monthly reporting snapshot cadences
- period-over-period movement analytics
- executive drilldowns from KPI to typology, team / region, and case set
- historical-period drilldowns and exports from a selected snapshot
- threshold-based reporting alerts
- manager action recommendations
- board-level reporting summaries
- reporting alert threshold settings
- scheduled report distribution rules
- compliance oversight reporting for review lag, approval lag, filing timeliness, audit-trail completeness, and evidence-pack completeness
- outcome correlation layer tied to model version, workflow delay, and playbook compliance
- workflow effectiveness analytics for SAR rebalance, playbook automation, and watchlist re-screen
- decision-quality dashboard
- closed-loop feedback signal board
- decision-quality snapshot history
- decision-quality period-over-period movement
- decision-quality drilldowns by typology, team, region, and feedback key
- quality-tuning recommendations
- reviewer-quality analytics
- exportable branded management reporting in JSON, CSV, PDF, and DOCX
- audience-specific report packs for `manager`, `executive`, `compliance`, and `board`

### Workflow Ops

- SLA summary
- notification posture
- playbook automation monitor
- model alert monitor
- reporting alert monitor
- manager recommendation monitor
- scheduled reporting monitor
- decision-quality intervention monitor
- decision-quality recommendation automation monitor

### Model Ops

- registry status
- deployment state
- governance history
- monitoring posture
- version outcomes
- scorer business impact by version and typology

### Decision Quality and Feedback

- alert precision by typology
- case escalation quality
- SAR quality proxies
- true-positive trend by workflow
- true-positive trend by model version
- stored decision-feedback records
- feedback signals from alerts and cases
- feedback-to-action automation for noisy-alert hotspots, weak SAR drafts, and missing evidence
- recurring recommendation automation for repeated noisy typologies and drafter-quality hotspots
- drafter rejection and rework analytics
- approval-to-filing lag analytics by team and typology

## 9. Authentication and Access Features

### Current Local Auth

- login
- logout
- JWT session
- profile page
- password change
- local users
- local roles
- desk gating
- permission checks
- auth audit support

### Future-Ready Identity Surface

- WSO2/OIDC settings forms in product settings
- provider metadata model already present

## 10. Platform and Admin Features

### Admin Surfaces

- Settings
- Platform Ops
- n8n monitor
- Camunda monitor
- Model Ops
- Manager Console

### Supporting Service UIs

- Superset
- Neo4j Browser
- Attu
- MinIO Console
- MLflow

## 11. Current Scope Summary

The platform currently delivers:

- analyst workflow
- reviewer / approver workflow
- manager queue control
- document and graph intelligence
- AI-assisted investigation
- model governance
- workflow automation

Still mostly future-facing:

- external identity provider cutover
- deeper row-level work partitioning
- final enterprise hardening

## 12. Related Docs

- [goaml-v2-project-overview-v3.md](/Users/ze/Documents/goaml-v2/goaml-v2-project-overview-v3.md)
- [implementation-plan-v3.md](/Users/ze/Documents/goaml-v2/implementation-plan-v3.md)
- [end-user-manual.md](/Users/ze/Documents/goaml-v2/end-user-manual.md)
- [product-feature-document.md](/Users/ze/Documents/goaml-v2/product-feature-document.md)
- [admin-manual.md](/Users/ze/Documents/goaml-v2/admin-manual.md)
