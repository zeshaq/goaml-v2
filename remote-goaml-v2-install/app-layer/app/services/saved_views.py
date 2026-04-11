"""
Saved analyst views for queue and desk productivity.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from core.database import get_pool


def _normalize_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(row)
    normalized["filters"] = _normalize_json(normalized.get("filters"))
    normalized["metadata"] = _normalize_json(normalized.get("metadata"))
    return normalized


async def list_saved_views(scope: str, owner: str | None = None) -> list[dict[str, Any]]:
    pool = get_pool()
    scope_value = str(scope or "").strip().lower()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM saved_views
            WHERE scope = $1
              AND (owner = $2 OR owner IS NULL OR is_shared = TRUE)
            ORDER BY is_default DESC, updated_at DESC, name ASC
            """,
            scope_value,
            owner,
        )
    return [_normalize_row(dict(row)) for row in rows]


async def create_saved_view(payload: dict[str, Any]) -> dict[str, Any]:
    pool = get_pool()
    scope = str(payload.get("scope") or "").strip().lower()
    owner = payload.get("owner")
    is_default = bool(payload.get("is_default"))
    async with pool.acquire() as conn:
        async with conn.transaction():
            if is_default:
                await conn.execute(
                    """
                    UPDATE saved_views
                    SET is_default = FALSE, updated_at = NOW()
                    WHERE scope = $1
                      AND ((owner = $2) OR (owner IS NULL AND $2 IS NULL))
                    """,
                    scope,
                    owner,
                )
            existing = await conn.fetchrow(
                """
                SELECT id
                FROM saved_views
                WHERE scope = $1
                  AND name = $2
                  AND ((owner = $3) OR (owner IS NULL AND $3 IS NULL))
                LIMIT 1
                """,
                scope,
                payload.get("name"),
                owner,
            )
            if existing:
                row = await conn.fetchrow(
                    """
                    UPDATE saved_views
                    SET
                        is_shared = $2,
                        is_default = $3,
                        filters = $4::jsonb,
                        metadata = $5::jsonb,
                        updated_at = NOW()
                    WHERE id = $1
                    RETURNING *
                    """,
                    existing["id"],
                    bool(payload.get("is_shared")),
                    is_default,
                    json.dumps(payload.get("filters") or {}),
                    json.dumps(payload.get("metadata") or {}),
                )
            else:
                row = await conn.fetchrow(
                """
                INSERT INTO saved_views (
                    scope,
                    owner,
                    name,
                    is_shared,
                    is_default,
                    filters,
                    metadata
                ) VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7::jsonb)
                RETURNING *
                """,
                    scope,
                    owner,
                    payload.get("name"),
                    bool(payload.get("is_shared")),
                    is_default,
                    json.dumps(payload.get("filters") or {}),
                    json.dumps(payload.get("metadata") or {}),
                )
    return _normalize_row(dict(row))


async def delete_saved_view(view_id: UUID) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM saved_views WHERE id = $1", view_id)
    return result.endswith("1")
