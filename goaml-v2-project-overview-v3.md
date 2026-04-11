# goAML-v2 Project Overview v3

> Current-state architecture and implementation guide for the goAML-v2 AML analytics platform, updated with the live deployment, public OpenSanctions screening path, Qwen-backed SAR drafting, first-class SAR reviewer/approver queues, entity watchlist workflows, the fully deployed Case Command Center, the new local-auth/profile layer with future WSO2-ready settings, the upgraded playbook analytics surface with team/region performance boards, hotspot heatmaps, and manager-facing intervention tuning, the new executive reporting layer in Reporting Studio with daily, weekly, and monthly historical snapshots, period-over-period analysis, historical-period exports, threshold-driven reporting alerts, manager action recommendations, board-level reporting packs, scorer business impact boards, workflow effectiveness analytics, the new decision-quality dashboard plus closed-loop feedback capture across alerts and cases, and the latest maturity slice covering analyst productivity previews, advanced manager controls, workflow exception handling, document/evidence intelligence, entity network intelligence, and model-tuning governance handoff.

## 1. Executive Summary

`goAML-v2` is a self-hosted Anti-Money Laundering analytics and investigation platform split across two servers:

- `goaml-v2` at `160.30.63.131`
  - app, workflow, storage, analytics, graph/vector, document support, and UI
- `gpu-01` at `160.30.63.152`
  - model inference, document intelligence, PII, and risk scoring

The platform is designed to handle:

- transaction monitoring and risk scoring
- alert triage and investigation
- sanctions and PEP screening
- case management and timeline history
- a default case-first Command Center with reviewer-grade tabs and workflow context
- reviewer / approver SAR queues and filing workflows
- reviewer workload balancing and SLA-driven queue automation
- entity profile, watchlist, and merge resolution workflows
- automatic watchlist case escalation when re-screening finds new matches
- analyst collaboration through case notes and tasks
- document OCR, parsing, PII extraction, and MinIO-backed evidence storage
- graph and vector-assisted investigations with persisted Neo4j evidence
- retrieval-backed investigation context and AI case summaries
- workflow automation and analyst support
- unattended watchlist re-screen automation through n8n schedules
- local authentication, RBAC desk gating, and audit-backed role-aware access
- self-service login, logout, password change, and user profile management
- a settings workspace that already carries future WSO2 / OIDC provider forms
- playbook compliance analytics by typology, including checklist completion, missed-step rankings, blocked-step trends, and false-positive / SAR conversion reporting
- second-generation playbook analytics with team and region performance breakdowns plus worst-offending-step heatmaps in Reporting Studio and Manager Console
- automated playbook enforcement for stuck checklist steps and near-SLA evidence gaps, with n8n-backed recurring runs and inbox-visible follow-up work
- manager-facing playbook intervention tuning in Manager Console so automation thresholds can be adjusted from the UI instead of config files
- executive KPI reporting, monthly operational summaries, typology mix, watchlist/screening posture, and model/workflow health views in Reporting Studio
- manager outcome reporting for false-positive rates, case-to-SAR conversion, filed SAR volume, and backlog aging/breach trends
- daily, weekly, and monthly reporting snapshots with persisted period labels and audit-friendly history
- period-over-period movement analysis for backlog, breached SARs, filed SARs, and watchlist posture
- historical-period drilldowns and exports anchored to a selected reporting snapshot
- threshold-driven reporting alerts with in-app notification delivery and configurable alert thresholds
- manager action recommendations derived from reporting posture and trend deterioration
- board-level reporting summaries with top risks, typology posture, biggest improvements, and biggest declines
- exportable management reporting in JSON, CSV, PDF, and DOCX formats
- scheduled n8n report generation for daily manager CSV packs, weekly executive PDF packs, daily reporting alerts, monthly board PDF packs, and quarterly board DOCX packs
- scorer business impact analytics in Model Ops covering alert capture, false-positive posture, case conversion, SAR conversion, filed-SAR rate, case cycle time, and dominant typology by model version
- workflow effectiveness analytics in Reporting Studio covering SAR rebalance, playbook automation, and watchlist re-screen outcomes with effectiveness trends over time
- decision-quality reporting covering alert precision by typology, case escalation quality, SAR quality proxies, and true-positive trends by workflow and model version
- closed-loop feedback capture from Alert Desk and Case Command Center for `good_alert`, `noisy_alert`, `missing_evidence`, `strong_evidence`, `weak_sar_draft`, and `high_quality_case`
- feedback-aware management views in Reporting Studio so recent quality signals are visible to managers, reviewers, and compliance users
- decision-quality drilldowns from Reporting Studio into case sets by typology, team, region, and feedback signal
- feedback-to-action automation in Workflow Ops for noisy-alert hotspots, weak SAR draft interventions, and missing-evidence follow-up tasks
- quality-tuning recommendations in Reporting Studio based on noisy-alert posture, weak SAR drafts, and repeated rework signals
- reviewer-quality analytics covering rejection rate by drafter, rework rate, evidence completeness at review time, and approval-to-filing lag by team and typology
- persisted decision-quality snapshot history with period-over-period movement in Reporting Studio for audit-friendly quality tracking over time
- recommendation automation in Workflow Ops that detects recurring noisy typologies and repeat drafter-quality hotspots across quality snapshots
- alert and SAR bulk-action previews with queue navigation, note templates, and lightweight keyboard shortcuts for higher-speed analyst work
- advanced manager controls with saved workspaces, balancing rules, intervention suggestions, and team / region hotspot boards
- workflow exception monitoring with guided-state visibility and intervention-ready exception actions in Workflow Ops
- document intelligence overlays showing duplicate candidates, related documents, provenance, and filing-pack impact
- entity network intelligence overlays showing network risk score, watch patterns, and graph-driven recommendations
- scorer tuning recommendations and governance handoff support inside Model Ops

The current system is beyond planning. It is already running as a live multi-service deployment with working APIs, a browser-accessible analyst UI, a default case-first Command Center, live case workflows, reviewer/approver SAR operations, LLM-generated SAR drafts, and a role-aware local login/profile experience.

Companion manuals now maintained alongside this overview:

- [end-user-manual.md](/Users/ze/Documents/goaml-v2/end-user-manual.md)
- [product-feature-document.md](/Users/ze/Documents/goaml-v2/product-feature-document.md)
- [admin-manual.md](/Users/ze/Documents/goaml-v2/admin-manual.md)
- [platform-functional-features.md](/Users/ze/Documents/goaml-v2/platform-functional-features.md)

## 2. Deployment Split

### 2.1 App / Control Plane

| Item | Value |
|---|---|
| Host | `goaml-v2` |
| IP | `160.30.63.131` |
| Role | API, UI, databases, workflow, graph/vector, screening, analytics |
| Main path | `/home/ze/goaml-v2` |
| Local copied source | [remote-goaml-v2-install](/Users/ze/Documents/goaml-v2/remote-goaml-v2-install) |

