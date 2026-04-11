# goAML-v2 End User Manual

> Practical guide for analysts, reviewers, approvers, managers, and specialist users working inside the live goAML-v2 platform.

## 1. Purpose

This manual explains how to use the platform day to day:

- how to log in
- how to navigate the desks
- how to investigate alerts and cases
- how to work with SARs
- how to use documents, graph, screening, and AI features
- how to use saved views, bulk actions, inbox, and manager tools

Primary app URL:

- `http://160.30.63.131/`

## 2. Login and Session

The current deployment uses local authentication.

Login flow:

1. Open the analyst UI.
2. Enter username and password.
3. After login, the platform loads the desk allowed by your role and profile preferences.

Current seeded local roles:

- analyst
- reviewer
- approver
- manager
- sanctions analyst
- model ops
- workflow ops
- auditor
- admin

Common seeded users:

- `analyst1`
- `reviewer1`
- `approver1`
- `manager1`
- `sanctions1`
- `modelops1`
- `workflowops1`
- `auditor1`
- `admin1`

Bootstrap demo password:

- `Goaml!2026`

Session features:

- login
- logout
- profile page
- password change
- preferred landing desk

## 3. Main Navigation Model

The UI is organized into dedicated desks instead of one large dashboard.

Main entry points:

- `Launchpad`
- `Control Tower`
- `Reporting Studio`
- `Alert Desk`
- `Case Command Center`
- `Intelligence Hub`
- `Workflow Ops`
- `Model Ops`
- `Platform Ops`
- `Manager Console`
- `Analyst Inbox`

Useful navigation behavior:

- `Back` returns you to the previous desk/page
- `Open in Window` opens a desk in a separate browser window
- many record actions open directly into the correct workspace

## 4. Launchpad

The Launchpad is the recommended landing page.

Use it to:

- open the right desk for your role
- launch desks in separate windows
- avoid navigating through a long side menu

Typical usage by role:

- analyst: `Alert Desk`, `Case Command Center`, `Intelligence Hub`
- reviewer: `SAR Review Queue`, `Case Command Center`
- approver: `SAR Review Queue`, `Workflow Ops`
- manager: `Manager Console`, `Reporting Studio`, `Workflow Ops`
- model ops: `Model Ops`

## 5. Alert Desk

Use Alert Desk for first-line triage.

Core actions:

- open alert detail
- investigate
- dismiss
- mark false positive
- escalate
- add analyst note
- capture closed-loop quality feedback

Available productivity features:

- saved views
- queue presets
- bulk triage
- multi-select
- bulk-action preview
- next / previous queue navigation
- note templates
- keyboard shortcuts:
  - `j` / `ArrowDown`
  - `k` / `ArrowUp`
- direct graph actions
- direct case open / create

Typical alert workflow:

1. Open `Alert Desk`.
2. Filter or load a saved view.
3. Open an alert.
4. Review alert detail, evidence, and graph context.
5. Take an action:
   - dismiss
   - false positive
   - escalate
   - investigate
6. If investigating, open or create the linked case.

Closed-loop feedback in Alert Desk:

- use `Good alert` when an alert was genuinely useful
- use `Noisy alert` when an alert added little investigative value
- use `Missing evidence` when the alert or surrounding context still needs better support
- these feedback signals flow into Reporting Studio and help shape the live decision-quality view

### SAR Queue Productivity

The SAR queue now includes a productivity panel similar to Alert Desk.

Use it for:

- bulk-action preview before review/approval actions
- next / previous queue navigation
- reviewer note templates
- faster movement across pending-review work

## 6. Case Command Center

The Command Center is the primary case workspace.

It is now the default case-open experience.

Tabs and areas:

- `Overview`
- `Evidence`
- `Graph`
- `Documents`
- `Timeline`
- `SAR`

What analysts can do:

- view case summary and risk factors
- review timeline and linked alerts/transactions
- pin evidence
- mark evidence for SAR inclusion
- review graph evidence and pathfinding
- attach and analyze documents
- add notes and tasks
- view workflow state
- view filing readiness
- generate AI summary
- draft SAR
- submit SAR for review
- capture closed-loop case and SAR quality feedback

Document detail and evidence surfaces now also show:

- duplicate candidates
- related documents
- provenance trail
- filing-pack impact

Entity detail now also shows:

- network risk score
- connected high-risk nodes and screening hits
- watch patterns
- graph-driven recommendations

## 7. Workflow Ops

Workflow Ops now includes exception handling and guided-state support.

Use it to:

- review workflow exceptions
- review guided-state issues
- trigger allowed intervention actions
- monitor decision-quality and playbook automations
- watch n8n and Camunda health from within the product

## 8. Manager Console

Manager Console now has an advanced controls panel.

Use it for:

- saved manager workspace presets
- balancing-rule visibility
- intervention suggestions
- team hotspots
- region hotspots

