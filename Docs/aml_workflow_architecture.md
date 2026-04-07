# AML Investigation AI Workflow

This artifact visualizes how the different NVIDIA Inference Microservices (NIMs) and machine learning models orchestrate an end-to-end Anti-Money Laundering (AML) and compliance workflow. 

## System Architecture

The AI workflow is broken down into concurrent layers that interact with your central LangGraph orchestrator:

```mermaid
graph TD
    %% Styling
    classDef primary fill:#2563eb,stroke:#1d4ed8,color:white
    classDef secondary fill:#059669,stroke:#047857,color:white
    classDef danger fill:#dc2626,stroke:#b91c1c,color:white
    classDef database fill:#4b5563,stroke:#374151,color:white

    subgraph "Document Understanding Layer"
        Raw[Scanned KYC / Bank Statements] --> OCR[nemotron-ocr-v1]
        OCR --> Parse[nemotron-parse]
        Parse --> PII{gliner-pii}
        PII -- "Redacted Structure" --> Embed[llama-nemotron-embed-1b-v2]
        Embed --> VectorDB[(Milvus Vector DB)]
    end

    subgraph "Transaction Scoring Layer"
        Tx[Live Transactions] --> Triton[XGBoost via Triton FIL]
        Triton:::primary -- "Risk Score & Features" --> Triage
    end

    subgraph "Agentic Inference Core (LangGraph)"
        Triage{llama-3.1-8b-instruct}:::secondary
        Triage -- "Real-time Assist / UI" --> Analyst[Analyst UI]
        Triage -- "Complex Investigation" --> RAG_Pipeline
        
        RAG_Pipeline[RAG Query Generator] --> VectorDB
        VectorDB -. "Semantic Search Results" .-> Rerank[llama-nemotron-rerank-1b-v2]
        
        Rerank -- "High-Precision Context" --> Brain[llama-3.3-70b-instruct]:::primary
        Brain --> SAR[SAR Narrative & Alert Explanation]
    end

    %% Connections across layers
    Triton -. "SHAP/Scores" .-> Brain
    VectorDB:::database
```

> [!TIP]
> **Latency Strategy**
> Use the 8B model (`llama-3.1-8b-instruct`) for anything requiring immediate UI feedback (like triaging tags, autocomplete, or intent routing). Reserve the 70B model (`llama-3.3-70b-instruct`) for asynchronous batch tasks or deep investigation flows that generate final reports.

## Component Responsibilities

| Layer | Component | Role in Workflow |
| :--- | :--- | :--- |
| **Documents** | `nemotron-ocr-v1` & `parse` | Extracts structured data from messy, unstructured uploads (like poor-quality ID scans or nested tables in bank statements). |
| **Documents** | `gliner-pii` | Erases or masks sensitive customer data (SSNs, Names) *before* it gets embedded into the vector database, preventing massive privacy leaks. |
| **Scoring** | `XGBoost via Triton FIL` | Provides lightning-fast, highly deterministic risk scoring on raw tabular data (e.g., transaction frequencies, amounts, IP addresses). |
| **Knowledge** | `nemotron-embed-1b-v2` | Converts redacted documents and past case histories into multilingual vectors, enabling robust search across languages (e.g., Bengali, Arabic). |
| **Knowledge** | `nemotron-rerank-1b-v2` | Acts as the "filter" for the 70B model, re-ordering Milvus search results to ensure only the most relevant snippets consume context space. |
| **Reasoning** | `llama-3.1-8b-instruct` | The "Router". Determines user intent, handles simple queries, and delegates massive analytical tasks to the 70B model. |
| **Reasoning** | `llama-3.3-70b-instruct` | The "Analyst". Synthesizes XGBoost scores, Milvus queries, and document parses to write comprehensive, auditor-ready Suspicious Activity Reports (SARs). |
