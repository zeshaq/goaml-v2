"""
Historical SAR SLA snapshot capture and trend analytics.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from typing import Any

from core.config import settings
from core.database import get_pool


QUEUE_KEYS = ("draft", "review", "approval", "filed")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _normalize_json_dict(value: Any) -> dict[str, Any]:
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


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _normalize_snapshot_payload(queue_data: dict[str, Any]) -> dict[str, Any]:
    counts = dict(queue_data.get("counts") or {})
    analytics = dict(queue_data.get("analytics") or {})
    queue_metrics: dict[str, dict[str, Any]] = {}
    weighted_age_total = 0.0
    weighted_age_count = 0
    oldest_active: float | None = None

    for item in analytics.get("queue_sla") or []:
        queue_key = str(item.get("queue") or "").lower()
        if queue_key not in QUEUE_KEYS:
            continue
        metric = {
            "queue": queue_key,
            "label": item.get("label") or queue_key.title(),
            "item_count": _safe_int(item.get("item_count")),
            "breached_count": _safe_int(item.get("breached_count")),
            "due_soon_count": _safe_int(item.get("due_soon_count")),
            "avg_age_hours": _safe_float(item.get("avg_age_hours")),
            "oldest_age_hours": _safe_float(item.get("oldest_age_hours")),
            "sla_hours": _safe_float(item.get("sla_hours")),
        }
        queue_metrics[queue_key] = metric
        if queue_key in {"draft", "review", "approval"}:
            if metric["avg_age_hours"] is not None and metric["item_count"] > 0:
                weighted_age_total += float(metric["avg_age_hours"]) * metric["item_count"]
                weighted_age_count += metric["item_count"]
            if metric["oldest_age_hours"] is not None:
                oldest_active = max(oldest_active or 0.0, float(metric["oldest_age_hours"]))

    total = _safe_int(counts.get("total"))
    if total <= 0:
        total = sum(_safe_int(counts.get(key)) for key in QUEUE_KEYS)

    return {
        "counts": {
            "draft": _safe_int(counts.get("draft")),
            "review": _safe_int(counts.get("review")),
            "approval": _safe_int(counts.get("approval")),
            "filed": _safe_int(counts.get("filed")),
            "total": total,
        },
        "overall_breached_count": _safe_int(analytics.get("overall_breached_count")),
        "overall_due_soon_count": _safe_int(analytics.get("overall_due_soon_count")),
        "active_owner_count": _safe_int(analytics.get("active_owner_count")),
        "avg_active_age_hours": round(weighted_age_total / weighted_age_count, 2) if weighted_age_count else None,
        "oldest_active_age_hours": round(oldest_active, 2) if oldest_active is not None else None,
        "queue_metrics": queue_metrics,
        "owner_workloads": analytics.get("owner_workloads") or [],
        "summary": analytics.get("summary") or [],
    }


def _scaled_metric(value: Any, factor: float, *, minimum: int = 0, maximum: int | None = None) -> int:
    base = _safe_int(value)
    scaled = max(minimum, round(base * factor))
    if maximum is not None:
        return min(scaled, maximum)
    return scaled


def _build_bootstrap_payload(base_payload: dict[str, Any], *, progress: float, index: int, total_points: int) -> dict[str, Any]:
    wave = (((index % 5) - 2) * 0.035)
    activity_factor = max(0.65, min(1.05, 0.76 + (0.24 * progress) + wave))
    filed_factor = max(0.55, min(1.0, 0.62 + (0.38 * progress)))
    breach_factor = max(0.45, min(1.0, 0.55 + (0.45 * progress) + (((index % 3) - 1) * 0.04)))
    due_factor = max(0.5, min(1.05, 0.65 + (0.35 * progress) - (((index % 4) - 1.5) * 0.03)))

    queue_metrics: dict[str, dict[str, Any]] = {}
    counts = {"draft": 0, "review": 0, "approval": 0, "filed": 0, "total": 0}
    total_breached = 0
    total_due = 0
    weighted_age_total = 0.0
    weighted_age_count = 0
    oldest_active: float | None = None

    for queue_key in QUEUE_KEYS:
        base_metric = dict((base_payload.get("queue_metrics") or {}).get(queue_key) or {})
        if queue_key == "filed":
            item_factor = filed_factor
        else:
            item_factor = activity_factor
        item_count = _scaled_metric(base_metric.get("item_count") or (base_payload.get("counts") or {}).get(queue_key), item_factor)
        breached_count = _scaled_metric(base_metric.get("breached_count"), breach_factor, maximum=item_count)
        due_soon_count = _scaled_metric(base_metric.get("due_soon_count"), due_factor, maximum=max(item_count - breached_count, 0))
        base_avg_age = _safe_float(base_metric.get("avg_age_hours"))
        avg_age = round(base_avg_age * max(0.82, min(1.18, 0.9 + (progress * 0.2) + (((index + 1) % 4) * 0.03))), 2) if base_avg_age is not None else None
        base_oldest = _safe_float(base_metric.get("oldest_age_hours"))
        oldest_age = round(base_oldest * max(0.85, min(1.22, 0.93 + (progress * 0.18) + (((index + 2) % 3) * 0.04))), 2) if base_oldest is not None else None
        metric = {
            "queue": queue_key,
            "label": base_metric.get("label") or queue_key.title(),
            "item_count": item_count,
            "breached_count": breached_count,
            "due_soon_count": due_soon_count,
            "avg_age_hours": avg_age,
            "oldest_age_hours": oldest_age,
            "sla_hours": _safe_float(base_metric.get("sla_hours")),
        }
        queue_metrics[queue_key] = metric
        counts[queue_key] = item_count
        if queue_key != "filed":
            total_breached += breached_count
            total_due += due_soon_count
            if avg_age is not None and item_count > 0:
                weighted_age_total += avg_age * item_count
                weighted_age_count += item_count
            if oldest_age is not None:
                oldest_active = max(oldest_active or 0.0, oldest_age)

    counts["total"] = counts["draft"] + counts["review"] + counts["approval"] + counts["filed"]
    owner_base = _safe_int(base_payload.get("active_owner_count"))
    if owner_base <= 0:
        owner_base = 1
    owner_count = min(owner_base, max(1, round(owner_base * max(0.75, min(1.0, 0.84 + (progress * 0.16))))))

    return {
        "counts": counts,
        "overall_breached_count": total_breached,
        "overall_due_soon_count": total_due,
        "active_owner_count": owner_count,
        "avg_active_age_hours": round(weighted_age_total / weighted_age_count, 2) if weighted_age_count else None,
        "oldest_active_age_hours": round(oldest_active, 2) if oldest_active is not None else None,
        "queue_metrics": queue_metrics,
        "owner_workloads": [],
        "summary": [
            "Historical SLA baseline bootstrapped from the current seeded queue state.",
            "Live snapshots will replace this synthetic baseline as scheduled captures accumulate.",
        ],
    }


def _normalize_snapshot_row(row: Any) -> dict[str, Any]:
    snapshot = _normalize_json_dict(row.get("snapshot"))
    metadata = _normalize_json_dict(row.get("metadata"))
    queue_metrics = snapshot.get("queue_metrics") or {}
    return {
        "captured_at": row.get("captured_at"),
        "counts": snapshot.get("counts") or {"draft": 0, "review": 0, "approval": 0, "filed": 0, "total": 0},
        "overall_breached_count": _safe_int(snapshot.get("overall_breached_count")),
        "overall_due_soon_count": _safe_int(snapshot.get("overall_due_soon_count")),
        "active_owner_count": _safe_int(snapshot.get("active_owner_count")),
        "avg_active_age_hours": _safe_float(snapshot.get("avg_active_age_hours")),
        "oldest_active_age_hours": _safe_float(snapshot.get("oldest_active_age_hours")),
        "queue_metrics": queue_metrics,
        "source": row.get("source"),
        "captured_by": row.get("captured_by"),
        "metadata": metadata,
    }


def _bucket_key_for_range(captured_at: datetime | None, range_hours: int) -> str:
    dt = captured_at or _utcnow()
    if range_hours <= 48:
        return dt.strftime("%Y-%m-%d %H:00")
    if range_hours <= 168:
        return f"{dt.strftime('%Y-%m-%d')} {'00' if dt.hour < 12 else '12'}:00"
    return dt.strftime("%Y-%m-%d")


def _collapse_snapshot_points(points: list[dict[str, Any]], range_hours: int, point_limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for point in points:
        grouped[_bucket_key_for_range(_safe_datetime(point.get("captured_at")), range_hours)] = point
    collapsed = list(grouped.values())
    if len(collapsed) > point_limit:
        collapsed = collapsed[-point_limit:]
    return collapsed


async def _fetch_current_queue_data() -> dict[str, Any]:
    from services.cases import list_sar_queue

    return await list_sar_queue(queue="all", limit=200, offset=0)


async def _latest_snapshot_row(conn: Any) -> Any | None:
    return await conn.fetchrow(
        """
        SELECT id, captured_at, captured_by, source, snapshot, metadata
        FROM sar_queue_snapshots
        WHERE snapshot_type = 'sar_queue'
        ORDER BY captured_at DESC
        LIMIT 1
        """
    )


async def capture_sar_queue_snapshot(
    *,
    triggered_by: str | None = None,
    source: str = "manual",
    force: bool = False,
    bootstrap_if_empty: bool = False,
    backfill_hours: int = 0,
    interval_minutes: int = 60,
) -> dict[str, Any]:
    pool = get_pool()
    source_name = source or "manual"
    actor_name = triggered_by or "sla-analytics"
    interval = max(15, int(interval_minutes or 60))
    min_age = timedelta(minutes=max(15, int(settings.SLA_SNAPSHOT_MIN_INTERVAL_MINUTES)))

    queue_data = await _fetch_current_queue_data()
    base_payload = _normalize_snapshot_payload(queue_data)

    async with pool.acquire() as conn:
        await conn.execute("SELECT pg_advisory_xact_lock(410011)")
        latest_row = await _latest_snapshot_row(conn)
        if latest_row:
            latest_at = _safe_datetime(latest_row.get("captured_at"))
        else:
            latest_at = None

        inserted_count = 0
        captured = False

        if bootstrap_if_empty and latest_row is None and backfill_hours > 0:
            points = max(2, (backfill_hours * 60) // interval + 1)
            start_time = _utcnow() - timedelta(hours=backfill_hours)
            for index in range(points):
                progress = index / (points - 1) if points > 1 else 1.0
                snapshot_payload = _build_bootstrap_payload(base_payload, progress=progress, index=index, total_points=points)
                captured_at = start_time + timedelta(minutes=interval * index)
                await conn.execute(
                    """
                    INSERT INTO sar_queue_snapshots (
                        snapshot_type, captured_at, captured_by, source, snapshot, metadata
                    ) VALUES ('sar_queue', $1, $2, $3, $4::jsonb, $5::jsonb)
                    """,
                    captured_at,
                    actor_name,
                    "bootstrap",
                    json.dumps(snapshot_payload),
                    json.dumps({"bootstrapped": True, "interval_minutes": interval, "source": source_name}),
                )
                inserted_count += 1
            captured = True
        elif force or latest_at is None or (_utcnow() - latest_at) >= min_age:
            await conn.execute(
                """
                INSERT INTO sar_queue_snapshots (
                    snapshot_type, captured_at, captured_by, source, snapshot, metadata
                ) VALUES ('sar_queue', NOW(), $1, $2, $3::jsonb, $4::jsonb)
                """,
                actor_name,
                source_name,
                json.dumps(base_payload),
                json.dumps({"bootstrapped": False}),
            )
            inserted_count = 1
            captured = True

        rows = await conn.fetch(
            """
            SELECT captured_at, captured_by, source, snapshot, metadata
            FROM sar_queue_snapshots
            WHERE snapshot_type = 'sar_queue'
            ORDER BY captured_at ASC
            """
        )

    points = [_normalize_snapshot_row(row) for row in rows]
    oldest = points[0]["captured_at"] if points else None
    latest = points[-1]["captured_at"] if points else None
    summary = []
    if captured and inserted_count > 1:
        summary.append(f"Bootstrapped {inserted_count} historical SAR SLA snapshots across the last {backfill_hours} hours.")
    elif captured:
        summary.append("Captured a fresh SAR SLA snapshot from the live review queues.")
    else:
        summary.append("Skipped snapshot capture because the latest SAR SLA snapshot is still within the minimum interval.")
    if points:
        summary.append(f"History now contains {len(points)} persisted SAR SLA snapshots.")

    return {
        "captured": captured,
        "inserted_count": inserted_count,
        "snapshot_count": len(points),
        "latest_snapshot_at": latest,
        "oldest_snapshot_at": oldest,
        "source": source_name,
        "triggered_by": actor_name,
        "summary": summary,
    }


async def get_sar_queue_trends(
    *,
    hours: int | None = None,
    limit: int = 24,
    auto_capture: bool = True,
    bootstrap_if_empty: bool = True,
) -> dict[str, Any]:
    range_hours = max(12, min(int(hours or settings.SLA_TREND_DEFAULT_HOURS), 24 * 90))
    point_limit = max(6, min(int(limit or 24), 120))

    if auto_capture:
        await capture_sar_queue_snapshot(
            triggered_by="workflow-dashboard",
            source="dashboard_auto",
            force=False,
            bootstrap_if_empty=bootstrap_if_empty,
            backfill_hours=min(range_hours, 24 * 7),
            interval_minutes=720 if range_hours > 72 else 240,
        )

    cutoff = _utcnow() - timedelta(hours=range_hours)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT captured_at, captured_by, source, snapshot, metadata
            FROM (
                SELECT captured_at, captured_by, source, snapshot, metadata
                FROM sar_queue_snapshots
                WHERE snapshot_type = 'sar_queue' AND captured_at >= $1
                ORDER BY captured_at DESC
                LIMIT $2
            ) recent
            ORDER BY captured_at ASC
            """,
            cutoff,
            point_limit,
        )

    points = _collapse_snapshot_points([_normalize_snapshot_row(row) for row in rows], range_hours, point_limit)
    oldest = points[0]["captured_at"] if points else None
    latest = points[-1]["captured_at"] if points else None
    summary: list[str] = []

    if points:
        first = points[0]
        last = points[-1]
        first_active = _safe_int((first.get("counts") or {}).get("draft")) + _safe_int((first.get("counts") or {}).get("review")) + _safe_int((first.get("counts") or {}).get("approval"))
        last_active = _safe_int((last.get("counts") or {}).get("draft")) + _safe_int((last.get("counts") or {}).get("review")) + _safe_int((last.get("counts") or {}).get("approval"))
        active_delta = last_active - first_active
        breached_delta = _safe_int(last.get("overall_breached_count")) - _safe_int(first.get("overall_breached_count"))
        summary.append(f"Tracked {len(points)} persisted SAR SLA snapshots across the last {range_hours} hours.")
        summary.append(f"Active SAR workload is {last_active}, {'up' if active_delta >= 0 else 'down'} {abs(active_delta)} versus the oldest visible snapshot.")
        summary.append(f"Breached items are {last.get('overall_breached_count')}, {'up' if breached_delta >= 0 else 'down'} {abs(breached_delta)} across the visible window.")
        if any(bool((point.get("metadata") or {}).get("bootstrapped")) for point in points):
            summary.append("Early history includes bootstrapped demo snapshots until enough live captures accumulate.")
    else:
        summary.append("No SAR SLA snapshots have been captured yet.")

    return {
        "generated_at": _utcnow(),
        "range_hours": range_hours,
        "snapshot_count": len(points),
        "oldest_snapshot_at": oldest,
        "latest_snapshot_at": latest,
        "points": points,
        "summary": summary,
    }
