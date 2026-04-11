# goAML-v2 Admin Manual

> Administrator and operator manual for the live goAML-v2 platform, covering service access, operational responsibilities, product settings, workflow/admin surfaces, and change management.

## 1. Purpose

This manual is for:

- admins
- workflow ops
- model ops
- platform operators
- implementation owners

It explains:

- what is running
- where to administer it
- how to use admin desks
- what to watch operationally

## 2. Deployment Overview

App/control plane:

- host: `160.30.63.131`
- primary path: `/home/ze/goaml-v2`

Inference/model plane:

- host: `160.30.63.152`

Local deployment mirrors:

- [remote-goaml-v2-install](/Users/ze/Documents/goaml-v2/remote-goaml-v2-install)
- [remote-gpu-01-models](/Users/ze/Documents/goaml-v2/remote-gpu-01-models)

## 3. Core Service Inventory

App host services:

- FastAPI
- React UI
- Nginx
- PostgreSQL
- ClickHouse
- Redis
- Neo4j
- Milvus
- MinIO
- Yente
- Elasticsearch
- Tika
- n8n
- Camunda
- LangGraph
- MLflow

GPU host services:

- Qwen primary
- Qwen fast
- Embed
- Rerank
- Parse
- OCR
- PII
- Scorer

## 4. Admin-Facing UIs

Key admin and operations UIs:

- Analyst UI: `http://160.30.63.131/`
- Superset: `http://160.30.63.131:8088`
- n8n: `http://160.30.63.131:5678`
- Camunda: `http://160.30.63.131:8085/camunda/app/`
- Neo4j Browser: `http://160.30.63.131:7474`
- Attu: `http://160.30.63.131:8080`
- MinIO Console: `http://160.30.63.131:9001`
- MLflow: `http://160.30.63.131:5000`

Sensitive current credentials are documented in:

- [goaml-v2-project-overview-v3.md](/Users/ze/Documents/goaml-v2/goaml-v2-project-overview-v3.md)

## 5. Local Authentication Administration

Current auth mode:

- local auth
- JWT sessions
- RBAC desk gating

Admin capabilities in the product:

- view auth providers
- view local auth config
- view WSO2-ready provider form
- manage local users
- inspect auth audit history

Current note:

- WSO2 settings exist in the UI for later adoption
- local auth is the active mode today

## 6. Seeded Roles and Users

Roles:

- analyst
- reviewer
- approver
- manager
- sanctions analyst
- model ops
- workflow ops
- auditor
- admin

Seed users:

- `analyst1`
- `reviewer1`
- `approver1`
- `manager1`
- `sanctions1`
- `modelops1`
- `workflowops1`
- `auditor1`
- `admin1`

Bootstrap password:

- `Goaml!2026`

## 7. Manager and Operations Surfaces

### 7.1 Manager Console

Used for:

- queue filtering
- mass reassignment
- saved manager workspaces
- balancing rules
- intervention suggestions
- backlog heatmap
- workload board
- playbook tuning
- intervention tuning
- hotspot visibility
- management outcome visibility
- decision-quality posture visibility

### 7.2 Workflow Ops

Used for:

- notification history
- workflow exceptions
- guided-state visibility
- playbook automation monitor
- model alert monitor
- reporting alert monitor
- manager recommendation monitor
- manual workflow triggers
- n8n and Camunda visibility
- scheduled report workflow visibility
- downstream feedback-driven quality issues surfaced through reporting and inbox signals

### 7.3 Model Ops

Used for:

- scorer metadata
- model registry
- evaluation gates
- approval workflow
- deploy / rollback
- champion / challenger
- drift monitoring
- scorer business impact by version and typology
- tuning recommendations
- governance handoff from tuning recommendations into the model-governance lane

### 7.4 Reporting Studio

Reporting Studio now also carries quality-governance surfaces:

- `Decision Quality Dashboard`
- `Closed-loop Feedback Signals`
- historical visibility into feedback-driven quality posture through the management reporting API
- decision-quality drilldowns into the affected case set by typology, team, region, and feedback key
- quality-tuning recommendations for threshold/playbook/SAR-guidance changes
- reviewer-quality analytics for drafter rejection/rework, evidence completeness, and approval-to-filing lag
- persisted decision-quality snapshot history and period-over-period movement boards for historical quality review
- recurring quality recommendation automation for noisy typologies and drafter coaching hotspots

Operational note:

- closed-loop feedback is stored in PostgreSQL in `decision_feedback`
- case-linked feedback also writes a `decision_feedback_added` event into `case_events`

### 7.5 Document and Entity Intelligence Overlays

Additional admin-visible intelligence surfaces now include:

- document duplicate candidates
- related-document visibility
- provenance and filing-pack impact on document detail
- entity network risk scoring
- watch-pattern summaries
- graph-driven entity recommendations

## 8. Workflow Administration

Current recurring automation areas:

