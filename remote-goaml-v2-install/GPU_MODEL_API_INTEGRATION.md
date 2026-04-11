# GPU Model API Integration

This note maps the `goaml-v2` app stack to the live model APIs hosted on `gpu-01`.

## Host

- GPU inference host: `160.30.63.152`

## API Endpoints

| Purpose | URL | Notes |
|---|---|---|
| Primary LLM | `http://160.30.63.152:8000/v1` | vLLM OpenAI-compatible; served model `Qwen3-32B` |
| Fast LLM | `http://160.30.63.152:8002/v1` | vLLM OpenAI-compatible; served model `qwen3-8b-instruct` |
| Embeddings | `http://160.30.63.152:8001/v1` | vLLM pooling; served model `llama-nemotron-embed-1b-v2` |
| Rerank | `http://160.30.63.152:8003/v1` | vLLM pooling; served model `llama-nemotron-rerank-1b-v2` |
| Parse | `http://160.30.63.152:8022/v1` | vLLM parser; served model `nemotron-parse` |
| OCR | `http://160.30.63.152:8021` | FastAPI wrapper |
| PII | `http://160.30.63.152:8020` | FastAPI wrapper |
| Scorer | `http://160.30.63.152:8010` | FastAPI XGBoost scorer |

## Updated App-Side Variables

These copied deployment files were updated to use the GPU host directly:

- [app-layer/docker-compose.app.yml](/Users/ze/Documents/goaml-v2/remote-goaml-v2-install/app-layer/docker-compose.app.yml)
- [agent-layer/docker-compose.agent.yml](/Users/ze/Documents/goaml-v2/remote-goaml-v2-install/agent-layer/docker-compose.agent.yml)

Suggested variables now present in the copied config:

```yaml
LLM_PRIMARY_URL: http://160.30.63.152:8000/v1
LLM_FAST_URL: http://160.30.63.152:8002/v1
EMBED_URL: http://160.30.63.152:8001/v1
RERANK_URL: http://160.30.63.152:8003/v1
PARSE_URL: http://160.30.63.152:8022/v1
OCR_URL: http://160.30.63.152:8021
PII_URL: http://160.30.63.152:8020
SCORER_URL: http://160.30.63.152:8010
```

## Notes

- The old internal names like `goaml-nim-llama70b`, `goaml-nim-embed`, `goaml-nim-rerank`, and `goaml-triton` do not match the currently running GPU deployment.
- The copied app config now reflects the live architecture: app/control plane on `goaml-v2`, inference plane on `gpu-01`.
- Compatibility aliases are also included in the copied compose files for older names like `LLM_BASE_URL`, `EMBED_BASE_URL`, and `TRITON_URL`.
