"""
ClickHouse client using clickhouse-connect
"""

import clickhouse_connect
from clickhouse_connect.driver.client import Client
from core.config import settings

_client: Client | None = None


def init_clickhouse():
    global _client
    _client = clickhouse_connect.get_client(
        host=settings.CLICKHOUSE_URL.replace("http://", "").split(":")[0],
        port=int(settings.CLICKHOUSE_URL.split(":")[-1]),
        username=settings.CLICKHOUSE_USER,
        password=settings.CLICKHOUSE_PASSWORD,
        database=settings.CLICKHOUSE_DB,
    )


def get_ch_client() -> Client:
    if _client is None:
        raise RuntimeError("ClickHouse client not initialized")
    return _client
