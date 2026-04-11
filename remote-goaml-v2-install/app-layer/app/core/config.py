"""
goAML-V2 Configuration
"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # PostgreSQL
    POSTGRES_URL: str = "postgresql://goaml:Asdf%401234@goaml-postgres:5432/goaml"

    # ClickHouse
    CLICKHOUSE_URL: str = "http://goaml-clickhouse:8123"
    CLICKHOUSE_USER: str = "goaml"
    CLICKHOUSE_PASSWORD: str = "Asdf@1234"
    CLICKHOUSE_DB: str = "goaml"

    # Redis
    REDIS_URL: str = "redis://:Asdf@1234@goaml-redis:6379/0"

    # Graph / vector
    NEO4J_URI: str = "bolt://goaml-neo4j:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "Asdf@1234"
    MILVUS_HOST: str = "goaml-milvus"
    MILVUS_PORT: int = 19530
    MINIO_ENDPOINT: str = "http://goaml-minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "Asdf@1234"
    MINIO_BUCKET: str = "goaml-documents"

    # GPU server — ML models
    SCORER_URL: str = "http://160.30.63.152:8010"
    LLM_PRIMARY_URL: str = "http://160.30.63.152:8000/v1"
    LLM_PRIMARY_MODEL: str = "Qwen3-32B"
    LLM_FAST_URL: str = "http://160.30.63.152:8002/v1"
    EMBED_URL: str = "http://160.30.63.152:8001/v1"
    RERANK_URL: str = "http://160.30.63.152:8003/v1"
    PII_URL: str = "http://160.30.63.152:8020"
    OCR_URL: str = "http://160.30.63.152:8021"
    PARSE_URL: str = "http://160.30.63.152:8022/v1"
    TIKA_URL: str = "http://goaml-tika:9998"
    YENTE_URL: str = "http://goaml-yente:8000"
    LLM_TIMEOUT_SECONDS: float = 45.0
    OFAC_SDN_XML_URL: str = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"

    # Thresholds for alert creation
    ALERT_THRESHOLD_HIGH: float = 0.75
    ALERT_THRESHOLD_MEDIUM: float = 0.45

    class Config:
        env_file = ".env"


settings = Settings()