## 9. Model Ops

Model Ops now includes tuning recommendations and governance handoff support.

Use it to:

- review scorer tuning recommendations
- review business-impact posture
- send a recommendation into the governance lane
- keep model tuning tied to the live analyst and manager signal flow

## 7. Evidence Workflow

Evidence can come from:

- alerts
- transactions
- documents
- screening hits
- graph relationships
- semantically retrieved case context

Evidence tools:

- pin evidence
- set importance
- mark `include_in_sar`
- review AI-used evidence

Pinned evidence drives:

- AI summaries
- SAR drafts
- filing packs
- filing readiness

Closed-loop feedback in Case Command Center:

- use `Strong evidence` when the case is well supported
- use `High-quality case` when the investigation quality is strong overall
- use `Missing evidence` when the case still lacks critical support
- use `Weak SAR draft` when the narrative needs better evidence synthesis before review
- these signals are visible in Reporting Studio under `Decision Quality Dashboard` and `Closed-loop Feedback Signals`

## 8. Documents and Intelligence Hub

Use `Documents` and `Intelligence Hub` for evidence-heavy investigation work.

Document capabilities:

- upload text, files, and images
- OCR
- structured parse
- PII extraction
- embeddings
- vector storage
- MinIO-backed storage
- attach document to case

What to expect in document detail:

- extracted text
- OCR / parse / PII status
- vector status
- storage path
- linked case
- graph candidates

OCR smoke testing:

- the UI includes a smoke-test path for image OCR validation

## 9. Screening and Watchlist

Screening flow:

- open `Screening`
- submit entity/person/company name
- review sanctions/watchlist matches
- save the results into case/entity workflows

Watchlist capabilities:

- entity watchlist dashboard
- recurring re-screen automation
- automatic escalation when new matches appear
- open or reuse watchlist review case

## 10. Graph Investigation

Graph features are available from:

- `Network Graph`
- `Case Command Center`
- alert details
- transaction detail
- entity detail

Available functions:

- graph explore
- graph drilldown
- pathfinding
- relationship evidence review

Use graph views to:

- identify linked accounts/entities
- inspect case-to-document or case-to-screening relationships
- understand connected suspicious activity

## 11. SAR Workflow

The SAR workflow now has real lifecycle stages:

- draft
- pending review
- approved
- filed
- rejected

Main user actions:

- analyst drafts SAR
- reviewer submits / comments / rejects
- approver approves
- authorized user files

SAR workspace functions:

- AI-assisted draft generation
- grounded evidence usage
- SAR preview
- workflow notes
- filing reference capture
- filing readiness panel
- filing pack generation

Export formats:

- JSON
- PDF
- DOCX

## 12. Reviewer and Approver Queues

The SAR queue is first-class, not hidden inside cases.

Features:

- review queue
- approval queue
- filed queue
- saved views
- bulk actions
- SLA visibility
- workload balancing inputs

Reviewers and approvers should use this queue to:

- prioritize due-soon and breached work
- open cases into Command Center
- apply workflow actions in a structured way

## 13. Analyst Inbox

The inbox is a task and notification surface for active work.

Inbox content includes:

- notifications
- automation follow-ups
- playbook intervention items
- workflow-generated work items

Current features:

- saved views
- presets
- bulk actions
- direct deep links into the right desk

## 14. Manager Console

Manager Console is for leads, supervisors, and queue controllers.

Main functions:

- team / region / typology / SLA / owner filters
- backlog heatmap
- workload board
- mass reassignment
- playbook compliance snapshot
- missed-step and hotspot visibility
- playbook tuning
- playbook intervention tuning
- management outcome visibility

Managers can use it to:

- rebalance workload
- inspect hot spots
- tune SLA targets
- tune automation thresholds

## 15. Reporting Studio

Reporting Studio is for operational reporting.

Current reporting areas:

- historical SLA trend
- review queue trend
- operational funnel
- owner workload distribution
- playbook compliance by typology
- typology outcomes
- most missed steps
- blocked-step trend
- team playbook performance
- region playbook performance
- worst offending step heatmap
- executive KPI layer
- monthly operational summary
- typology mix
- watchlist and screening posture
- model and workflow health summary
- playbook effectiveness by typology and priority
- false-positive rate by team / typology / owner
- filed SAR volume by team / region
- backlog aging and breach trend view
- historical reporting snapshots
- daily / weekly / monthly snapshot cadence selector
- period-over-period movement board
- executive drilldowns from KPI to case set
- historical-period exports from a selected snapshot
- threshold alerts and escalations
- manager action recommendations
- board-level summary
- reporting alert threshold settings
- scheduled report distribution rules
- compliance oversight for review lag, approval lag, filing timeliness, audit completeness, and evidence-pack completeness
- outcome correlation layer
- workflow effectiveness analytics for SAR rebalance, playbook automation, and watchlist re-screen
- export as JSON / CSV / PDF / DOCX

