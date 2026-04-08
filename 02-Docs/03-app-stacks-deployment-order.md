# App Stacks Deployment Order

| Order | Layer | Why |
|:---|:---|:---|
| 1 | Storage | Everything depends on it — FastAPI, MLflow, n8n, Camunda all need a DB on day one |
| 2 | Graph + Vector | Neo4j and Milvus need to be ready before agents start writing embeddings/relationships |
| 3 | Docs | OpenSanctions + OCR pipeline feeds data into the graph and vector stores |
| 4 | Agent | LangGraph and MLflow need storage + vector layers healthy first |
| 5 | Workflow | n8n and Camunda orchestrate agents — agents must exist first |
| 6 | App | FastAPI, Superset, React UI sit on top of everything |
