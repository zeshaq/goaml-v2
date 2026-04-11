"""
PostgreSQL async connection pool using asyncpg
"""

import json

import asyncpg
from core.config import settings
from core.security import default_provider_rows, default_role_rows, default_user_rows

_pool: asyncpg.Pool | None = None


async def _ensure_support_tables(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_roles (
                role_key VARCHAR(64) PRIMARY KEY,
                display_name VARCHAR(255) NOT NULL,
                description TEXT,
                permissions JSONB NOT NULL DEFAULT '[]'::jsonb,
                desk_access JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS app_users (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                username VARCHAR(255) NOT NULL UNIQUE,
                full_name VARCHAR(255) NOT NULL,
                email VARCHAR(255),
                password_hash TEXT NOT NULL,
                role_key VARCHAR(64) NOT NULL REFERENCES auth_roles(role_key) ON DELETE RESTRICT,
                team_key VARCHAR(64) NOT NULL DEFAULT 'global',
                team_label VARCHAR(255) NOT NULL DEFAULT 'Global Operations',
                regions JSONB NOT NULL DEFAULT '[]'::jsonb,
                countries JSONB NOT NULL DEFAULT '[]'::jsonb,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                must_change_password BOOLEAN NOT NULL DEFAULT FALSE,
                auth_provider VARCHAR(64) NOT NULL DEFAULT 'local',
                last_login_at TIMESTAMPTZ,
                password_updated_at TIMESTAMPTZ,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_app_users_role_key
                ON app_users(role_key, team_key, username);
            CREATE INDEX IF NOT EXISTS idx_app_users_active
                ON app_users(is_active, username);

            CREATE TABLE IF NOT EXISTS auth_provider_settings (
                provider_key VARCHAR(64) PRIMARY KEY,
                display_name VARCHAR(255) NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                mode VARCHAR(64) NOT NULL DEFAULT 'password',
                config JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS auth_audit_events (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                actor VARCHAR(255),
                event_type VARCHAR(64) NOT NULL,
                status VARCHAR(32) NOT NULL DEFAULT 'success',
                target_type VARCHAR(64),
                target_id VARCHAR(255),
                ip_address VARCHAR(128),
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_auth_audit_events_created
                ON auth_audit_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_auth_audit_events_actor
                ON auth_audit_events(actor, created_at DESC);

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

            CREATE TABLE IF NOT EXISTS notification_inbox_state (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                item_type VARCHAR(32) NOT NULL,
                item_id VARCHAR(255) NOT NULL,
                actor VARCHAR(255) NOT NULL,
                state VARCHAR(32) NOT NULL DEFAULT 'new',
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_notification_inbox_state_unique
                ON notification_inbox_state(item_type, item_id, actor);
            CREATE INDEX IF NOT EXISTS idx_notification_inbox_state_actor
                ON notification_inbox_state(actor, state, updated_at DESC);

            CREATE TABLE IF NOT EXISTS saved_views (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                scope VARCHAR(64) NOT NULL,
                owner VARCHAR(255),
                name VARCHAR(255) NOT NULL,
                is_shared BOOLEAN NOT NULL DEFAULT FALSE,
                is_default BOOLEAN NOT NULL DEFAULT FALSE,
                filters JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_saved_views_scope_owner
                ON saved_views(scope, owner, updated_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_saved_views_unique_name
                ON saved_views(scope, COALESCE(owner, ''), name);

            CREATE TABLE IF NOT EXISTS case_evidence (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                evidence_type VARCHAR(64) NOT NULL,
                source_evidence_id TEXT,
                title TEXT NOT NULL,
                summary TEXT,
                source VARCHAR(64),
                importance SMALLINT NOT NULL DEFAULT 50,
                include_in_sar BOOLEAN NOT NULL DEFAULT FALSE,
                pinned_by VARCHAR(255),
                pinned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            );

            CREATE INDEX IF NOT EXISTS idx_case_evidence_case
                ON case_evidence(case_id, include_in_sar DESC, importance DESC, pinned_at DESC);
            CREATE INDEX IF NOT EXISTS idx_case_evidence_type
                ON case_evidence(evidence_type, source_evidence_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_case_evidence_unique_source
                ON case_evidence(case_id, evidence_type, source_evidence_id);

            CREATE TABLE IF NOT EXISTS decision_feedback (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                subject_type VARCHAR(32) NOT NULL,
                subject_id UUID NOT NULL,
                case_id UUID REFERENCES cases(id) ON DELETE SET NULL,
                alert_id UUID REFERENCES alerts(id) ON DELETE SET NULL,
                actor VARCHAR(255),
                actor_role VARCHAR(64),
                feedback_key VARCHAR(64) NOT NULL,
                label VARCHAR(255) NOT NULL,
                sentiment VARCHAR(32) NOT NULL DEFAULT 'neutral',
                rating SMALLINT NOT NULL DEFAULT 0,
                note TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_decision_feedback_subject
                ON decision_feedback(subject_type, subject_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_decision_feedback_case
                ON decision_feedback(case_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_decision_feedback_alert
                ON decision_feedback(alert_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_decision_feedback_key
                ON decision_feedback(feedback_key, created_at DESC);

            CREATE TABLE IF NOT EXISTS case_playbook_configs (
                typology VARCHAR(64) PRIMARY KEY,
                display_name VARCHAR(255) NOT NULL,
                checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
                evidence_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
                sla_targets JSONB NOT NULL DEFAULT '{}'::jsonb,
                task_templates JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_by VARCHAR(255),
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_case_playbook_configs_updated
                ON case_playbook_configs(updated_at DESC);

            CREATE TABLE IF NOT EXISTS app_runtime_settings (
                setting_key VARCHAR(128) PRIMARY KEY,
                config JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_app_runtime_settings_updated
                ON app_runtime_settings(updated_at DESC);

            CREATE TABLE IF NOT EXISTS sar_queue_snapshots (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                snapshot_type VARCHAR(32) NOT NULL DEFAULT 'sar_queue',
                captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                captured_by VARCHAR(255),
                source VARCHAR(64) NOT NULL DEFAULT 'manual',
                snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            );

            CREATE INDEX IF NOT EXISTS idx_sar_queue_snapshots_type_time
                ON sar_queue_snapshots(snapshot_type, captured_at DESC);

            CREATE TABLE IF NOT EXISTS reporting_snapshots (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                snapshot_scope VARCHAR(32) NOT NULL DEFAULT 'manager',
                snapshot_granularity VARCHAR(16) NOT NULL DEFAULT 'daily',
                range_days INTEGER NOT NULL DEFAULT 180,
                period_start TIMESTAMPTZ,
                period_end TIMESTAMPTZ,
                period_label VARCHAR(64),
                captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                captured_by VARCHAR(255),
                source VARCHAR(64) NOT NULL DEFAULT 'manual',
                summary_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            );

            CREATE INDEX IF NOT EXISTS idx_reporting_snapshots_scope_time
                ON reporting_snapshots(snapshot_scope, captured_at DESC);

            CREATE TABLE IF NOT EXISTS decision_quality_snapshots (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                snapshot_granularity VARCHAR(16) NOT NULL DEFAULT 'daily',
                range_days INTEGER NOT NULL DEFAULT 180,
                period_start TIMESTAMPTZ,
                period_end TIMESTAMPTZ,
                period_label VARCHAR(64),
                captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                captured_by VARCHAR(255),
                source VARCHAR(64) NOT NULL DEFAULT 'manual',
                summary_metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            );

            CREATE INDEX IF NOT EXISTS idx_decision_quality_snapshots_period
                ON decision_quality_snapshots(snapshot_granularity, period_end DESC, captured_at DESC);

            CREATE TABLE IF NOT EXISTS report_distribution_rules (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                rule_key VARCHAR(128) NOT NULL UNIQUE,
                display_name VARCHAR(255) NOT NULL,
                target_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
                template_key VARCHAR(32) NOT NULL DEFAULT 'manager',
                export_format VARCHAR(16) NOT NULL DEFAULT 'pdf',
                cadence VARCHAR(32) NOT NULL DEFAULT 'daily',
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                channels JSONB NOT NULL DEFAULT '[]'::jsonb,
                recipients JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_by VARCHAR(255),
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_report_distribution_rules_enabled
                ON report_distribution_rules(enabled, cadence, template_key);

            CREATE TABLE IF NOT EXISTS model_evaluations (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                registered_model_name VARCHAR(255) NOT NULL,
                version VARCHAR(64) NOT NULL,
                evaluation_type VARCHAR(64) NOT NULL DEFAULT 'pre_promotion',
                evaluator VARCHAR(255),
                dataset_label VARCHAR(255),
                summary TEXT,
                notes TEXT,
                metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
                gate_results JSONB NOT NULL DEFAULT '{}'::jsonb,
                overall_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_model_evaluations_model_version
                ON model_evaluations(registered_model_name, version, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_model_evaluations_status
                ON model_evaluations(overall_status, created_at DESC);

            CREATE TABLE IF NOT EXISTS model_approval_requests (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                registered_model_name VARCHAR(255) NOT NULL,
                version VARCHAR(64) NOT NULL,
                target_stage VARCHAR(64) NOT NULL DEFAULT 'Production',
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                submitted_by VARCHAR(255),
                submitted_notes TEXT,
                reviewer VARCHAR(255),
                review_notes TEXT,
                evaluation_id UUID REFERENCES model_evaluations(id) ON DELETE SET NULL,
                submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                reviewed_at TIMESTAMPTZ
            );

            CREATE INDEX IF NOT EXISTS idx_model_approval_requests_model_version
                ON model_approval_requests(registered_model_name, version, submitted_at DESC);
            CREATE INDEX IF NOT EXISTS idx_model_approval_requests_status
                ON model_approval_requests(status, submitted_at DESC);

            CREATE TABLE IF NOT EXISTS model_deployment_events (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                registered_model_name VARCHAR(255) NOT NULL,
                version VARCHAR(64) NOT NULL,
                stage VARCHAR(64),
                action VARCHAR(32) NOT NULL DEFAULT 'deploy',
                actor VARCHAR(255),
                notes TEXT,
                previous_version VARCHAR(64),
                previous_stage VARCHAR(64),
                run_id VARCHAR(255),
                source_uri TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_model_deployment_events_model
                ON model_deployment_events(registered_model_name, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_model_deployment_events_version
                ON model_deployment_events(version, created_at DESC);

            CREATE TABLE IF NOT EXISTS model_monitoring_snapshots (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                registered_model_name VARCHAR(255) NOT NULL,
                snapshot_type VARCHAR(64) NOT NULL,
                primary_version VARCHAR(64),
                secondary_version VARCHAR(64),
                actor VARCHAR(255),
                status VARCHAR(32) NOT NULL DEFAULT 'completed',
                sample_size INTEGER NOT NULL DEFAULT 0,
                window_start TIMESTAMPTZ,
                window_end TIMESTAMPTZ,
                summary JSONB NOT NULL DEFAULT '{}'::jsonb,
                metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_model_monitoring_snapshots_model
                ON model_monitoring_snapshots(registered_model_name, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_model_monitoring_snapshots_type
                ON model_monitoring_snapshots(snapshot_type, created_at DESC);
            """
        )
        await conn.execute("ALTER TABLE reporting_snapshots ADD COLUMN IF NOT EXISTS snapshot_granularity VARCHAR(16) NOT NULL DEFAULT 'daily'")
        await conn.execute("ALTER TABLE reporting_snapshots ADD COLUMN IF NOT EXISTS period_start TIMESTAMPTZ")
        await conn.execute("ALTER TABLE reporting_snapshots ADD COLUMN IF NOT EXISTS period_end TIMESTAMPTZ")
        await conn.execute("ALTER TABLE reporting_snapshots ADD COLUMN IF NOT EXISTS period_label VARCHAR(64)")
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_reporting_snapshots_scope_granularity_period
                ON reporting_snapshots(snapshot_scope, snapshot_granularity, period_end DESC)
            """
        )
        await conn.execute("ALTER TABLE decision_quality_snapshots ADD COLUMN IF NOT EXISTS snapshot_granularity VARCHAR(16) NOT NULL DEFAULT 'daily'")
        await conn.execute("ALTER TABLE decision_quality_snapshots ADD COLUMN IF NOT EXISTS period_start TIMESTAMPTZ")
        await conn.execute("ALTER TABLE decision_quality_snapshots ADD COLUMN IF NOT EXISTS period_end TIMESTAMPTZ")
        await conn.execute("ALTER TABLE decision_quality_snapshots ADD COLUMN IF NOT EXISTS period_label VARCHAR(64)")
        await conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_decision_quality_snapshots_granularity_period
                ON decision_quality_snapshots(snapshot_granularity, period_end DESC)
            """
        )
        for role in default_role_rows():
            await conn.execute(
                """
                INSERT INTO auth_roles (
                    role_key, display_name, description, permissions, desk_access, metadata
                )
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb)
                ON CONFLICT (role_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    permissions = EXCLUDED.permissions,
                    desk_access = EXCLUDED.desk_access,
                    metadata = EXCLUDED.metadata,
                    updated_at = NOW()
                """,
                role["role_key"],
                role["display_name"],
                role.get("description"),
                json.dumps(role.get("permissions", [])),
                json.dumps(role.get("desk_access", [])),
                json.dumps(role.get("metadata", {})),
            )

        for provider in default_provider_rows():
            await conn.execute(
                """
                INSERT INTO auth_provider_settings (
                    provider_key, display_name, enabled, mode, config
                )
                VALUES ($1, $2, $3, $4, $5::jsonb)
                ON CONFLICT (provider_key) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    mode = EXCLUDED.mode,
                    config = COALESCE(auth_provider_settings.config, '{}'::jsonb) || EXCLUDED.config,
                    updated_at = NOW()
                """,
                provider["provider_key"],
                provider["display_name"],
                provider["enabled"],
                provider["mode"],
                json.dumps(provider.get("config", {})),
            )

        for user in default_user_rows():
            await conn.execute(
                """
                INSERT INTO app_users (
                    username, full_name, email, password_hash, role_key,
                    team_key, team_label, regions, countries, is_active,
                    must_change_password, auth_provider, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12, $13::jsonb)
                ON CONFLICT (username) DO NOTHING
                """,
                user["username"],
                user["full_name"],
                user.get("email"),
                user["password_hash"],
                user["role_key"],
                user.get("team_key", "global"),
                user.get("team_label", "Global Operations"),
                json.dumps(user.get("regions", [])),
                json.dumps(user.get("countries", [])),
                user.get("is_active", True),
                user.get("must_change_password", False),
                user.get("auth_provider", "local"),
                json.dumps(user.get("metadata", {})),
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
