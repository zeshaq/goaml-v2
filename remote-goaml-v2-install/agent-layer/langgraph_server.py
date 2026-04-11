"""
goAML-V2 LangGraph Server
Stub server — replace graph definitions with your AML agent workflows.
"""

from fastapi import FastAPI
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.redis import RedisSaver
import os

app = FastAPI(title="goAML LangGraph Server", version="1.0.0")

POSTGRES_URL = os.getenv("POSTGRES_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "goaml-langgraph"}


@app.get("/graphs")
async def list_graphs():
    """List all registered AML agent graphs."""
    return {
        "graphs": [
            "aml_screening_agent",
            "transaction_monitor_agent",
            "entity_resolution_agent",
            "sar_report_agent",
        ]
    }
