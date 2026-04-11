# goAML-v2 Product Feature Document

> Product-facing feature catalog describing what the platform does today, how the major capability areas fit together, and how they support AML operations.

## 1. Product Positioning

`goAML-v2` is a self-hosted AML analyst workbench and operations platform with:

- alert triage
- investigation and case management
- sanctions/watchlist workflows
- document and graph intelligence
- SAR lifecycle management
- workflow automation
- model lifecycle governance

It is designed to operate as:

- an analyst desktop
- a reviewer/approver workflow tool
- a manager operations surface
- a model/workflow governance surface

## 2. Core Product Areas

### 2.1 Alert and Case Operations

Features:

- live alert queue
- alert detail and evidence
- investigate, dismiss, false positive, escalate
- automatic or linked case creation
- case timeline
- collaboration notes and tasks
- manager reassignment
- closed-loop alert quality feedback
- alert bulk-action preview
- alert queue next / previous navigation
- alert note templates and shortcut-driven triage

Value:

- turns suspicious activity into structured, auditable investigation workflows

### 2.2 Case Command Center

Features:

- default case-first workspace
- overview, evidence, graph, documents, timeline, and SAR tabs
- workflow state
- filing readiness
- pinned evidence
- AI-used evidence visibility
- direct document attach
- closed-loop case and SAR quality feedback

Value:

- provides one primary investigation workspace instead of fragmented pages

### 2.3 SAR Workflow

Features:

- AI-backed SAR drafting
- reviewer and approver queues
- review, approval, rejection, filing
- filing readiness checks
- filing pack generation
- export as JSON, PDF, DOCX

Value:

- supports a real SAR lifecycle rather than simple narrative generation

### 2.4 Document Intelligence

Features:

- OCR
- structured parse
- PII extraction
- embeddings
- vector indexing
- MinIO-backed raw file storage
- case-linked document evidence
- duplicate-document detection
- related-document surfacing
- provenance and filing-pack impact visibility

Value:

- converts unstructured documents into searchable investigation evidence

### 2.5 Graph and Entity Intelligence

Features:

- persistent Neo4j sync
- graph exploration
- drilldown
- pathfinding
- entity profile
- watchlist workflows
- merge workflow
- network risk scoring
- watch-pattern detection
- graph-driven entity recommendations

Value:

- supports contextual network-based investigation and entity resolution

### 2.6 Screening and Watchlist

Features:

- sanctions screening
- watchlist dashboard
- recurring re-screen automation
- watchlist case escalation

Value:

- supports ongoing screening and higher-risk entity monitoring

### 2.7 Playbooks and Guided Investigation

Features:

- typology playbooks:
  - structuring
  - sanctions match
  - layering
  - PEP exposure
  - large cash
  - crypto mixing
- checklist steps
- required evidence rules
- manager-configurable SLA targets
- auto-generated tasks
- playbook analytics
- intervention tuning
- automation for stuck checklists and evidence gaps

Value:

- improves analyst consistency and codifies investigative operating practice

### 2.8 Workflow Automation

Features:

- n8n recurring jobs
- Camunda process orchestration
- workflow monitoring pages
- workflow exceptions panel
- guided-state visibility
- notification events
- rebalance and re-screen automation
- model monitoring automation

Value:

- turns manual operational checks into repeatable workflow controls

### 2.9 Manager and Reporting Features

Features:

