"""
PostgreSQL async connection pool using asyncpg
"""

import asyncpg
from core.config import settings

_pool: asyncpg.Pool | None = None


async def _ensure_support_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS orchestration_runs (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                engine VARCHAR(32) NOT NULL,
                workflow_key VARCHAR(128) NOT NULL,
                workflow_label VARCHAR(255),
                process_instance_id VARCHAR(255),
                business_key VARCHAR(255),
                case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
                subject_type VARCHAR(64),
                subject_id UUID,
                team_key VARCHAR(64),
                team_label VARCHAR(255),
                region_key VARCHAR(64),
                region_label VARCHAR(255),
                status VARCHAR(32) NOT NULL DEFAULT 'active',
                current_task_name VARCHAR(255),
                summary TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                finished_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_orchestration_runs_engine
                ON orchestration_runs(engine, workflow_key, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_orchestration_runs_case
                ON orchestration_runs(case_id, started_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_orchestration_runs_process_instance
                ON orchestration_runs(process_instance_id);

            CREATE TABLE IF NOT EXISTS notification_events (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                notification_type VARCHAR(64) NOT NULL,
                channel VARCHAR(32) NOT NULL,
                severity VARCHAR(32) NOT NULL DEFAULT 'info',
                status VARCHAR(32) NOT NULL DEFAULT 'queued',
                subject TEXT,
                target TEXT,
                team_key VARCHAR(64),
                region_key VARCHAR(64),
                case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                delivered_at TIMESTAMPTZ
            );

            CREATE INDEX IF NOT EXISTS idx_notification_events_created
                ON notification_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_notification_events_type
                ON notification_events(notification_type, status, created_at DESC);
            """
        )


async def init_postgres():
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.POSTGRES_URL,
        min_size=5,
        max_size=20,
        command_timeout=30,
    )
    await _ensure_support_tables(_pool)


async def close_postgres():
    global _pool
    if _pool:
        await _pool.close()


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("PostgreSQL pool not initialized")
    return _pool
