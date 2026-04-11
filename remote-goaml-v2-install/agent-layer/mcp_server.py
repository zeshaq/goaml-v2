"""
goAML-V2 MCP Server
Exposes AML data tools over the Model Context Protocol.
Replace tool implementations with your actual goAML-V2 queries.
"""

from fastapi import FastAPI
import os

app = FastAPI(title="goAML MCP Server", version="1.0.0")

POSTGRES_URI = os.getenv("POSTGRES_URI", "")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://goaml-neo4j:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")


@app.get("/health")
async def health():
    return {"status": "ok", "service": "goaml-mcp-server"}


@app.get("/tools")
async def list_tools():
    """List all available MCP tools for AML agents."""
    return {
        "tools": [
            {"name": "query_transactions", "description": "Query AML transaction records from PostgreSQL"},
            {"name": "screen_entity", "description": "Screen entity against OpenSanctions via yente"},
            {"name": "graph_lookup", "description": "Look up entity relationships in Neo4j"},
            {"name": "vector_search", "description": "Semantic search over AML documents via Milvus"},
            {"name": "get_risk_score", "description": "Get ML risk score from Triton/XGBoost"},
        ]
    }
