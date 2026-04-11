"""
goAML-V2 FastAPI Application
"""

from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from core.database import init_postgres, close_postgres
from core.clickhouse import init_clickhouse
from services.graph_sync import close_graph_driver, ensure_graph_schema
from api.v1.transactions import router as transactions_router
from api.v1.auth import router as auth_router
from api.v1.alerts import router as alerts_router
from api.v1.cases import router as cases_router
from api.v1.screening import router as screening_router
from api.v1.graph import router as graph_router
from api.v1.documents import router as documents_router
from api.v1.entities import router as entities_router
from api.v1.workflows import router as workflows_router
from api.v1.model_ops import router as model_ops_router
from api.v1.views import router as views_router
from api.v1.analyst import router as analyst_router
from api.v1.manager import router as manager_router
from services.auth import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_postgres()
    init_clickhouse()
    await ensure_graph_schema()
    yield
    await close_graph_driver()
    await close_postgres()


app = FastAPI(
    title="goAML-V2 API",
    description="Anti-Money Laundering Intelligence Platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(transactions_router, prefix="/api/v1", tags=["transactions"])
app.include_router(auth_router, prefix="/api/v1", tags=["auth"])
app.include_router(alerts_router, prefix="/api/v1", tags=["alerts"])
app.include_router(cases_router, prefix="/api/v1", tags=["cases"])
app.include_router(screening_router, prefix="/api/v1", tags=["screening"])
app.include_router(graph_router, prefix="/api/v1", tags=["graph"])
app.include_router(documents_router, prefix="/api/v1", tags=["documents"])
app.include_router(entities_router, prefix="/api/v1", tags=["entities"])
app.include_router(workflows_router, prefix="/api/v1", tags=["workflow"])
app.include_router(model_ops_router, prefix="/api/v1", tags=["model-ops"])
app.include_router(views_router, prefix="/api/v1", tags=["saved-views"])
app.include_router(analyst_router, prefix="/api/v1", tags=["analyst"])
app.include_router(manager_router, prefix="/api/v1", tags=["manager"])


@app.get("/health")
async def health():
    return {"status": "ok", "service": "goaml-fastapi", "version": "2.0.0"}


@app.get("/api/v1/status")
async def status(current_user=Depends(get_current_user)):
    return {
        "postgres": settings.POSTGRES_URL[:30] + "...",
        "clickhouse": settings.CLICKHOUSE_URL,
        "scorer": settings.SCORER_URL,
        "mlflow": settings.MLFLOW_TRACKING_URI,
        "llm_primary": settings.LLM_PRIMARY_URL,
        "llm_fast": settings.LLM_FAST_URL,
        "embed": settings.EMBED_URL,
        "rerank": settings.RERANK_URL,
        "parse": settings.PARSE_URL,
        "ocr": settings.OCR_URL,
        "pii": settings.PII_URL,
        "neo4j": settings.NEO4J_URI,
        "milvus": f"{settings.MILVUS_HOST}:{settings.MILVUS_PORT}",
        "minio": settings.MINIO_ENDPOINT,
    }
