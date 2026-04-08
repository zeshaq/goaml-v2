# goAML-V2 — Model Stack Reference

> **Platform:** AML (Anti-Money Laundering) Intelligence Platform  
> **Server:** gpu-01 · 2× NVIDIA L40S (48GB each, 96GB total)  
> **Last updated:** 2026-04-09

---

## Model Registry

| # | Container | Model | Port | Runtime | GPU | Purpose |
|---|---|---|---|---|---|---|
| 1 | `goaml-llm-primary` | `Qwen/Qwen3-32B-FP8` | 8000 | vLLM TP=1 FP8 | GPU 0 | Primary reasoning & analysis LLM |
| 2 | `goaml-embed` | `nvidia/llama-nemotron-embed-1b-v2` | 8001 | vLLM pooling | GPU 1 | Multilingual semantic embeddings |
| 3 | `goaml-llm-fast` | `Qwen/Qwen3-8B-FP8` | 8002 | vLLM FP8 | GPU 1 | Fast/lightweight LLM for routing & drafting |
| 4 | `goaml-rerank` | `nvidia/llama-nemotron-rerank-1b-v2` | 8003 | vLLM pooling | GPU 1 | Re-rank retrieved documents by relevance |
| 5 | `goaml-scorer` | XGBoost (placeholder) | 8010 | FastAPI / CPU | CPU | AML risk scoring — transaction features → probability |
| 6 | `goaml-pii` | `nvidia/gliner-PII` | 8020 | FastAPI / CPU | CPU | PII/PHI detection & redaction (55+ entity types) |
| 7 | `goaml-ocr` | `nvidia/nemotron-ocr-v2` | 8021 | FastAPI / GPU 1 | GPU 1 | Multilingual OCR — scanned docs → text |
| 8 | `goaml-parse` | `nvidia/NVIDIA-Nemotron-Parse-v1.1` | 8022 | vLLM multimodal | GPU 1 | Structured document parsing — images → markdown/JSON |

---

## Model Purposes

### 🧠 Qwen3-32B-FP8 — Primary LLM (Port 8000)
The core reasoning engine. Handles complex AML analysis tasks: SAR (Suspicious Activity Report) narrative generation, entity relationship reasoning, risk explanation, and multi-step agent planning. Thinking mode can be enabled per-request for deeper chain-of-thought on complex cases.

### ⚡ Qwen3-8B-FP8 — Fast LLM (Port 8002)
Lightweight companion to the 32B. Used for tasks that don't require deep reasoning: query classification, intent routing, short-form extraction, summarisation of already-structured data, and drafting simple outputs. Reduces load on the primary model.

### 🔢 llama-nemotron-embed-1b-v2 — Embeddings (Port 8001)
Converts text into 2048-dimensional semantic vectors. Multilingual — handles non-English AML source documents (Arabic, Chinese, French, etc.). Powers the vector search layer in Milvus for RAG retrieval, entity similarity matching, and document deduplication.

### 📊 llama-nemotron-rerank-1b-v2 — Reranker (Port 8003)
Given a query and a list of retrieved documents, scores each document for relevance and reorders them. Sits between Milvus retrieval and LLM context assembly — ensures the most relevant chunks are prioritised within the context window.

### 🔍 gliner-PII — PII Extractor (Port 8020)
Named-entity recognition model fine-tuned for 55+ PII/PHI entity types: persons, organisations, SSNs, account numbers, passport numbers, IP addresses, emails, and more. Runs on CPU. Used to redact sensitive data before storage and to extract structured entities from raw text.

### 📄 nemotron-ocr-v2 — OCR (Port 8021)
Multilingual OCR engine for scanned financial documents — bank statements, invoices, contracts, ID documents. Outputs clean text that feeds into the document intelligence pipeline. Replaces Apache Tika's OCR path.

### 🗂️ NVIDIA-Nemotron-Parse-v1.1 — Document Parser (Port 8022)
Vision-language model that understands document layout. Takes document images and produces structured markdown or JSON — preserving tables, headers, columns, and reading order. Works in tandem with nemotron-ocr-v2: OCR extracts text, Parse extracts structure.

### 🎯 XGBoost Scorer — Risk Scorer (Port 8010)
Gradient-boosted tree model for transaction-level AML risk scoring. Ingests engineered features (transaction amount, frequency, counterparty risk, geography, velocity) and outputs a fraud probability score (0–1). Placeholder until a trained model is available.

---

## Architecture Diagrams

### 1. GPU Memory Layout

```mermaid
block-beta
  columns 2

  block:gpu0["GPU 0 — L40S 48GB"]:1
    llm32["Qwen3-32B-FP8\n~42.5GB\nPort 8000"]
  end

  block:gpu1["GPU 1 — L40S 48GB"]:1
    embed["embed-1b\n~3.2GB\nPort 8001"]
    rerank["rerank-1b\n~3.2GB\nPort 8003"]
    llm8["Qwen3-8B-FP8\n~19.2GB\nPort 8002"]
    parse["Nemotron-Parse\n~9.6GB\nPort 8022"]
    ocr["nemotron-ocr-v2\nshared\nPort 8021"]
  end
```

