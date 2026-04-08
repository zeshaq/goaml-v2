# goAML-V2 — Complete Project Overview

> **Anti-Money Laundering Intelligence Platform**
> A multi-service, GPU-accelerated AML detection system spanning ML inference, document intelligence, graph analytics, and workflow automation.

---

## Table of Contents

1. [Project Summary](#1-project-summary)
2. [Infrastructure](#2-infrastructure)
3. [Architectural Overview](#3-architectural-overview)
4. [Layer 1 — Storage Layer](#4-layer-1--storage-layer)
5. [Layer 2 — Graph & Vector Layer](#5-layer-2--graph--vector-layer)
6. [Layer 3 — Document Intelligence Layer](#6-layer-3--document-intelligence-layer)
7. [Layer 4 — ML Inference Layer (NIM Stack)](#7-layer-4--ml-inference-layer-nim-stack)
8. [Layer 5 — Agent & Orchestration Layer](#8-layer-5--agent--orchestration-layer)
9. [Layer 6 — Workflow Automation Layer](#9-layer-6--workflow-automation-layer)
10. [Layer 7 — Application Layer](#10-layer-7--application-layer)
11. [NIM Model Stack Reference](#11-nim-model-stack-reference)
12. [Data Flow: End-to-End AML Pipeline](#12-data-flow-end-to-end-aml-pipeline)
13. [Service Port Map](#13-service-port-map)
14. [Key Design Decisions](#14-key-design-decisions)

---

## 1. Project Summary

**goAML-V2** is a production-grade financial crime intelligence platform designed to detect, investigate, and report money laundering activity. The platform integrates:

- **GPU-accelerated LLM inference** via NVIDIA NIM containers
- **Graph analytics** on entity relationship networks
- **Document parsing** with OCR and layout understanding
- **ML scoring** for transaction anomaly detection
- **Automated workflow** orchestration for case management

The system is organized into **18 services** across **7 architectural layers**, each with defined responsibilities and inter-service contracts.

---

## 2. Infrastructure

### Hardware

| Component | Specification |
|---|---|
| Primary Server | 512-core AMD EPYC |
| RAM | 1.5 TB |
| Storage | 15 TB NVMe |
| GPU Server | 2× NVIDIA L40S (48 GB VRAM each, 96 GB total) |
| GPU Access | NVIDIA AI Enterprise (full NIM catalog) |

### Infrastructure Map

```mermaid
graph TB
    subgraph GPU_Server["GPU Server — 2× NVIDIA L40S (96 GB VRAM)"]
        GPU1["L40S #1 (48 GB)\nllama-3.3-70b FP8 TP=2"]
        GPU2["L40S #2 (48 GB)\nllama-3.3-70b FP8 TP=2"]
    end

    subgraph Primary_Server["Primary Server — 512-core AMD EPYC / 1.5 TB RAM / 15 TB NVMe"]
        CPU_MODELS["CPU-bound NIM Models\ngliner-pii · llama-3.1-8b\nnv-embedqa-e5-v5 · rerank"]
        TRITON["Triton FIL\nXGBoost :8010"]
        SERVICES["Platform Services\nPostgres · ClickHouse · Redis\nNeo4j · Milvus · n8n · Camunda\nFastAPI · React · Nginx"]
    end

    GPU1 & GPU2 --> CPU_MODELS
    TRITON --> SERVICES
```

---

## 3. Architectural Overview

The platform is structured as seven discrete layers. Each layer depends only on the layers below it, enabling independent scaling and replacement of components.

```mermaid
graph TD
    L7["Layer 7 — Application\nFastAPI · React UI · Superset · Nginx"]
    L6["Layer 6 — Workflow Automation\nn8n · Camunda"]
    L5["Layer 5 — Agent & Orchestration\nLangGraph · MCP Server · MLflow"]
    L4["Layer 4 — ML Inference (NIM Stack)\nLLMs · Embeddings · Rerank · OCR · PII · XGBoost"]
    L3["Layer 3 — Document Intelligence\nNemotron OCR · Nemotron Parse · OpenSanctions"]
    L2["Layer 2 — Graph & Vector\nNeo4j · Milvus"]
    L1["Layer 1 — Storage\nPostgreSQL · ClickHouse · Redis"]

    L7 --> L6
    L6 --> L5
    L5 --> L4
    L5 --> L3
    L4 --> L2
    L3 --> L2
    L2 --> L1

    style L7 fill:#1a3a5c,color:#fff
    style L6 fill:#1e4d6b,color:#fff
    style L5 fill:#245f7a,color:#fff
    style L4 fill:#2a7289,color:#fff
    style L3 fill:#308597,color:#fff
    style L2 fill:#3698a6,color:#fff
    style L1 fill:#3cabaf,color:#fff
```

---

## 4. Layer 1 — Storage Layer

The storage layer provides durable, queryable persistence for all platform data. Three engines serve distinct access patterns:

- **PostgreSQL** — transactional records: cases, alerts, audit logs, user state
- **ClickHouse** — high-throughput analytical queries over transaction history and time-series signals
- **Redis** — low-latency caching, session state, and pub/sub messaging between services

```mermaid
erDiagram
    POSTGRESQL {
        uuid case_id PK
        string status
        timestamp created_at
        jsonb metadata
    }
    POSTGRESQL ||--o{ ALERTS : contains
    ALERTS {
        uuid alert_id PK
        uuid case_id FK
        float risk_score
        string alert_type
    }
    CLICKHOUSE {
        string tx_id PK
        string account_id
        float amount
        timestamp tx_time
        string currency
    }
    REDIS {
        string key
        string value
        int ttl_seconds
    }

    POSTGRESQL ||--|{ CLICKHOUSE : "feeds analytics"
    POSTGRESQL ||--|{ REDIS : "caches state"
```

---

## 5. Layer 2 — Graph & Vector Layer

This layer provides two specialized data structures that are central to AML intelligence:

- **Neo4j** — stores the entity relationship graph: accounts, persons, companies, transactions, and ownership chains. Graph traversal enables detection of layering schemes, shell company networks, and unusual transaction patterns.
- **Milvus** — stores dense vector embeddings produced by the embedding NIM. Enables semantic similarity search over documents, entities, and transaction narratives.

```mermaid
graph LR
    subgraph Neo4j["Neo4j — Entity Graph"]
        PERSON["Person Node"]
        ACCOUNT["Account Node"]
        COMPANY["Company Node"]
        TX["Transaction Edge"]
        OWNS["OWNS Relationship"]
        CONTROLS["CONTROLS Relationship"]

        PERSON -- OWNS --> ACCOUNT
        PERSON -- CONTROLS --> COMPANY
        COMPANY -- OWNS --> ACCOUNT
        ACCOUNT -- TX --> ACCOUNT
    end

    subgraph Milvus["Milvus — Vector Store"]
        COLL["Collection: documents"]
        IDX["HNSW Index"]
        EMBED["768-dim Embeddings\n(nv-embedqa-e5-v5)"]
        COLL --> IDX --> EMBED
    end

    Neo4j <-->|"Entity Resolution"| Milvus
```

---

## 6. Layer 3 — Document Intelligence Layer

This layer handles ingestion and parsing of unstructured financial documents — statements, KYC forms, wire transfer records, sanctions lists.

- **nemotron-ocr-v1** (`:8021`) — GPU-powered OCR, replacing the legacy Apache Tika path
- **nemotron-parse** (`:8022`) — 885M VLM that understands document layout and structure; works in tandem with OCR v1
- **OpenSanctions** — reference data source providing up-to-date global sanctions, PEP, and watchlist data for entity screening

```mermaid
sequenceDiagram
    participant Ingest as Document Ingestor
    participant OCR as nemotron-ocr-v1 :8021
    participant Parse as nemotron-parse :8022
    participant PII as gliner-pii :8020
    participant Sanctions as OpenSanctions
    participant Storage as Neo4j / Milvus

    Ingest->>OCR: Raw PDF / Scan
    OCR-->>Parse: OCR Text + Bounding Boxes
    Parse-->>PII: Structured Content (tables, fields)
    PII-->>Storage: Extracted Entities (names, accounts, dates)
    Storage->>Sanctions: Entity Lookup
    Sanctions-->>Storage: Sanctions Match Result
```

---

## 7. Layer 4 — ML Inference Layer (NIM Stack)

The inference layer is the computational core of the platform. All models are served via NVIDIA NIM containers, providing OpenAI-compatible APIs.

```mermaid
graph TD
    subgraph NIM_Containers["NVIDIA NIM Inference Services"]
        LLM70B["llama-3.3-70b-instruct\n:8000 | FP8 | TP=2\nPrimary reasoning & generation"]
        LLM8B["llama-3.1-8b-instruct\n:8002\nFast summarization & classification"]
        EMBED["nv-embedqa-e5-v5\n:8001\nDocument & entity embeddings"]
        RERANK["llama-nemotron-rerank-1b-v2\n:8003\nRetrieval re-ranking"]
        OCR["nemotron-ocr-v1\n:8021\nGPU OCR"]
        PARSE["nemotron-parse\n:8022\n885M VLM layout parser"]
        PII["gliner-pii\n:8020\n55+ PII/PHI types | CPU-capable"]
        XGBOOST["XGBoost via Triton FIL\n:8010\nTransaction risk scoring"]
    end

    AGENT["LangGraph Agent"] --> LLM70B
    AGENT --> LLM8B
    AGENT --> EMBED
    EMBED --> RERANK
    RERANK --> RETRIEVAL["Milvus Retrieval"]
    OCR --> PARSE
    PARSE --> PII
    XGBOOST --> SCORING["Risk Score Output"]
```

### Inference Routing Logic

```mermaid
flowchart LR
    INPUT["Incoming Request"]
    INPUT --> Q{Request Type?}
    Q -- "Complex reasoning\nCase narrative\nSAR drafting" --> LLM70["llama-3.3-70b\n:8000"]
    Q -- "Classification\nQuick summary\nAlert label" --> LLM8["llama-3.1-8b\n:8002"]
    Q -- "Document / entity\nsimilarity search" --> EMB["nv-embedqa-e5-v5\n:8001"]
    Q -- "Re-rank retrieved\nchunks" --> RERANK["nemotron-rerank\n:8003"]
    Q -- "Transaction\nanomaly score" --> XGB["XGBoost / Triton\n:8010"]
    Q -- "PII extraction\nfrom text" --> PII["gliner-pii\n:8020"]
```

---

## 8. Layer 5 — Agent & Orchestration Layer

This layer provides the intelligence coordination infrastructure: agent reasoning loops, tool calling, experiment tracking, and external integration via MCP.

- **LangGraph** — stateful agent graphs managing multi-step AML investigations
- **MCP Server** — Model Context Protocol server exposing platform tools to LLM agents
- **MLflow** — experiment tracking, model registry, and inference artifact versioning

```mermaid
stateDiagram-v2
    [*] --> AlertReceived
    AlertReceived --> EntityExtraction : LangGraph triggers
    EntityExtraction --> GraphLookup : gliner-pii + Neo4j
    GraphLookup --> RiskScoring : XGBoost via Triton
    RiskScoring --> EvidenceRetrieval : score > threshold
    EvidenceRetrieval --> ReasoningLoop : Milvus semantic search
    ReasoningLoop --> NarrativeDraft : llama-3.3-70b
    NarrativeDraft --> HumanReview : Draft SAR / Case file
    HumanReview --> CaseClosed : Approved
    HumanReview --> ReasoningLoop : Needs more evidence
    CaseClosed --> [*]
    RiskScoring --> CaseClosed : score < threshold (auto-dismiss)
```

### MCP Tool Surface

```mermaid
graph LR
    AGENT["LangGraph Agent\n(llama-3.3-70b)"]
    MCP["MCP Server"]
    AGENT --> MCP

    MCP --> T1["graph_query\n(Neo4j Cypher)"]
    MCP --> T2["vector_search\n(Milvus)"]
    MCP --> T3["score_transaction\n(XGBoost/Triton)"]
    MCP --> T4["extract_entities\n(gliner-pii)"]
    MCP --> T5["screen_sanctions\n(OpenSanctions)"]
    MCP --> T6["parse_document\n(OCR + Parse)"]
    MCP --> T7["retrieve_case\n(PostgreSQL)"]
```

---

## 9. Layer 6 — Workflow Automation Layer

This layer handles business process automation and case lifecycle management, bridging the AI inference layer with human investigators.

- **n8n** — event-driven automation: alert routing, notification triggers, data enrichment pipelines, third-party integrations
- **Camunda** — BPMN-based case management for regulatory-compliant AML investigation workflows (STR/SAR filing, escalation paths, deadlines)

```mermaid
graph TD
    subgraph n8n["n8n — Event Automation"]
        TRIGGER["Webhook / Cron Trigger"]
        ENRICH["Data Enrichment Node"]
        NOTIFY["Notification Node\n(Email / Slack)"]
        TRIGGER --> ENRICH --> NOTIFY
    end

    subgraph Camunda["Camunda — Case BPM"]
        CASE_OPEN["Open Case"]
        INVEST["Investigation Task\n(Human)"]
        ESCALATE["Escalation Gate"]
        SAR["File SAR / STR"]
        CLOSE["Close Case"]

        CASE_OPEN --> INVEST
        INVEST --> ESCALATE
        ESCALATE -- "High Risk" --> SAR
        ESCALATE -- "Resolved" --> CLOSE
        SAR --> CLOSE
    end

    n8n --> Camunda
    Camunda --> n8n
```

---

## 10. Layer 7 — Application Layer

The application layer exposes the platform to end users (analysts, compliance officers) and external systems.

- **FastAPI** — REST/WebSocket API gateway; routes requests to appropriate services
- **React UI** — investigator dashboard for case review, graph visualization, alert triage
- **Apache Superset** — BI dashboards for AML trend analysis, KPI monitoring, regulatory reporting
- **Nginx** — reverse proxy, TLS termination, load balancing

```mermaid
graph TD
    USER_ANALYST["Compliance Analyst"]
    USER_MANAGER["AML Manager"]
    EXT_SYS["External Systems\n(Core Banking, SWIFT)"]

    NGINX["Nginx\nReverse Proxy / TLS"]

    USER_ANALYST & USER_MANAGER --> NGINX
    EXT_SYS --> NGINX

    NGINX --> REACT["React UI\nInvestigator Dashboard"]
    NGINX --> FASTAPI["FastAPI\nREST API Gateway"]
    NGINX --> SUPERSET["Apache Superset\nBI & Reporting"]

    FASTAPI --> L5["Agent Layer\n(LangGraph / MCP)"]
    FASTAPI --> L6["Workflow Layer\n(n8n / Camunda)"]
    FASTAPI --> L1["Storage Layer\n(Postgres / ClickHouse)"]
```

---

## 11. NIM Model Stack Reference

All models are locked and confirmed. This table is the authoritative configuration reference.

| Model | Port | Backend | Notes |
|---|---|---|---|
| `nim/meta/llama-3.3-70b-instruct` | 8000 | NIM Container | FP8 quantized, Tensor Parallel = 2 across both L40S |
| `nim/nvidia/nv-embedqa-e5-v5` | 8001 | NIM Container | Primary embedding model; multilingual upgrade tracked |
| `nim/meta/llama-3.1-8b-instruct` | 8002 | NIM Container | Fast inference for classification and summarization |
| `nim/nvidia/llama-nemotron-rerank-1b-v2` | 8003 | NIM Container only | Not in model registry — query via `ngc registry image list --org nim` |
| XGBoost | 8010 | Triton FIL Backend | Transaction anomaly scoring |
| `nim/nvidia/gliner-pii` | 8020 | NIM Container | 55+ PII/PHI entity types; CPU-capable (no GPU contention) |
| `nim/nvidia/nemotron-ocr-v1` | 8021 | NIM Container | Replaces Apache Tika OCR path |
| `nim/nvidia/nemotron-parse` | 8022 | NIM Container | 885M VLM; pairs with OCR v1 for structured parsing |

### GPU Memory Allocation

```mermaid
pie title GPU VRAM Allocation (96 GB total)
    "llama-3.3-70b FP8 (TP=2) — spans both GPUs" : 72
    "nemotron-ocr-v1" : 10
    "nemotron-parse (885M VLM)" : 8
    "Headroom / OS" : 6
```

### NIM Dependency Note

> `llama-nemotron-rerank-1b-v2` exists **only as a NIM container image**, not as downloadable model weights. It must be discovered via:
> ```bash
> ngc registry image list --org nim
> ```
> Do **not** search `ngc registry model list` for this model.

---

## 12. Data Flow: End-to-End AML Pipeline

This diagram shows the complete flow from raw financial data ingestion to SAR filing.

```mermaid
flowchart TD
    A["Raw Input\n(Transactions, Documents, Alerts)"]

    A --> B{Input Type}
    B -- "Transaction Data" --> C["ClickHouse\nTime-series ingest"]
    B -- "Document (PDF/Scan)" --> D["nemotron-ocr-v1 :8021\nOCR Extraction"]
    B -- "Alert from Core Banking" --> E["n8n Webhook Trigger"]

    D --> F["nemotron-parse :8022\nLayout + Structure"]
    F --> G["gliner-pii :8020\nPII / Entity Extraction"]
    G --> H["OpenSanctions\nSanctions Screening"]

    C --> I["XGBoost / Triton :8010\nTransaction Risk Score"]
    I --> J{Score > Threshold?}
    J -- "No" --> K["Auto-dismiss\nLog to PostgreSQL"]
    J -- "Yes" --> L["LangGraph Agent\nInvestigation Graph"]

    H --> L
    L --> M["nv-embedqa-e5-v5 :8001\nEmbed Evidence"]
    M --> N["Milvus\nSemantic Retrieval"]
    N --> O["nemotron-rerank :8003\nRe-rank Retrieved Chunks"]
    O --> P["llama-3.3-70b :8000\nReasoning + SAR Draft"]

    P --> Q["Camunda BPM\nHuman Review Task"]
    Q --> R{Analyst Decision}
    R -- "Approve" --> S["File SAR/STR\nRegulatory Report"]
    R -- "Dismiss" --> K
    R -- "More Evidence" --> L

    S --> T["PostgreSQL\nCase Archive"]
    S --> U["Superset\nCompliance Dashboard"]
```

---

## 13. Service Port Map

```mermaid
graph LR
    subgraph Ports_8000["LLM Inference"]
        P8000[":8000 llama-3.3-70b"]
        P8002[":8002 llama-3.1-8b"]
    end

    subgraph Ports_800X["Embedding & Rerank"]
        P8001[":8001 nv-embedqa-e5-v5"]
        P8003[":8003 nemotron-rerank"]
    end

    subgraph Ports_801X["Scoring"]
        P8010[":8010 XGBoost / Triton FIL"]
    end

    subgraph Ports_802X["Document & PII"]
        P8020[":8020 gliner-pii"]
        P8021[":8021 nemotron-ocr-v1"]
        P8022[":8022 nemotron-parse"]
    end

    subgraph Data_Services["Data Services"]
        PG[":5432 PostgreSQL"]
        CH[":8123 ClickHouse"]
        RD[":6379 Redis"]
        NEO[":7474/:7687 Neo4j"]
        MIL[":19530 Milvus"]
    end

    subgraph App_Services["Application Services"]
        API[":8080 FastAPI"]
        UI[":3000 React UI"]
        SUP[":8088 Superset"]
        NGX[":80/:443 Nginx"]
    end
```

---

## 14. Key Design Decisions

### Why NVIDIA NIM?

NIM containers provide production-ready, optimized inference with OpenAI-compatible APIs. Using the full NVIDIA AI Enterprise catalog allows the platform to run OCR, PII extraction, embeddings, reranking, and LLM reasoning without managing custom model serving infrastructure.

### Why Tensor Parallelism = 2 for llama-3.3-70b?

The 70B model in FP8 requires ~70 GB VRAM. With TP=2, the model is sharded across both L40S GPUs (96 GB total), with headroom for the remaining NIM services.

### Why gliner-pii on CPU?

`gliner-pii` is CPU-capable, which deliberately avoids GPU contention with the inference models. Given the high-throughput PII extraction workload (every parsed document passes through it), keeping it CPU-bound preserves GPU resources for the heavier LLM and OCR workloads.

### Why nemotron-ocr-v1 over Tika?

Apache Tika provides reasonable text extraction for clean PDFs but degrades significantly on scanned documents, low-quality images, and handwritten text. `nemotron-ocr-v1` is GPU-accelerated and designed for financial documents. It integrates directly with `nemotron-parse` for structured layout extraction — a capability Tika does not provide.

### Multilingual Consideration

`llama-nemotron-embed-1b-v2` is being tracked as a potential replacement for `nv-embedqa-e5-v5` when non-English AML source documents (Arabic, French, Bangla, etc.) become a significant portion of the ingest pipeline.

```mermaid
graph LR
    CURRENT["Current\nnv-embedqa-e5-v5 :8001\nEnglish-optimized"]
    FUTURE["Potential Upgrade\nllama-nemotron-embed-1b-v2\nMultilingual"]
    TRIGGER["Trigger: Non-English\ndocument volume\nexceeds threshold"]
    CURRENT -->|"Hot-swap (same port)"| FUTURE
    TRIGGER --> FUTURE
```

---

*Document generated for goAML-V2 platform — internal reference only.*
