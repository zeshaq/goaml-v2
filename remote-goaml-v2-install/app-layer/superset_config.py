import os

# Security
SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "")
WTF_CSRF_ENABLED = True

# Database
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "DATABASE_URL",
    "postgresql://goaml:goaml@goaml-postgres:5432/superset"
)

# Redis cache
CACHE_CONFIG = {
    "CACHE_TYPE": "RedisCache",
    "CACHE_DEFAULT_TIMEOUT": 300,
    "CACHE_KEY_PREFIX": "superset_",
    "CACHE_REDIS_URL": os.environ.get("REDIS_URL", "redis://goaml-redis:6379/3"),
}

# Feature flags
FEATURE_FLAGS = {
    "ENABLE_TEMPLATE_PROCESSING": True,
    "DASHBOARD_NATIVE_FILTERS": True,
    "DASHBOARD_CROSS_FILTERS": True,
}

# Allow embedding
SESSION_COOKIE_SAMESITE = "Lax"
TALISMAN_ENABLED = False