---

### 2. Full Service Map

```mermaid
graph TB
    subgraph Ingestion["📥 Document Ingestion Layer"]
        DOC[Raw Document\nPDF / Image / Scan]
        OCR[nemotron-ocr-v2\nPort 8021]
        PARSE[Nemotron-Parse-v1.1\nPort 8022]
        PII[gliner-PII\nPort 8020]
    end

    subgraph Intelligence["🧠 Intelligence Layer"]
        EMBED[llama-nemotron-embed-1b-v2\nPort 8001]
        RERANK[llama-nemotron-rerank-1b-v2\nPort 8003]
        LLM_FAST[Qwen3-8B-FP8\nPort 8002]
        LLM_PRIMARY[Qwen3-32B-FP8\nPort 8000]
        SCORER[XGBoost Scorer\nPort 8010]
    end

    subgraph Storage["🗄️ Storage Layer"]
        MILVUS[(Milvus\nVector DB)]
        PG[(PostgreSQL\nRelational)]
        NEO4J[(Neo4j\nGraph DB)]
        REDIS[(Redis\nCache)]
    end

    subgraph Workflow["⚙️ Workflow Layer"]
        LANGGRAPH[LangGraph\nAgent Orchestration]
        N8N[n8n\nWorkflow Automation]
        CAMUNDA[Camunda\nBPMN Engine]
    end

    subgraph App["🖥️ Application Layer"]
        API[FastAPI\nREST API]
        UI[React UI]
        SUPERSET[Apache Superset\nDashboards]
    end

    DOC --> OCR
    DOC --> PARSE
    OCR --> PII
    PARSE --> PII
    PII --> EMBED
    PII --> PG

    EMBED --> MILVUS
    MILVUS --> RERANK
    RERANK --> LLM_PRIMARY
    RERANK --> LLM_FAST

    LLM_FAST --> LANGGRAPH
    LLM_PRIMARY --> LANGGRAPH
    SCORER --> LANGGRAPH

    LANGGRAPH --> NEO4J
    LANGGRAPH --> PG
    LANGGRAPH --> N8N
    N8N --> CAMUNDA

    LANGGRAPH --> API
    API --> UI
    PG --> SUPERSET
    NEO4J --> SUPERSET

    REDIS -.->|cache| RERANK
    REDIS -.->|cache| EMBED
```

---

### 3. Document Intelligence Pipeline

```mermaid
flowchart LR
    A[📎 Uploaded Document] --> B{File Type?}
    B -->|Scanned / Image| C[nemotron-ocr-v2\nPort 8021\nText Extraction]
    B -->|Structured Doc\nwith Layout| D[Nemotron-Parse-v1.1\nPort 8022\nLayout + Structure]
    B -->|Plain Text| E[Direct Text]

    C --> F[gliner-PII\nPort 8020\nEntity Detection]
    D --> F
    E --> F

    F --> G{Action}
    G -->|Store Entities| H[(PostgreSQL\nEntities Table)]
    G -->|Redact PII| I[Redacted Text]
    G -->|Embed| J[llama-nemotron-embed-1b-v2\nPort 8001]

    I --> J
    J --> K[(Milvus\nVector Index)]

    K --> L[llama-nemotron-rerank-1b-v2\nPort 8003\nRetrieval Reranking]
    L --> M[Qwen3-32B-FP8\nPort 8000\nRAG Analysis]
    M --> N[📋 AML Report / SAR Draft]
```

---

### 4. Transaction Risk Scoring Pipeline

```mermaid
flowchart TD
    A[💳 Transaction Event] --> B[Feature Engineering\nAmount · Velocity · Geography\nCounterparty Risk · Time Pattern]
    B --> C[XGBoost Scorer\nPort 8010]
    C --> D{Risk Score}

    D -->|Score < 0.3\nLow Risk| E[✅ Auto-Clear\nLog to PostgreSQL]
    D -->|0.3 ≤ Score < 0.7\nMedium Risk| F[🔍 Enhanced Due Diligence\nRAG Lookup via Milvus]
    D -->|Score ≥ 0.7\nHigh Risk| G[🚨 Alert Queue\nCamunda Workflow]

    F --> H[Qwen3-8B-FP8\nPort 8002\nQuick Analysis]
    G --> I[Qwen3-32B-FP8\nPort 8000\nFull SAR Analysis]

    H --> J[Case Management\nn8n Workflow]
    I --> J
    J --> K[📧 Compliance Officer\nNotification]
```

---

### 5. RAG (Retrieval-Augmented Generation) Flow