### 2.2 Inference Plane

| Item | Value |
|---|---|
| Host | `gpu-01` |
| IP | `160.30.63.152` |
| Role | LLMs, embeddings, rerank, OCR, parse, PII, scorer |
| Model deployment path | model-side deployment on GPU host |
| Local copied source | [remote-gpu-01-models](/Users/ze/Documents/goaml-v2/remote-gpu-01-models) |

### 2.3 Separation Principle

The two hosts should remain separate:

- `goaml-v2` owns product and data-plane services
- `gpu-01` owns model-serving and ML inference services
- integration happens over HTTP APIs, not shared local containers

This separation keeps model deployment independent from app deployment and makes it easier to scale or replace either side later.

## 3. Live Service Inventory

### 3.1 `goaml-v2` Services

Verified via live `docker ps` and deployment files:

| Area | Services |
|---|---|
| App | FastAPI, React UI, Nginx, Superset |
| Workflow | n8n, Camunda |
| Agent / orchestration | LangGraph, MCP server, MLflow |
| Storage | PostgreSQL, ClickHouse, Redis |
| Graph / vector | Neo4j, Milvus, MinIO, etcd, Attu |
| Docs / screening | Apache Tika, Yente, Elasticsearch |

### 3.2 `gpu-01` Services

Verified via live `docker ps` and model compose files:

| Container | Runtime | Port | Purpose |
|---|---|---:|---|
| `goaml-llm-primary` | vLLM | 8000 | Primary LLM reasoning and SAR drafting |
| `goaml-llm-fast` | vLLM | 8002 | Fast inference / lightweight reasoning |
| `goaml-embed` | vLLM pooling | 8001 | Semantic embeddings |
| `goaml-rerank` | vLLM pooling | 8003 | Retrieval reranking |
| `goaml-parse` | vLLM | 8022 | Structured document parsing |
| `goaml-ocr` | FastAPI wrapper | 8021 | OCR |
| `goaml-pii` | FastAPI wrapper | 8020 | PII extraction |
| `goaml-scorer` | FastAPI wrapper | 8010 | XGBoost risk scoring |

### 3.3 Dashboard UI Access Matrix

The following dashboard-style UIs are live on `goaml-v2` and were verified as responding on `160.30.63.131`.

Important: this section contains active access details from the current deployment and should be treated as sensitive.

| App | Link | Login | Notes |
|---|---|---|---|
| Analyst UI | `http://160.30.63.131/` | local auth enabled, demo password `Goaml!2026` | Main AML analyst UI. Demo users now include `analyst1`, `reviewer1`, `approver1`, `manager1`, `sanctions1`, `modelops1`, `workflowops1`, `auditor1`, and `admin1`. The same settings workspace already keeps WSO2 / OIDC fields ready for a later cutover. |
| Superset | `http://160.30.63.131:8088` | `admin` / `Asdf@1234` | Analytics dashboards and BI. Admin user is created from the app-layer compose startup command. |
| n8n | `http://160.30.63.131:5678` | no static user/pass configured in compose | Workflow UI is live. No `N8N_BASIC_AUTH_*` settings are present in the deployed compose, so access is currently governed by n8n's own app bootstrap/session model rather than a shared static credential in env. Active workflows now include daily due-only and weekly full watchlist re-screen jobs, a weekday SAR queue rebalance workflow, a daily scorer drift monitor, a weekly scorer challenger evaluation workflow, a daily manager CSV report workflow, and a weekly executive PDF report workflow. |
| Camunda | `http://160.30.63.131:8085/camunda/app/` | no explicit credential set in deployed env | BPMN workflow UI is live. The current compose file sets database connectivity only and does not define a custom app username/password. |
| Neo4j Browser | `http://160.30.63.131:7474` | `neo4j` / `Asdf@1234` | Graph investigation and Cypher exploration UI. Bolt endpoint is `bolt://160.30.63.131:7687`. |
| Attu | `http://160.30.63.131:8080` | no separate Attu login configured | Milvus admin UI. It connects to Milvus using `160.30.63.131:19530` or the internal service name `goaml-milvus:19530`. |
| MinIO Console | `http://160.30.63.131:9001` | `minioadmin` / `Asdf@1234` | Object storage console used by Milvus and MLflow. S3 API endpoint is `http://160.30.63.131:9002`. |
| MLflow | `http://160.30.63.131:5000` | none configured | Experiment tracking and model registry UI. No app-layer auth is configured in the current compose. |

### 3.4 Local Auth and RBAC Model

The analyst-facing product now uses local authentication plus app-native RBAC. This is intentionally designed so the login provider can be swapped to WSO2 later without changing desk layout, page routing, or permission semantics.

Current auth shape:

- local username/password login is live
- JWT-backed app sessions are live
- role-aware desk visibility is live
- backend permission checks are enforced on protected APIs
- SAR separation-of-duties rules are enforced in the case workflow
- auth settings, provider metadata, user administration, and auth audit history are exposed in the `Settings` desk
- WSO2 / OIDC forms already exist in the product settings page but remain disabled until external identity is introduced

Seeded local roles:

- `analyst`
- `reviewer`
- `approver`
- `manager`
- `sanctions_analyst`
- `model_ops`
- `workflow_ops`
- `auditor`
- `admin`

Seeded bootstrap users:

- `analyst1`
- `reviewer1`
- `approver1`
- `manager1`
- `sanctions1`
- `modelops1`
- `workflowops1`
- `auditor1`
- `admin1`

Important current-state note:

- local auth is now real and enforced
- WSO2 is no longer a prerequisite for role-aware product behavior
- the future identity migration can focus on swapping the authentication provider, while preserving the app-side role, desk, and policy model

## 4. Current Application Architecture

```mermaid
graph TD
    subgraph GOAML["goaml-v2 : 160.30.63.131"]
        UI[Analyst UI]
        NGINX[Nginx]
        API[FastAPI]
        PG[(PostgreSQL)]
        CH[(ClickHouse)]
        REDIS[(Redis)]
        NEO4J[(Neo4j)]
        MILVUS[(Milvus)]
        MINIO[(MinIO)]
        YENTE[Yente]
        ES[(Elasticsearch)]
        TIKA[Tika]
        N8N[n8n]
        CAMUNDA[Camunda]
        LANGGRAPH[LangGraph]
        MLFLOW[MLflow]
    end

    subgraph GPU["gpu-01 : 160.30.63.152"]
        QWEN32[Qwen3-32B]
        QWEN8[Qwen3-8B]
        EMBED[Embed]
        RERANK[Rerank]
        PARSE[Parse]
        OCR[OCR]
        PII[PII]
        SCORER[Scorer]
    end

    UI --> NGINX --> API
    API --> PG
    API --> CH
    API --> REDIS
    API --> NEO4J
    API --> MILVUS
    API --> YENTE
    YENTE --> ES
    API --> TIKA
    API --> QWEN32
    API --> QWEN8
    API --> EMBED
    API --> RERANK
    API --> PARSE
    API --> OCR
    API --> PII
    API --> SCORER
    N8N --> API
    CAMUNDA --> API
    LANGGRAPH --> API
    MLFLOW --> SCORER
    MILVUS --> MINIO
```