- watchlist re-screen
- SAR queue rebalance
- scorer drift monitor
- scorer challenger evaluation
- playbook compliance automation
- manager report daily CSV
- executive report weekly PDF
- reporting alerts daily
- decision-quality intervention automation on demand from Workflow Ops
- decision-quality recommendation automation on demand from Workflow Ops
- board report monthly PDF
- board report quarterly DOCX

n8n holds the timed recurring jobs.

Camunda holds formal review/escalation processes.

Inside the product, use:

- `Workflow Ops`
- `n8n Monitor`
- `Camunda`
- `Reporting Studio` for on-demand exports
- `Reporting Studio` for reporting automation settings and audience-specific export templates

## 9. Playbook Administration

Playbooks now support:

- typology-specific checklist steps
- required evidence rules
- per-priority SLA targets
- case backfill
- intervention tuning thresholds

Manager-configurable intervention settings:

- stuck checklist threshold
- evidence-gap warning window
- automation cooldown
- cases per run

## 10. Model Governance Administration

Scorer lifecycle currently supports:

- register current
- evaluate
- submit for approval
- approve / reject
- promote
- deploy
- rollback

Monitoring features:

- champion/challenger
- drift baseline
- drift observations
- scheduled monitoring jobs
- model alerts
- business-impact analytics showing alert capture, conversion, and workload effect by scorer version

## 10A. Reporting Automation Administration

Reporting automation now supports:

- in-app reporting alert thresholds
- manager action recommendations derived from reporting posture
- audience-specific templates for `manager`, `executive`, `compliance`, and `board`
- daily reporting alert runs
- monthly and quarterly board-pack distribution

Relevant API surfaces:

- `GET /api/v1/manager/reports/automation-settings`
- `PUT /api/v1/manager/reports/automation-settings`
- `POST /api/v1/manager/reports/alerts/run`
- `GET /api/v1/workflow/reports/overview`
- `POST /api/v1/workflow/reports/alerts/run`

Operational note:

- app notifications are recorded immediately
- Slack and SMTP delivery require real credentials; without them, delivery records will show `not_configured`

## 11. Document and Evidence Operations

Current evidence stack:

- MinIO for raw storage
- OCR / Parse / PII pipeline
- Milvus for retrieval
- Neo4j for graph sync

Operators should watch:

- OCR health
- parse health
- embedding / rerank health
- object storage reachability
- graph sync behavior

## 12. Data and Demo Dataset Management

The project includes a dense synthetic AML seed dataset.

It supports:

- realistic demos
- queue testing
- workflow testing
- playbook analytics
- manager console validation

Seed source:

- [seed_aml_dataset.py](/Users/ze/Documents/goaml-v2/remote-goaml-v2-install/app-layer/app/tools/seed_aml_dataset.py)

Important note:

- reseeding is useful after smoke tests that mutate alert/case/demo records

## 13. Reporting and Oversight

Current reporting/oversight surfaces:

- Reporting Studio
- Manager Console
- Workflow Ops
- Model Ops
- Superset

Newer analytics already live:

- playbook compliance by typology
- typology outcomes
- team/region playbook performance
- worst offending step heatmaps
- SLA trend history
- executive and manager reporting overview
- persisted historical reporting snapshots
- daily / weekly / monthly snapshot cadence support
- executive drilldowns to typology, team / region, and case set
- snapshot-based drilldowns and historical-period exports
- compliance oversight reporting for filing timeliness, review lag, approval lag, audit-trail completeness, and evidence-pack completeness
- outcome correlation reporting tied to model version, workflow delay, and playbook compliance
- exportable management reporting in template-specific JSON, CSV, PDF, and DOCX
- scheduled report capture and distribution via n8n

## 14. Operational Responsibilities

Admin / ops responsibilities typically include:

- user and role oversight
- workflow automation oversight
- model promotion/deploy/rollback oversight
- queue and SLA monitoring
- verifying alerting/notification channels
- keeping docs aligned with deployed behavior

## 15. Change Management Pattern

Recommended pattern for future changes:

1. implement feature in local mirror
2. validate with compile/smoke tests
3. deploy to `goaml-v2` and/or `gpu-01`
4. verify live endpoints and UI
5. update docs:
   - overview
   - implementation plan
   - manual(s)

## 16. Current Admin Limitations

Still future-facing or partial:

- external IdP cutover
- step-up auth
- deeper row-level access controls
- final secrets / TLS hardening
- fully configured Slack/email channels

## 17. Related Docs

- [goaml-v2-project-overview-v3.md](/Users/ze/Documents/goaml-v2/goaml-v2-project-overview-v3.md)
- [implementation-plan-v3.md](/Users/ze/Documents/goaml-v2/implementation-plan-v3.md)
- [end-user-manual.md](/Users/ze/Documents/goaml-v2/end-user-manual.md)
- [product-feature-document.md](/Users/ze/Documents/goaml-v2/product-feature-document.md)
- [platform-functional-features.md](/Users/ze/Documents/goaml-v2/platform-functional-features.md)