```mermaid
sequenceDiagram
    participant User as 👤 Analyst
    participant API as FastAPI
    participant Fast as Qwen3-8B\nPort 8002
    participant Embed as Embed-1b\nPort 8001
    participant Milvus as Milvus
    participant Rerank as Rerank-1b\nPort 8003
    participant Primary as Qwen3-32B\nPort 8000

    User->>API: Submit query
    API->>Fast: Classify & rewrite query
    Fast-->>API: Optimised search query
    API->>Embed: Embed query → vector
    Embed-->>API: 2048-dim vector
    API->>Milvus: ANN search (top-20)
    Milvus-->>API: 20 candidate chunks
    API->>Rerank: Score & rerank chunks
    Rerank-->>API: Top-5 ranked chunks
    API->>Primary: Query + top-5 context
    Primary-->>API: Analysis / answer
    API-->>User: Structured response
```

---

### 6. LangGraph Agent Architecture

```mermaid
graph TD
    START([🚀 Agent Start]) --> ROUTER

    subgraph Agent["LangGraph Agent"]
        ROUTER[Router Node\nQwen3-8B · Port 8002]
        ROUTER -->|Document task| DOC_NODE[Document Node]
        ROUTER -->|Search task| SEARCH_NODE[Search Node]
        ROUTER -->|Score task| SCORE_NODE[Score Node]
        ROUTER -->|Report task| REPORT_NODE[Report Node]

        DOC_NODE --> OCR_TOOL[OCR Tool\nPort 8021]
        DOC_NODE --> PARSE_TOOL[Parse Tool\nPort 8022]
        DOC_NODE --> PII_TOOL[PII Tool\nPort 8020]

        SEARCH_NODE --> EMBED_TOOL[Embed Tool\nPort 8001]
        SEARCH_NODE --> RERANK_TOOL[Rerank Tool\nPort 8003]

        SCORE_NODE --> SCORER_TOOL[Scorer Tool\nPort 8010]

        REPORT_NODE --> LLM_TOOL[Primary LLM\nPort 8000]
    end

    OCR_TOOL --> MEMORY[(Agent Memory\nRedis)]
    PARSE_TOOL --> MEMORY
    PII_TOOL --> MEMORY
    EMBED_TOOL --> MEMORY
    RERANK_TOOL --> MEMORY
    SCORER_TOOL --> MEMORY
    LLM_TOOL --> MEMORY

    MEMORY --> END([✅ Agent End\nReturn Result])
```

---

### 7. Model Dependency Map

```mermaid
graph LR
    subgraph Standalone["Standalone — No dependencies"]
        PII[gliner-PII\nPort 8020]
        SCORER[XGBoost\nPort 8010]
        OCR[nemotron-ocr-v2\nPort 8021]
    end

    subgraph Paired["Paired — Work together"]
        OCR2[nemotron-ocr-v2\nPort 8021] -->|text| PARSE[Nemotron-Parse\nPort 8022]
        EMBED[embed-1b\nPort 8001] -->|vectors| RERANK[rerank-1b\nPort 8003]
    end

    subgraph Chain["Chained — RAG pipeline"]
        EMBED2[embed-1b] --> MILVUS[(Milvus)] --> RERANK2[rerank-1b] --> LLM[Qwen3-32B\nPort 8000]
    end

    subgraph Orchestrated["Orchestrated — Agent controlled"]
        LANGGRAPH[LangGraph] --> ALL["All 8 models\nvia tool calls"]
    end
```

---

## Port Reference

| Port | Service | Protocol | Notes |
|------|---------|----------|-------|
| 8000 | Qwen3-32B-FP8 | OpenAI-compatible REST | `/v1/chat/completions` |
| 8001 | llama-nemotron-embed-1b-v2 | OpenAI-compatible REST | `/v1/embeddings` |
| 8002 | Qwen3-8B-FP8 | OpenAI-compatible REST | `/v1/chat/completions` |
| 8003 | llama-nemotron-rerank-1b-v2 | OpenAI-compatible REST | `/v1/rerank` |
| 8010 | XGBoost Scorer | FastAPI REST | `/score` · `/health` |
| 8020 | gliner-PII | FastAPI REST | `/extract` · `/health` |
| 8021 | nemotron-ocr-v2 | FastAPI REST | `/extract` · `/health` |
| 8022 | Nemotron-Parse-v1.1 | OpenAI-compatible REST | `/v1/completions` |

---

## Thinking Mode (Qwen3)

Both Qwen3 models support optional chain-of-thought reasoning. Disabled by default for speed.

```bash
# Enable thinking mode per-request
curl http://160.30.63.152:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen3-32b-instruct",
    "extra_body": {"chat_template_kwargs": {"enable_thinking": true}},
    "messages": [{"role": "user", "content": "Analyse this transaction for AML risk..."}]
  }'
```

---

*goAML-V2 · gpu-01 · 160.30.63.152*