## 5. Core Product Workflows

### 5.1 Transaction Monitoring Workflow

```mermaid
flowchart LR
    A[Incoming transaction] --> B[FastAPI ingestion]
    B --> C[PostgreSQL transactional store]
    B --> D[ClickHouse analytics store]
    B --> E[XGBoost risk scorer]
    E --> F[Risk score and factors]
    F --> G[Alert generation logic]
    G --> H[Alerts table]
    H --> I[Analyst UI alert queue]
```

### 5.2 Alert to Case to SAR Workflow

```mermaid
flowchart LR
    A[Alert created] --> B[Analyst opens Alerts page]
    B --> C[Investigate button]
    C --> D[Assign analyst]
    D --> E[Create or reopen case]
    E --> F[Case timeline]
    F --> G[Case notes, tasks, and graph evidence]
    G --> H[AI summary and investigation context]
    H --> I[Draft SAR]
    I --> J[SAR preview]
    J --> K[Submit for review]
    K --> L[Approve or reject]
    L --> M[File SAR]
    M --> N[Case status becomes sar_filed]
```

### 5.3 Document Intelligence Workflow

```mermaid
flowchart LR
    A[Uploaded document] --> B[Tika]
    A --> C[OCR]
    C --> D[Parse]
    D --> E[PII extraction]
    E --> F[Embeddings]
    F --> G[Milvus retrieval]
    G --> H[Rerank]
    H --> I[Case context and AI summary]
    A --> J[MinIO raw file storage]
    J --> K[Document detail and case attachment]
```

### 5.4 Screening Workflow

```mermaid
flowchart LR
    A[Entity name submitted] --> B[FastAPI /screen]
    B --> C[Yente]
    C --> D[OpenSanctions public catalog]
    C --> E[Elasticsearch index]
    C --> F[OFAC XML fallback if needed]
    E --> G[Search results]
    F --> G
    G --> H[screening_results table]
    H --> I[Entity profile and watchlist workflow]
```

### 5.5 Investigation Context Workflow

```mermaid
flowchart LR
    A[Case opened] --> B[Linked alerts and transactions]
    A --> C[Direct case documents]
    A --> D[Screening hits]
    A --> E[Persisted Neo4j graph]
    C --> F[Embeddings search in Milvus]
    F --> G[Rerank]
    B --> H[Case context assembler]
    D --> H
    E --> H
    G --> H
    H --> I[Analyst evidence panel]
    H --> J[Qwen3-32B AI case summary]
```

### 5.6 Entity Resolution and Watchlist Workflow

```mermaid
flowchart LR
    A[Entity screening or analyst review] --> B[Entity profile workspace]
    B --> C[Watchlist confirm / PEP / sanctions confirm]
    B --> D[Open watchlist review case]
    B --> E[Add note]
    B --> F[Merge duplicate candidate]
    C --> G[Watchlist dashboard]
    D --> G
    F --> H[Linked accounts, cases, docs consolidated]
    G --> I[Open review case from dashboard]
```

### 5.7 Case Command Center Workflow

```mermaid
flowchart LR
    A[Alert queue / SAR queue / Watchlist / Entity / Graph pivot] --> B[Case Command Center]
    B --> C[Overview tab]
    B --> D[Evidence tab]
    B --> E[Documents tab]
    B --> F[Graph tab]
    B --> G[Timeline tab]
    B --> H[SAR tab]
    D --> I[Pinned evidence board]
    I --> J[Filing readiness]
    E --> J
    F --> J
    H --> K[Reviewer and approver actions]
    K --> L[Filed SAR]
```

### 5.8 Persisted Graph Workflow

```mermaid
flowchart LR
    A[PostgreSQL AML records] --> B[Graph sync]
    B --> C[Neo4j persisted graph]
    C --> D[Graph explore]
    C --> E[Graph drilldown]
    C --> F[Pathfinding]
    D --> G[Cases workspace]
    E --> G
    F --> G
```

## 6. Database Model

The PostgreSQL instance is not a toy schema. It contains both business-domain AML tables and support-service tables.

### 6.1 Main AML Tables

Core business tables verified in schema and/or live database:

- `transactions`
- `accounts`
- `entities`
- `alerts`
- `cases`
- `case_alerts`
- `case_transactions`
- `case_events`
- `case_notes`
- `case_tasks`
- `sar_reports`
- `documents`
- `screening_results`

### 6.2 Platform Tables Also Present

Shared platform database also includes:

- Camunda `act_*` tables
- Superset `ab_*` tables
- MLflow tables
- n8n workflow and execution tables

### 6.3 Important AML Relationships

```mermaid
erDiagram
    ACCOUNTS ||--o{ TRANSACTIONS : sender_or_receiver
    ALERTS }o--|| TRANSACTIONS : linked_txn
    CASES ||--o{ CASE_ALERTS : contains
    CASES ||--o{ CASE_TRANSACTIONS : contains
    CASES ||--o{ CASE_EVENTS : timeline
    CASES ||--o| SAR_REPORTS : produces
    SCREENING_RESULTS }o--|| TRANSACTIONS : optionally_linked
```

## 7. Model Usage Map

### 7.1 Current Inference Usage

| Model / Service | Current role |
|---|---|
| `Qwen3-32B` | Live SAR drafting and live AI case summary generation |
| `Qwen3-8B` | Deployed fast LLM reserved for lighter triage and future low-latency summarization |
| `Nemotron Embed` | Live document embedding generation, Milvus indexing, and semantic retrieval for case context |
| `Nemotron Rerank` | Live reranking in retrieval-backed investigation context |
| `Nemotron Parse` | Live structured document extraction path in document analysis |
| OCR service | Live GPU-backed image OCR for analyst uploads on `gpu-01` |
| GLiNER PII | Live entity and PII extraction from uploaded documents/text |
| XGBoost scorer | Live transaction risk scoring support path |

Current ML lifecycle note:

- the XGBoost scorer is already used in the live transaction ingest path
- MLflow is deployed and healthy as experiment tracking and registry infrastructure
- MLflow is now the runtime source of truth for scorer registration, promotion, and deployment
- `goaml-scorer` can register its current model into MLflow, promote a version to `Production`, and redeploy itself from the promoted registry artifact bundle
- the analyst-facing `Model Ops` page exposes scorer runtime metadata, registry versions, deployment alignment, evaluation gates, approval workflow, deployment history, rollback controls, champion/challenger comparison, and drift monitoring
- scorer monitoring now persists a production drift baseline, follow-up drift observations, and challenger evaluations against recent scored transactions
- scorer monitoring alerts now flow through the shared workflow notification layer and appear in `Workflow Ops`
- n8n now runs automated weekday scorer drift capture and weekly challenger evaluation jobs
- Reporting Studio now includes executive KPIs, monthly summaries, typology mix, watchlist/screening posture, model/workflow health, team/region trend views, playbook effectiveness, manager false-positive reporting, filed SAR volume, and backlog aging
- historical reporting snapshots are now persisted at daily, weekly, and monthly cadences and can be queried independently of live aggregations for audit-friendly trend analysis
- Reporting Studio now includes a reporting-granularity selector and period-over-period movement board for snapshot-based comparison
- executive drilldowns now support KPI -> typology -> team / region -> case set navigation through the reporting API and UI, with direct jump-to-desk actions into the case workspace
- executive drilldowns can now be anchored to a selected historical snapshot period rather than only the current live window
- manager reporting is available through `GET /api/v1/manager/reports/overview`, `GET /api/v1/manager/reports/snapshots`, `GET /api/v1/manager/reports/drilldown`, `GET /api/v1/manager/reports/automation-settings`, `PUT /api/v1/manager/reports/automation-settings`, `POST /api/v1/manager/reports/alerts/run`, and `GET /api/v1/manager/reports/export?template=manager|executive|compliance|board&format=json|csv|pdf|docx`
- historical reporting packs can now be exported for a selected snapshot period, not just the current live view
- scheduled report distribution rules are now configurable in-app for manager, executive, compliance, and board templates, while n8n remains the timed runner
- branded management reporting packs now support template-specific `JSON`, `CSV`, `PDF`, and `DOCX` exports with stronger CSV breakdowns for downstream analysis, including board-ready PDF and DOCX formats
- Reporting Studio now includes an outcome-correlation layer tying typology outcomes to model version, workflow delay, and playbook compliance
- Reporting Studio now includes compliance reporting for filing timeliness, review lag, approval lag, audit-trail completeness, and evidence-pack completeness
- Reporting Studio now includes threshold-driven reporting alerts, manager action recommendations, board-level reporting summaries, and configurable reporting alert thresholds
- Workflow Ops now includes a reporting alert monitor and recommendation panel sourced from the reporting engine
- scheduled report generation and distribution are live through n8n as `goAML Reporting Snapshot Daily`, `goAML Scheduled Report Distribution Daily`, `goAML Scheduled Report Distribution Weekly`, `goAML Manager Report Daily CSV`, `goAML Executive Report Weekly PDF`, `goAML Reporting Alerts Daily`, `goAML Scheduled Report Distribution Monthly`, and `goAML Scheduled Report Distribution Quarterly`
- the first live monitoring rollout captured:
  - a production drift baseline for scorer version `2`
  - a stable follow-up drift observation with `amount_psi = 0.0` and `score_psi = 0.0`
  - a live comparison of challenger version `3` against production version `2`

### 7.2 API Endpoints to GPU Host

```text
LLM_PRIMARY_URL = http://160.30.63.152:8000/v1
LLM_FAST_URL    = http://160.30.63.152:8002/v1
EMBED_URL       = http://160.30.63.152:8001/v1
RERANK_URL      = http://160.30.63.152:8003/v1
PARSE_URL       = http://160.30.63.152:8022/v1
OCR_URL         = http://160.30.63.152:8021
PII_URL         = http://160.30.63.152:8020
SCORER_URL      = http://160.30.63.152:8010
```

## 8. What Is Working Right Now

### 8.1 Public UI

Accessible at:

- `http://160.30.63.131/`

Live UI features now include:

- local login overlay and authenticated app shell
- role-aware launchpad, desk visibility, and current-user context
- dedicated `My Profile` page for personal details, landing-desk preference, and self-service security actions
- `Settings` workspace for local auth, local users, role visibility, auth audit, and future WSO2 / OIDC provider fields
- dashboard shell
- transactions view
- transaction investigation workspace
- alerts view
- alert resolution workspace with analyst notes
- cases and SARs view
- AI case summary generation
- investigation context with direct documents, retrieved evidence, screening hits, and graph context
- SAR reviewer / approver queue
- case collaboration notes and task management
- entity profile and resolution workspace
- entity watchlist dashboard
- watchlist case creation and reuse
- entity merge candidate review and merge actions
- entity screening with live sanctions results
- network graph exploration
- graph drilldown and case-centric pathfinding
- direct graph actions from cases, alerts, transactions, and document graph candidates
- document intelligence workspace
- MinIO-backed case evidence uploads and document attachments
- case timeline panel
- case action panel
- SAR preview drawer
- alert-level `Investigate` action

### 8.2 Working APIs

Verified working:

- `GET /health`
- `GET /api/v1/status`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET /api/v1/auth/profile`
- `PATCH /api/v1/auth/profile`
- `POST /api/v1/auth/change-password`
- `GET /api/v1/auth/settings`
- `PUT /api/v1/auth/settings/{provider_key}`
- `GET /api/v1/auth/roles`
- `GET /api/v1/auth/users`
- `POST /api/v1/auth/users`
- `PATCH /api/v1/auth/users/{username}`
- `POST /api/v1/auth/users/{username}/reset-password`
- `GET /api/v1/auth/audit`
- `POST /api/v1/transactions`
- `GET /api/v1/transactions`
- `GET /api/v1/transactions/{id}`
- `GET /api/v1/alerts`
- `PATCH /api/v1/alerts/{id}`
- `GET /api/v1/alerts/{id}`
- `POST /api/v1/alerts/{id}/investigate`
- `POST /api/v1/alerts/{id}/actions`
- `POST /api/v1/screen`
- `GET /api/v1/sars/queue`
- `GET /api/v1/cases`
- `POST /api/v1/cases`
- `GET /api/v1/cases/{id}`
- `PATCH /api/v1/cases/{id}`
- `GET /api/v1/cases/{id}/events`
- `GET /api/v1/cases/{id}/context`
- `POST /api/v1/cases/{id}/summary`
- `GET /api/v1/cases/{id}/tasks`
- `POST /api/v1/cases/{id}/tasks`
- `PATCH /api/v1/cases/{id}/tasks/{task_id}`
- `GET /api/v1/cases/{id}/notes`
- `POST /api/v1/cases/{id}/notes`
- `POST /api/v1/cases/{id}/sar`
- `POST /api/v1/cases/{id}/sar/review`
- `GET /api/v1/cases/{id}/sar`
- `POST /api/v1/cases/{id}/sar/file`
- `GET /api/v1/documents`
- `GET /api/v1/documents/{id}`
- `POST /api/v1/documents/analyze`
- `POST /api/v1/cases/{id}/documents/analyze`
- `POST /api/v1/cases/{id}/documents/{document_id}/attach`
- `GET /api/v1/entities`
- `GET /api/v1/entities/watchlist`
- `GET /api/v1/entities/{id}`
- `POST /api/v1/entities/{id}/resolve`
- `POST /api/v1/graph/explore`
- `POST /api/v1/graph/drilldown`
- `POST /api/v1/graph/pathfind`
- `POST /api/v1/graph/sync`

### 8.3 Live Case Workflow Already Verified

Verified case:

- `CASE-2026-0800`

Verified events:

- `created`
- `updated`
- `sar_drafted`
- `sar_filed`

### 8.4 LLM Drafting Verified

Verified test case:

- `CASE-2026-0801`

Verified SAR:

- `SAR-6906D66717F9`
- `ai_drafted: true`
- `ai_model: Qwen3-32B`

This confirms the SAR narrative is currently being drafted by the live GPU-hosted LLM, not only by a template fallback.

### 8.5 AI Investigation Context and Summary Verified

Verified live:

- `GET /api/v1/cases/{id}/context` returns:
  - linked alerts
  - linked transactions
  - direct case documents
  - screening hits
  - semantically retrieved documents from Milvus
  - reranked evidence
  - graph expansion from Neo4j
- `POST /api/v1/cases/{id}/summary` generates and stores:
  - `ai_summary`
  - `ai_risk_factors`
  - `ai_summary_generated` case event

This confirms the analyst workspace already has retrieval-backed case context plus an LLM summary layer, not just manual case notes.

### 8.6 Reviewer / Approver and Watchlist Queues Verified

Verified queue state after the latest pristine reseed:

- SAR review queue counts:
  - draft/rejected: `0`
  - pending review: `4`
  - approved / ready to file: `4`
  - filed: `10`
  - total SARs: `18`
- example review queue case refs:
  - `CASE-SD-0016`
  - `CASE-SD-0015`
  - `CASE-SD-0014`
- example approval queue case refs:
  - `CASE-SD-0012`
  - `CASE-SD-0011`
  - `CASE-SD-0010`

Verified watchlist dashboard state after the latest pristine reseed:

- active watchlist entities: `12`
- removed watchlist entities: `0`
- active watchlist entities with open review cases: `2`
- critical watchlist entities: `6`
- total watchlist entities: `12`
- example watchlist entities:
  - `East Pier Exports PLC`
  - `Atlas Capital Pte Ltd`
  - `Harborline Ventures PLC`
  - `Farah Habib`
  - `Sajid Latif`
- example open review cases linked from the watchlist:
  - `CASE-SD-0037`
  - `CASE-SD-0036`

### 8.7 Screening, Graph, and Documents Verified

Verified live:

- `POST /api/v1/screen` returns public-source sanctions matches without a commercial delivery token
- `POST /api/v1/graph/explore` returns connected graph data for cases, alerts, transactions, and screening hits
- `POST /api/v1/graph/drilldown` returns persisted Neo4j relationship evidence for cases, alerts, transactions, accounts, documents, and screening hits
- `POST /api/v1/graph/pathfind` returns case-centric and counterparty paths across the persisted Neo4j graph
- `POST /api/v1/graph/sync` maintains a persisted investigation graph from PostgreSQL into Neo4j
- `POST /api/v1/documents/analyze` stores analyst-submitted documents with:
  - OCR support for image uploads
  - structured extraction
  - PII/entity extraction
  - embedding generation
  - Milvus vector indexing
- `POST /api/v1/cases/{id}/documents/analyze` stores raw files in MinIO and attaches them directly to the case
- `POST /api/v1/cases/{id}/documents/{document_id}/attach` links previously analyzed documents into case evidence

Verified document example:

- document id `55d235c4-c19a-48da-8c82-5d95cf4e45bd`
- `vector_status: embedded_in_milvus`
- `pii_detected: true`
- `parse_applied: true`

Verified OCR smoke-test example:

- document id `2a465a79-52c0-40ed-908a-4b7320ca1ee3`
- `ocr_applied: true`
- `parse_applied: true`
- `pii_detected: true`
- `vector_status: embedded_in_milvus`
- OCR response mode currently: `cuda`

### 8.8 Dense Seed Dataset Verified

The platform now includes a large seeded AML investigation dataset for demos, testing, and analyst workflow validation.

Latest verified seed batch:

- seed tag: `synthetic_aml_dense_v1`
- accounts: `60`
- entities: `48`
- transactions: `756`
- alerts: `160`
- cases: `42`
- documents: `108`
- screening results: `120`
- SARs: `16`
- persisted Neo4j graph: `1365` nodes and `3251` edges

This dataset is safe to refresh because the seed workflow only replaces prior rows created by the same seed tag and leaves unrelated live data untouched.

### 8.9 Case Command Center Verified

Verified live on `160.30.63.131`:

- the Command Center is now the default case-open experience from case rows, alert investigation flows, and other case-linked pivots
- the center workspace is tabbed:
  - `Overview`
  - `Evidence`
  - `Graph`
  - `Documents`
  - `Timeline`
  - `SAR`
- the right rail now includes:
  - filing readiness
  - action rail
  - case-specific workflow state
  - SAR preview
- analysts can pin evidence from:
  - alerts
  - transactions
  - direct documents
  - retrieved documents
  - screening hits
  - graph relationships
- pinned evidence supports:
  - importance boosting/lowering
  - `include in SAR`
  - removal
- filing readiness is now computed and visible as a first-class panel with blocker-to-tab guidance
- workflow state now exposes:
  - expected next role
  - Camunda task/process summary
  - process history
  - latest automation touches
  - deeplinked notifications
  - quick jumps to Workflow Ops, n8n, and Camunda
- the SAR tab now supports:
  - structured draft editing
  - reviewer/approver note visibility
  - evidence-in-filing view
  - narrative comparison between original/current/final variants
  - `save draft details`
- filing packs are now exportable directly from the Command Center as analyst-ready artifacts:
  - `JSON`
  - `PDF`
  - `DOCX`
- the exported artifact includes:
  - case metadata
  - workflow state
  - filing evidence
  - supporting evidence
  - notes/tasks when requested
  - AI summary when requested
  - SAR narrative context and collaboration data

Representative verified case:

- `CASE-2026-0810`
- workflow expected role: `reviewer`
- process history count: `1`
- filing readiness: `blocked` with score `73`
- pinned evidence count: `1`

### 8.10 Local Auth and RBAC Verified

Verified live:

- `analyst1` can sign in through the public UI and access investigation desks
- `admin1` can access the `Settings` desk and manage local auth/provider settings
- `analyst1` receives `403` on model-governance routes such as `GET /api/v1/model-ops/scorer`
- `modelops1` can access `Model Ops`
- the public UI hides desks a user is not allowed to open
- auth audit events are recorded for login and logout

This confirms the analyst product now has real local auth and permission gating rather than anonymous desk access.

### 8.11 Profile and Session Experience Verified

Verified live on `160.30.63.131`:

- the top bar now exposes `Profile`, `Settings`, and `Logout`
- the `My Profile` page supports:
  - editable identity details
  - timezone and locale preferences
  - preferred landing-desk selection
  - self-service password change
- `GET /api/v1/auth/profile` returns the current user profile and preference bundle
- `PATCH /api/v1/auth/profile` persists profile changes successfully
- `POST /api/v1/auth/logout` cleanly ends the local session

This turns the auth layer into a complete user-facing login/profile flow rather than a backend-only RBAC scaffold.

## 9. Latest Changes Implemented So Far

### 9.1 Phase 2 Backend Extensions

Implemented:

- transaction ingest, scoring, alert generation, and transaction detail APIs
- alert detail endpoint
- alert investigation action
- alert resolution actions for dismiss, false positive, escalate, and analyst notes
- case create/list/detail/update
- case timeline endpoint
- case investigation context endpoint
- AI case summary endpoint
- case workspace aggregation endpoint
- case workflow state endpoint
- case filing readiness endpoint
- pinned case evidence list/pin/update/delete endpoints
- case collaboration note and task endpoints
- SAR draft endpoint
- SAR draft update endpoint
- SAR review / approval endpoint
- SAR file endpoint
- SAR reviewer / approver queue endpoint
- SAR read/preview endpoint
- document list/detail/analyze endpoints
- case document analyze and attach endpoints
- entity list endpoint
- entity profile endpoint
- entity resolution endpoint
- entity watchlist dashboard endpoint
- graph explore endpoint
- graph sync endpoint
- screening endpoint with better error handling

### 9.2 UI Enhancements

Implemented:

- live transactions from API
- transaction investigation workspace
- live alerts from API
- alert resolution workspace
- live cases from API
- case detail panel
- case timeline rendering
- case status update
- case assignment update
- case notes and team tasks panel
- SAR draft action
- SAR review / approve / reject actions
- SAR file action
- dedicated SAR review queue page
- alert `Investigate` button
- SAR preview drawer
- entity profile and entity resolution workspace
- watchlist dashboard page with open-case links
- graph canvas and graph summary panel
- graph drilldown and pathfinding panels
- direct graph launch from alerts and transactions
- document analysis workspace
- OCR smoke-test path from the UI
- one-click graph exploration from document graph candidates
- case evidence attachment from retrieved documents
- AI case summary action in the case workspace
- entity watchlist case actions
- entity merge workflow controls
- Case Command Center as the default case-open path
- classic timeline retained as a fallback path
- tabbed case workspace with `Overview`, `Evidence`, `Graph`, `Documents`, `Timeline`, and `SAR`
- pinned evidence board with evidence pinning from alerts, transactions, documents, screening hits, and graph relationships
- filing readiness panel with jump-to-action guidance
- case-specific workflow panel with Camunda/n8n visibility and deeplinked notifications
- reviewer-grade SAR editing, narrative comparison, and evidence-in-filing workflow

### 9.3 Screening Fix

`yente` previously failed because:

- it used the commercial manifest
- no `OPENSANCTIONS_DELIVERY_TOKEN` was configured

Alternative implemented:

- switched `yente` to the built-in public `civic.yml` manifest
- screening now works against public-source matches without a commercial token
- OFAC-style fallback logic is available if upstream screening is temporarily unavailable
- the app still has graceful fallback behavior if indexing or upstream search is temporarily unavailable

### 9.4 Intelligence and Graph Implementation

Implemented:

- MinIO-backed raw document storage
- Milvus vector indexing for analyzed documents
- retrieval-backed case context using embeddings and rerank
- persisted Neo4j graph synchronization from PostgreSQL
- graph exploration, drilldown, and pathfinding APIs
- direct graph evidence launch from cases, alerts, transactions, and document candidates
- AI case summaries stored back onto cases with risk factors

### 9.5 Entity Resolution and Watchlist Workflows

Implemented:

- watchlist confirmation
- PEP confirmation
- sanctions confirmation
- entity notes and resolution history
- create or reuse watchlist review case
- remove from watchlist
- duplicate candidate review
- duplicate merge workflow with linked-record consolidation
- watchlist dashboard with open-case counts

### 9.6 Model Integration Fix

Implemented:

- app-side model URLs aligned to the real GPU host instead of stale internal names
- OCR container corrected to run in true CUDA mode on `gpu-01`
- Qwen3-32B wired into SAR drafting and AI case summaries
- embedding, rerank, parse, PII, and scorer URLs aligned to the live inference host

### 9.7 Runtime Hardening During This Work

Fixed:

- JSON/string normalization issues from Postgres rows
- `sar_ref` generation
- SAR filing state transition
- case/SAR UI workflow continuity
- duplicate-case prevention on repeated alert investigation
- persisted Neo4j graph synchronization plus graph-first analyst workflows
- safe dense-data seeding for demo and workflow validation
- Command Center routing and deeplink continuity after rebuilds
- Nginx/UI recovery after case workspace deploys

## 10. Screening Without an OpenSanctions API Key

You said you do not have an OpenSanctions API key. The practical alternative now in place is:

- use the public OpenSanctions data catalog via `yente`'s built-in `civic.yml`
- keep OFAC-style fallback matching logic available inside the app
- no delivery token required
- slower first-time indexing on first startup
- once the public catalog is indexed, screening works against public data

Current state:

- public-data screening is live
- `/api/v1/screen` is returning real matches
- fallback handling remains in place for resilience during future re-index cycles

Recommended follow-up after indexing completes:

1. keep the public catalog for now
2. optionally add recurring re-screen jobs and screening watchlists
3. only move to delivery token later if you need fresher or broader managed datasets

## 11. Implementation Phases

### Phase 1 — Infrastructure and Base Platform

Status: complete and live

Included:

- multi-service Docker deployment
- storage, workflow, graph/vector, and UI layers
- GPU inference host
- model-serving APIs

### Phase 2 — Integration and Data Wiring

Status: implemented and live for core analyst workflows

Completed or substantially completed:

- FastAPI route handlers for transactions, alerts, cases, screening
- PostgreSQL business schema
- ClickHouse schema
- case workflows
- alert investigation flow
- alert resolution flow with analyst notes
- case timelines
- SAR draft and file flow
- analyst UI wiring for alerts/cases/SARs
- analyst UI wiring for screening, graph exploration, and document intelligence
- default Command Center case-open behavior
- case workspace aggregation, pinned evidence, and filing readiness
- document registry backed by PostgreSQL
- raw document storage in MinIO
- embedding generation and Milvus vector write path
- direct case document attachment workflow
- persistent Neo4j graph synchronization from PostgreSQL
- graph drilldown, relationship evidence, and pathfinding from the analyst UI
- entity profile workspace and watchlist dashboard
- collaboration notes and tasks
- unattended n8n watchlist re-screen schedules
- automated SAR queue rebalancing from SLA analytics
- automatic case escalation and follow-up task creation when watchlist re-screening finds new matches
- seeded AML dataset for dense end-to-end workflow testing

Still maturing in Phase 2:

- graph/vector retrieval can be pushed deeper into analyst case workflows
- broader workflow automation across n8n / Camunda is still limited outside the watchlist re-screen runner

### Phase 3 — Model Integration

Status: materially implemented and live

Completed:

- app connected to `Qwen3-32B` for live SAR narrative drafting
- app connected to `Qwen3-32B` for live AI case summaries
- app connected to public-source sanctions screening through `yente`
- app connected to GLiNER PII for live document/entity extraction
- app connected to embeddings for Milvus-backed document indexing
- app connected to rerank for retrieval-backed case context
- app connected to CUDA-backed OCR for image-based document ingestion
- app connected to parse for structured extraction
- app connected to XGBoost scoring for transaction monitoring

Planned next in Phase 3:

- deepen OCR and Parse usage for harder semi-structured and multilingual document ingestion
- connect PII extraction outputs into entity resolution workflows
- expand `Qwen3-8B` usage for fast triage and summarization

### Phase 4 — Workflow and Investigation Depth

Status: substantially implemented and operational

Already implemented in this phase:

- default Case Command Center as the case-first analyst workspace
- reviewer-grade tabbed case review with filing-readiness and evidence packaging
- SAR draft, review, approval, reject, and filing lifecycle
- first-class reviewer / approver queues
- reviewer / approver SLA dashboards and workload analytics
- escalation routing by analyst team and inferred region
- automated SAR queue workload rebalance through n8n
- SLA breach notification dispatch and notification history tracking
- entity watchlist dashboard and review-case entry points
- recurring watchlist re-screen automation through n8n
- automatic watchlist review-case escalation on new screening matches
- formal Camunda orchestration for SAR review and watchlist escalation flows
- dedicated analyst-facing Workflow Ops, n8n Monitor, and Camunda dashboards with live polling
- entity merge and watchlist resolution workflows
- analyst collaboration notes and tasks
- executive KPI and operational reporting in Reporting Studio
- manager outcome reporting and trend boards
- exportable management reports in JSON, CSV, PDF, and DOCX
- scheduled daily manager and weekly executive reporting through n8n

Still planned:

- broader automated workflows through n8n and Camunda beyond SAR and watchlist flows
- additional recurring watchlist review playbooks beyond re-screening
- richer entity merge confidence and entity resolution automation
- deeper alert, case, and entity collaboration workflows
- richer stakeholder-specific delivery channels and alert routing on top of the live manager / executive / compliance / board reporting templates

### Phase 5 — Enterprise Hardening

Planned:

- WSO2 / OIDC identity integration as a provider swap on top of the live local auth model
- deeper row-level authorization, step-up auth, and audit policy refinement
- HTTPS and secret rotation
- Prometheus / Grafana monitoring
- backups and retention
- load testing and security review

## 12. Recommended Near-Term Roadmap

### 12.1 Immediate Next Steps

1. Add richer report delivery channels and stakeholder targeting on top of the live distribution-rule engine
2. Add notification-channel completion for scheduled reports once SMTP / Slack credentials are available
3. Drive more analyst workflows through n8n, Camunda, and LangGraph orchestration
4. Add recurring compliance playbooks beyond the watchlist re-screen runner
5. Extend graph actions and evidence packs deeper into end-to-end alert and document workflows

### 12.2 After That

1. Improve entity resolution confidence scoring and duplicate automation
2. Expand report drill-downs and historical snapshots deeper into ClickHouse and Superset
3. Introduce WSO2 identity when ready
4. Add role-aware approvals and audit controls
5. Expand stakeholder delivery and operational notifications across the reporting layer

## 13. Future Enhancements

Planned future enhancements likely to add the most value:

- attachment support on alerts and SARs
- LLM-assisted alert explanation
- document evidence packs for SARs
- pinned-evidence-aware summary and SAR prompt composition
- deeper queue balancing and SLA escalation automation
- recurring watchlist review, re-screen, and downstream case escalation playbooks
- automated entity merge suggestions
- model routing between `Qwen3-8B` and `Qwen3-32B`
- MLflow-backed scorer evaluation gates, rollback controls, and champion/challenger workflow
- role-aware approval policies
- dashboard drill-downs into ClickHouse analytics

## 14. End-to-End System Map

```mermaid
flowchart TD
    A[Transactions / Entities / Documents] --> B[FastAPI]
    B --> C[Risk scoring]
    B --> D[Screening]
    B --> E[Case management]
    B --> F[Document pipeline]
    B --> G[Entity resolution]
    B --> H[Graph sync]

    C --> C1[XGBoost scorer]
    C1 --> C2[Alerts]

    D --> D1[Yente]
    D1 --> D2[OpenSanctions public catalog]
    D1 --> D3[Screening results]

    E --> E1[Cases]
    E1 --> E2[Case events]
    E1 --> E3[Case context]
    E3 --> E4[Qwen3-32B summary]
    E1 --> E5[SAR draft]
    E5 --> E6[Qwen3-32B]
    E6 --> E7[SAR preview]
    E7 --> E8[Review queue]
    E8 --> E9[Approval queue]
    E9 --> E10[SAR filing]

    F --> F1[Tika]
    F --> F2[OCR]
    F2 --> F3[Parse]
    F3 --> F4[PII]
    F4 --> F5[Embeddings]
    F5 --> F6[Milvus]
    F6 --> F7[Rerank]
    F --> F8[MinIO]

    G --> G1[Entity profile]
    G1 --> G2[Watchlist dashboard]
    G1 --> G3[Merge and review actions]

    H --> H1[Neo4j]
    H1 --> H2[Explore, drilldown, pathfind]

    C2 --> UI[Analyst UI]
    D3 --> UI
    E2 --> UI
    E4 --> UI
    E7 --> UI
    G2 --> UI
    H2 --> UI