- Manager Console
- backlog heatmap
- workload board
- mass reassignment
- advanced manager controls
- saved manager workspaces
- balancing rules and intervention suggestions
- Reporting Studio
- SLA history
- typology outcome analytics
- team/region playbook performance
- hotspot heatmaps
- executive KPI layer
- monthly operational summary
- typology mix and posture reporting
- false-positive and SAR outcome reporting
- persisted historical reporting snapshots
- daily, weekly, and monthly snapshot rollups
- period-over-period movement analytics
- executive KPI drilldowns down to typology, team / region, and case set
- snapshot-anchored historical drilldowns and exports
- threshold-based reporting alerts
- manager action recommendations
- board-level reporting summaries
- configurable reporting alert thresholds
- compliance oversight reporting for review/approval/file timing and evidence/audit completeness
- outcome correlation layer tying typology outcomes to model version, workflow delay, and playbook compliance
- workflow effectiveness analytics for SAR rebalance, playbook automation, and watchlist re-screen
- decision-quality analytics for alert precision, case escalation quality, SAR quality proxies, and true-positive trends
- closed-loop feedback signal aggregation from alert and case workspaces
- decision-quality drilldowns from quality metrics into filtered case sets
- feedback-to-action automation that converts poor-quality signals into notifications and case tasks
- manager-facing quality-tuning recommendations derived from noisy-alert posture, weak SAR draft signals, and repeat rework
- reviewer-quality analytics for drafter rejection rate, rework rate, evidence completeness, and approval-to-filing lag
- persisted decision-quality snapshot history and period-over-period movement boards
- recommendation automation for recurring typology hotspots and repeated drafter-quality issues across snapshots
- exportable branded management packs in JSON, CSV, PDF, and DOCX
- audience-specific report packs for `manager`, `executive`, `compliance`, and `board`
- scheduled manager, executive, compliance-ready, reporting-alert, and board-report workflows through n8n

Value:

- gives team leads and operations stakeholders control over volume, SLA, quality, and stakeholder reporting

### 2.10 Model Ops

Features:

- MLflow-based scorer registration
- evaluation gates
- approval workflow
- production promotion
- deploy
- rollback
- champion/challenger
- drift monitoring
- model monitoring automation
- outcome analytics by version
- scorer business impact by version and typology
- tuning recommendations
- governance handoff from recommendations into Model Ops

Value:

- gives the risk scorer a governed lifecycle rather than ad hoc deployment

## 3. User Types Supported

Primary user types:

- analyst
- reviewer
- approver
- manager
- sanctions analyst
- model ops
- workflow ops
- auditor
- admin

Each role has:

- desk visibility
- permission gating
- relevant workflows and actions

## 4. Product Desks

Current top-level desks:

- Launchpad
- Control Tower
- Reporting Studio
- Alert Desk
- Case Command Center
- Intelligence Hub
- Workflow Ops
- Model Ops
- Platform Ops
- Manager Console
- Analyst Inbox

## 5. AI and Decision Support Features

Live AI functions:

- case summaries
- grounded SAR drafting
- AI-used-evidence attribution
- retrieval-backed investigation context
- OCR
- parse
- PII extraction
- semantic retrieval
- rerank
- XGBoost transaction scoring

## 6. Governance and Operational Control

Current governance features:

- SAR separation-of-duties
- local auth and RBAC
- auth audit and provider settings
- model evaluation, approval, deploy, rollback
- workflow notifications
- SLA trends and automation

## 7. Product Differentiators Inside the Current Build

Strongest current differentiators:

- unified investigation + graph + document + AI workflow
- first-class case command center
- grounded evidence-aware AI drafting
- MLflow-driven scorer lifecycle
- watchlist re-screen automation with escalation
- playbook analytics and intervention tuning

## 8. Current Scope Boundaries

Not yet the main focus of the current version:

- external identity provider cutover
- deep row-level data partitioning
- final enterprise hardening
- full external connector ecosystem

## 9. Related Docs

- [goaml-v2-project-overview-v3.md](/Users/ze/Documents/goaml-v2/goaml-v2-project-overview-v3.md)
- [implementation-plan-v3.md](/Users/ze/Documents/goaml-v2/implementation-plan-v3.md)
- [end-user-manual.md](/Users/ze/Documents/goaml-v2/end-user-manual.md)
- [admin-manual.md](/Users/ze/Documents/goaml-v2/admin-manual.md)
- [platform-functional-features.md](/Users/ze/Documents/goaml-v2/platform-functional-features.md)