Managers and compliance leads can use the export buttons at the top of Reporting Studio to download the current reporting pack. They can switch between `manager`, `executive`, `compliance`, and `board` templates, choose `daily`, `weekly`, or `monthly` reporting cadence, capture a reporting snapshot, select a historical period from the snapshot board, review period-over-period movement, run snapshot-anchored drilldowns, run threshold alerts, review action recommendations, review `Decision Quality Dashboard` and `Closed-loop Feedback Signals`, and export a historical period pack from the same page.

Decision-quality reporting also supports deeper drilldowns. Managers can click from alert precision, case escalation quality, SAR quality, or feedback-signal views into the affected case set, filtered by typology, team, region, or specific feedback keys such as `weak_sar_draft`.

Reporting Studio now also includes `Quality Tuning Recommendations` and `Reviewer Quality Analytics`. Managers can use these to see where typologies need threshold or playbook changes, which drafters are seeing repeated rejection or rework, how complete evidence is at review time, and where approval-to-filing lag is longest by team and typology.

Reporting Studio also includes `Decision-quality Snapshot History` and `Decision-quality Period Movement`. These boards show how quality signals are changing over time, using persisted daily snapshots rather than only the current live view.

Scheduled reporting now also includes a daily reporting-alert run plus monthly and quarterly board-pack distribution through n8n. Until SMTP is configured, external delivery remains visible as `not_configured`, while app-side notifications still appear in the platform.

## 16. Model Ops

Model Ops is for scorer/model governance.

Current capabilities:

- scorer runtime metadata
- MLflow model registry state
- version catalog
- evaluation gates
- approval workflow
- deployment history
- rollback
- champion / challenger
- drift monitoring
- model outcome analytics
- scorer business impact analytics by model version

Use it to:

- register model versions
- evaluate challenger versions
- approve promotion
- deploy production model
- roll back if needed
- compare how model versions change alert capture, false-positive posture, case conversion, and SAR conversion

## 17. Workflow Ops

Workflow Ops shows automation and operational control surfaces.

Current workflow capabilities:

- n8n automation visibility
- Camunda process visibility
- SLA notification history
- playbook automation monitor
- model alert monitoring
- reporting alert monitor
- reporting recommendation monitor
- decision-quality intervention monitor
- manual workflow trigger actions
- scheduled reporting workflow visibility

Workflow Ops also includes a `Run Decision-Quality Automation` control. This turns recent analyst feedback into actions such as noisy-alert hotspot notifications, weak-SAR-draft intervention tasks, and missing-evidence follow-up tasks.

Workflow Ops now also includes `Run Quality Recommendation Automation`. This uses repeated decision-quality snapshots to flag recurring noisy typologies and repeated drafter-quality hotspots so managers can intervene earlier.

## 18. Settings and Profile

Profile features:

- update personal profile fields
- change password
- set preferred home
- view role and desk access

Settings features:

- auth provider list
- local auth settings
- WSO2-ready forms for future configuration
- admin user management and auth audit views

## 19. Recommended Role-Based Usage

Analyst:

- Launchpad -> Alert Desk -> Case Command Center -> Documents / Graph

Reviewer:

- Launchpad -> SAR Queue -> Case Command Center -> Workflow note / decision

Approver:

- Launchpad -> SAR Queue -> Case Command Center -> Approve / file

Manager:

- Launchpad -> Manager Console -> Reporting Studio -> Workflow Ops

Model Ops:

- Launchpad -> Model Ops

Workflow Ops:

- Launchpad -> Workflow Ops -> n8n / Camunda

## 20. Troubleshooting

If a page seems stale:

- hard refresh the browser

If a workflow page looks empty:

- check whether your role includes access to that desk
- check whether seed/demo data exists for that queue

If a document or graph action seems missing:

- open the relevant case first so context-sensitive actions become available

If a SAR action is disabled:

- review the current workflow stage
- review filing readiness blockers
- check whether your role allows that action

## 21. Current Limitations

Current intentional limitations:

- local auth is active; external IdP is deferred
- deeper row-level work partitioning is planned for a later version
- Slack and email delivery require credential setup
- some queues and dashboards are strongest with seeded demo data or recent live activity

## 22. Related Docs

- [goaml-v2-project-overview-v3.md](/Users/ze/Documents/goaml-v2/goaml-v2-project-overview-v3.md)
- [implementation-plan-v3.md](/Users/ze/Documents/goaml-v2/implementation-plan-v3.md)
- [admin-manual.md](/Users/ze/Documents/goaml-v2/admin-manual.md)
- [product-feature-document.md](/Users/ze/Documents/goaml-v2/product-feature-document.md)
- [platform-functional-features.md](/Users/ze/Documents/goaml-v2/platform-functional-features.md)