```

## 15. Source of Truth Files

### Local project documentation

- [goAML-V2-PROJECT-OVERVIEW.md](/Users/ze/Documents/goaml-v2/goAML-V2-PROJECT-OVERVIEW.md)
- [gpu-01-running-models.md](/Users/ze/Documents/goaml-v2/gpu-01-running-models.md)
- [goaml-v2-project-overview-v3.md](/Users/ze/Documents/goaml-v2/goaml-v2-project-overview-v3.md)
- [implementation-plan-v3.md](/Users/ze/Documents/goaml-v2/implementation-plan-v3.md)
- [case-command-center-design-spec.md](/Users/ze/Documents/goaml-v2/case-command-center-design-spec.md)
- [case-command-center-implementation-tasks.md](/Users/ze/Documents/goaml-v2/case-command-center-implementation-tasks.md)

### App-side deployment copy

- [remote-goaml-v2-install](/Users/ze/Documents/goaml-v2/remote-goaml-v2-install)
- [GPU_MODEL_API_INTEGRATION.md](/Users/ze/Documents/goaml-v2/remote-goaml-v2-install/GPU_MODEL_API_INTEGRATION.md)

### Model-side deployment copy

- [remote-gpu-01-models](/Users/ze/Documents/goaml-v2/remote-gpu-01-models)

## 16. Practical Status Summary

If someone new joins the project today, the correct mental model is:

- the platform is already deployed and usable
- the app and GPU model planes are cleanly separated
- Phase 2 is mostly real, not aspirational
- sanctions screening no longer needs a commercial token and is already returning live public-data matches
- SAR drafting is already using `Qwen3-32B`
- AI case summaries, graph exploration, pathfinding, and document intelligence are live in the analyst UI
- the Case Command Center is now the default case workspace and reflects live workflow state
- local auth, RBAC desk gating, auth audit, and settings-driven future WSO2 provider forms are live
- the user-facing login, logout, and `My Profile` flow is live, including landing-desk preference
- dense seeded AML data is in place for realistic demos and workflow testing
- reviewer / approver queues and the watchlist dashboard are now first-class analyst workspaces
- Workflow Ops, n8n Monitor, and Camunda dashboards are live in the analyst UI
- Camunda is now tracking live goAML SAR and watchlist process instances with routed tasks
- Phase 4 workflow depth is now materially real, while enterprise hardening is still ahead
- the next work should focus on richer retrieval-assisted investigations, recurring review automation, workload analytics, MLflow-driven scorer lifecycle management, and operational hardening

## 17. Competitive Gap Analysis

This section compares the current platform against a serious real-world AML workbench, excluding enterprise hardening items such as external identity, TLS, backup policy, and infrastructure security controls.

### 17.1 Overall Position

Current position:

- clearly beyond prototype stage
- stronger than many internal AML tools on feature breadth and AI-assisted investigation depth
- credible as a serious pilot or internal v1 platform
- not yet at the workflow polish, reporting depth, and operational maturity of a mature commercial AML suite

Practical maturity read:

- compared to a typical internal build: ahead
- compared to a serious pilot deployment: strong
- compared to an established commercial platform: still behind, but with a solid product foundation already in place

### 17.2 Analyst Workflow

Current strength: strong

What is already competitive:

- end-to-end alert, case, review, approval, and filing workflow is live
- the Case Command Center provides a credible daily analyst workspace
- notes, tasks, evidence pinning, filing readiness, and exports are already integrated into case work
- watchlist and entity workflows are first-class instead of being separate admin-only tools

Main gaps versus mature products:

- bulk triage and bulk review actions are still limited
- saved views, saved filters, analyst-specific workspaces, and queue personalization are not yet deep
- cross-case investigation management is still lighter than vendor-grade products
- structured investigation playbooks and checklist-driven workflows can go further
- alert closure, reopen, false-positive review, and feedback-loop tooling can still be deepened

### 17.3 Investigation Intelligence

Current strength: very strong for this stage

What is already competitive:

- retrieval-augmented investigation context is live
- OCR, Parse, PII, embeddings, rerank, graph exploration, and pathfinding are all connected into analyst workflows
- AI summaries and SAR drafts are grounded on retrieved and pinned evidence
- document intelligence is operational, not just demonstrational

Main gaps versus mature products:

- entity resolution confidence and merge logic need more sophistication
- alert explanation and typology reasoning can be richer and more transparent
- evidence ranking and provenance explanation can be more explicit to analysts
- cross-case pattern detection and higher-order behavioral clustering are still early
- evaluation and tuning workflow for retrieval quality is not yet very mature

### 17.4 Model Governance

Current strength: moderate

What is already competitive:

- multiple live inference services are deployed and genuinely used
- XGBoost scoring is in the transaction path
- LLM outputs are grounded on evidence instead of being free-form
- MLflow is already deployed as registry and tracking infrastructure
- MLflow-backed scorer registration, promotion, deployment, and runtime lineage are live
- the analyst UI now exposes a dedicated `Model Ops` view for scorer version visibility, approval workflow, challenger evaluation, and drift state

Main gaps versus mature products:

- champion/challenger evaluation is now live, but offline benchmark management and scheduled candidate testing are still light
- prompt/version lineage and analyst feedback loops need stronger governance
- ongoing model drift monitoring and alerting are live, but long-horizon quality tracking is still early-stage

### 17.5 Reporting and Operations

Current strength: moderate and improving quickly

What is already competitive:

- reviewer / approver queues, workload balancing, and SLA views are live
- notification history, n8n visibility, Camunda visibility, and workflow dashboards are live
- historical SLA snapshots and trend dashboards now exist

Main gaps versus mature products:

- manager reporting is still thinner than a mature compliance operations suite
- throughput, conversion, false-positive, and queue-quality analytics need more depth
- team/region/analyst drilldown reporting should be stronger
- Superset and ClickHouse analytics can be pushed further into daily operations
- monthly and audit-oriented reporting is not yet fully productized

### 17.6 Product UX Maturity

Current strength: moderate to strong

What is already competitive:

- the product now has a real workbench feel, not a disconnected demo feel
- the Command Center gives the platform a coherent center of gravity
- analyst-facing operations dashboards now exist inside the same UI

Main gaps versus mature products:

- consistency across pages can still improve
- some modules are feature-rich before they are fully streamlined for speed
- dense power-user workflows, keyboard-driven actions, and saved layouts are still limited
- filtering, drilldown, and cross-workspace continuity can still be polished further

### 17.7 Bottom-Line Assessment

If enterprise hardening is excluded, the current platform is best described as:

- a serious, usable AML analytics and investigation platform
- stronger than many internal first-generation tools
- good enough for realistic pilot or internal operations scenarios
- still short of the workflow polish, model governance maturity, and reporting depth of the best established AML vendors

The most important remaining gaps to close are:

- MLflow-driven scorer lifecycle control
- deeper management and compliance reporting
- faster analyst workflows through bulk operations and saved workspaces
- stronger entity resolution and typology/explanation depth
- continued polish of the Command Center and queue experience
