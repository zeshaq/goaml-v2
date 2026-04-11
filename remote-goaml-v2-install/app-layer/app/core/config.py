"""
goAML-V2 Configuration
"""

from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Auth / RBAC
    AUTH_MODE: str = "local"
    AUTH_DEFAULT_DEMO_PASSWORD: str = "Goaml!2026"
    AUTH_ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    AUTH_JWT_SECRET: str = "goaml-v2-local-dev-secret"
    AUTH_JWT_ALGORITHM: str = "HS256"
    AUTH_JWT_ISSUER: str = "goaml-v2"
    AUTH_JWT_AUDIENCE: str = "goaml-v2-ui"
    AUTH_WSO2_ISSUER: str | None = None
    AUTH_WSO2_DISCOVERY_URL: str | None = None
    AUTH_WSO2_AUTHORIZE_URL: str | None = None
    AUTH_WSO2_TOKEN_URL: str | None = None
    AUTH_WSO2_USERINFO_URL: str | None = None
    AUTH_WSO2_JWKS_URL: str | None = None
    AUTH_WSO2_CLIENT_ID: str | None = None
    AUTH_WSO2_CLIENT_SECRET: str | None = None
    AUTH_WSO2_SCOPES: str = "openid profile email groups"
    AUTH_WSO2_REDIRECT_URI: str = "http://160.30.63.131/auth/callback"

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
    MLFLOW_TRACKING_URI: str = "http://goaml-mlflow:5000"
    MLFLOW_PUBLIC_URL: str = "http://160.30.63.131:5000"
    MLFLOW_EXPERIMENT_NAME: str = "goaml-scorer"
    MLFLOW_ARTIFACT_BUCKET: str = "mlflow-artifacts"
    SCORER_REGISTERED_MODEL_NAME: str = "goaml-xgboost-scorer"
    SCORER_DEPLOYED_MODEL_NAME: str = "aml-xgboost-risk-scorer"
    SCORER_METADATA_TIMEOUT_SECONDS: float = 5.0
    SCORER_ADMIN_TIMEOUT_SECONDS: float = 90.0
    SCORER_EVAL_MIN_AUC: float = 0.78
    SCORER_EVAL_MIN_PRECISION_AT_10: float = 0.72
    SCORER_EVAL_MIN_RECALL_AT_10: float = 0.60
    SCORER_EVAL_MAX_FALSE_POSITIVE_RATE: float = 0.18
    SCORER_MONITORING_DEFAULT_SAMPLE_SIZE: int = 200
    SCORER_MONITORING_MAX_SAMPLE_SIZE: int = 500
    SCORER_MONITORING_DEFAULT_LOOKBACK_HOURS: int = 168
    SCORER_DRIFT_PSI_WARNING: float = 0.20
    SCORER_DRIFT_PSI_CRITICAL: float = 0.35
    SCORER_DRIFT_RATE_WARNING: float = 0.10
    SCORER_DRIFT_RATE_CRITICAL: float = 0.18
    SCORER_CHALLENGER_DISAGREEMENT_WARNING: float = 0.05
    SCORER_CHALLENGER_DISAGREEMENT_CRITICAL: float = 0.15
    SCORER_CHALLENGER_MEAN_ABS_DELTA_WARNING: float = 0.04
    SCORER_CHALLENGER_MEAN_ABS_DELTA_CRITICAL: float = 0.10
    SCORER_MONITORING_WORKFLOW_ACTOR: str = "model-monitoring-automation"
    TIKA_URL: str = "http://goaml-tika:9998"
    YENTE_URL: str = "http://goaml-yente:8000"
    N8N_BASE_URL: str = "http://goaml-n8n:5678"
    N8N_PUBLIC_URL: str = "http://160.30.63.131:5678"
    CAMUNDA_BASE_URL: str = "http://goaml-camunda:8080/engine-rest"
    CAMUNDA_PUBLIC_URL: str = "http://160.30.63.131:8085/camunda/app/"
    LLM_TIMEOUT_SECONDS: float = 45.0
    OFAC_SDN_XML_URL: str = "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.XML"
    SAR_DRAFT_SLA_HOURS: float = 48.0
    SAR_REVIEW_SLA_HOURS: float = 24.0
    SAR_APPROVAL_SLA_HOURS: float = 12.0
    SAR_AUTOBALANCE_ANALYST_POOL: str = "analyst1,analyst2,analyst3,analyst4"
    SAR_AUTOBALANCE_BATCH_LIMIT: int = 8
    SAR_AUTOBALANCE_MAX_ITEMS_PER_OWNER: int = 4
    SAR_AUTOBALANCE_MIN_WORKLOAD_GAP: int = 1
    SAR_AUTOBALANCE_INCLUDE_DUE_SOON: bool = True
    WATCHLIST_RESCREEN_INTERVAL_DAYS: int = 14
    WATCHLIST_RESCREEN_DUE_SOON_DAYS: int = 3
    WATCHLIST_RESCREEN_BATCH_LIMIT: int = 25
    WATCHLIST_AUTO_ESCALATE_NEW_MATCHES: bool = True
    AML_ANALYST_DIRECTORY_JSON: str = (
        '[{"name":"analyst1","team_key":"south_asia","team_label":"South Asia AML Pod","regions":["south_asia"],'
        '"countries":["BD","IN","PK","LK","NP"],"workflows":["alert_investigation","watchlist","sar_review","general"]},'
        '{"name":"analyst2","team_key":"mena","team_label":"MENA Sanctions Pod","regions":["mena"],'
        '"countries":["AE","SA","IR","IQ","EG","JO","SY","LB","QA","KW","OM","YE","TR"],'
        '"workflows":["alert_investigation","watchlist","sar_review","general"]},'
        '{"name":"analyst3","team_key":"europe","team_label":"Europe and UK Review Pod","regions":["europe"],'
        '"countries":["GB","DE","FR","IT","ES","NL","BE","CH","UA","RU"],'
        '"workflows":["alert_investigation","sar_review","general"]},'
        '{"name":"analyst4","team_key":"americas","team_label":"Americas AML Pod","regions":["americas"],'
        '"countries":["US","CA","MX","CU","BR","AR","CL","CO","PE","PA"],'
        '"workflows":["alert_investigation","watchlist","sar_review","general"]}]'
    )
    OPS_ALERT_DEFAULT_REGION: str = "global"
    OPS_ALERT_DEFAULT_TEAM: str = "global_ops"
    SLACK_WEBHOOK_URL: str | None = None
    TEAM_SLACK_WEBHOOKS_JSON: str = "{}"
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USERNAME: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_FROM: str | None = None
    SLA_NOTIFICATION_EMAIL_TO: str = ""
    TEAM_EMAIL_RECIPIENTS_JSON: str = "{}"
    SLA_NOTIFICATION_INCLUDE_DUE_SOON: bool = True
    SLA_NOTIFICATION_MAX_CASES: int = 12
    SLA_NOTIFICATION_WORKFLOW_ACTOR: str = "sla-notification-automation"
    PLAYBOOK_STUCK_CHECKLIST_HOURS: float = 18.0
    PLAYBOOK_EVIDENCE_GAP_WARNING_HOURS: float = 8.0
    PLAYBOOK_AUTOMATION_COOLDOWN_HOURS: float = 12.0
    PLAYBOOK_AUTOMATION_MAX_CASES: int = 50
    PLAYBOOK_AUTOMATION_WORKFLOW_ACTOR: str = "playbook-automation"
    SLA_SNAPSHOT_MIN_INTERVAL_MINUTES: int = 60
    SLA_TREND_DEFAULT_HOURS: int = 168

    # Thresholds for alert creation
    ALERT_THRESHOLD_HIGH: float = 0.75
    ALERT_THRESHOLD_MEDIUM: float = 0.45

    @model_validator(mode="after")
    def apply_runtime_fallbacks(self):
        if not str(self.POSTGRES_URL or "").strip() or "://goaml:@goaml-postgres:" in str(self.POSTGRES_URL):
            self.POSTGRES_URL = "postgresql://goaml:Asdf%401234@goaml-postgres:5432/goaml"
        if not str(self.REDIS_URL or "").strip() or "redis://:@" in str(self.REDIS_URL):
            self.REDIS_URL = "redis://:Asdf@1234@goaml-redis:6379/0"
        if not str(self.CLICKHOUSE_PASSWORD or "").strip():
            self.CLICKHOUSE_PASSWORD = "Asdf@1234"
        if not str(self.NEO4J_PASSWORD or "").strip():
            self.NEO4J_PASSWORD = "Asdf@1234"
        if not str(self.MINIO_SECRET_KEY or "").strip():
            self.MINIO_SECRET_KEY = "Asdf@1234"
        return self

    class Config:
        env_file = ".env"


settings = Settings()
