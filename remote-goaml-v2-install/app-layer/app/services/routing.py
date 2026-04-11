"""
Routing helpers for analyst assignment by team and region.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any
from uuid import UUID


from core.config import settings


REGION_LABELS = {
    "south_asia": "South Asia",
    "mena": "MENA",
    "europe": "Europe and UK",
    "americas": "Americas",
    "africa": "Africa",
    "apac": "APAC",
    "global": "Global",
}

COUNTRY_REGION_MAP = {
    "BD": "south_asia",
    "IN": "south_asia",
    "PK": "south_asia",
    "LK": "south_asia",
    "NP": "south_asia",
    "AE": "mena",
    "SA": "mena",
    "IR": "mena",
    "IQ": "mena",
    "EG": "mena",
    "JO": "mena",
    "SY": "mena",
    "LB": "mena",
    "QA": "mena",
    "KW": "mena",
    "OM": "mena",
    "YE": "mena",
    "TR": "mena",
    "GB": "europe",
    "DE": "europe",
    "FR": "europe",
    "IT": "europe",
    "ES": "europe",
    "NL": "europe",
    "BE": "europe",
    "CH": "europe",
    "RU": "europe",
    "UA": "europe",
    "US": "americas",
    "CA": "americas",
    "MX": "americas",
    "CU": "americas",
    "BR": "americas",
    "AR": "americas",
    "CL": "americas",
    "CO": "americas",
    "PE": "americas",
    "PA": "americas",
    "NG": "africa",
    "ZA": "africa",
    "KE": "africa",
    "SG": "apac",
    "CN": "apac",
    "HK": "apac",
    "JP": "apac",
    "AU": "apac",
}


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


def _parse_directory() -> list[dict[str, Any]]:
    try:
        parsed = json.loads(settings.AML_ANALYST_DIRECTORY_JSON)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    directory: list[dict[str, Any]] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        directory.append(
            {
                "name": name,
                "team_key": str(item.get("team_key") or "global").strip() or "global",
                "team_label": str(item.get("team_label") or name).strip() or name,
                "regions": [str(region).strip() for region in item.get("regions", []) if str(region).strip()],
                "countries": [str(country).strip().upper() for country in item.get("countries", []) if str(country).strip()],
                "workflows": [str(workflow).strip() for workflow in item.get("workflows", []) if str(workflow).strip()],
            }
        )
    return directory


def analyst_directory() -> list[dict[str, Any]]:
    return _parse_directory()


def region_for_country(country_code: str | None) -> str:
    key = str(country_code or "").upper().strip()
    return COUNTRY_REGION_MAP.get(key, settings.OPS_ALERT_DEFAULT_REGION)


def region_label(region_key: str | None) -> str:
    return REGION_LABELS.get(str(region_key or "global"), "Global")


async def _country_candidates_from_links(
    conn: Any,
    *,
    primary_entity_id: UUID | None,
    primary_account_id: UUID | None,
    alert_ids: list[UUID] | None,
    transaction_ids: list[UUID] | None,
) -> list[str]:
    candidates: list[str] = []
    if primary_entity_id:
        value = await conn.fetchval("SELECT country FROM entities WHERE id = $1", primary_entity_id)
        if value:
            candidates.append(str(value).upper())
    if primary_account_id:
        value = await conn.fetchval("SELECT country FROM accounts WHERE id = $1", primary_account_id)
        if value:
            candidates.append(str(value).upper())
    if alert_ids:
        rows = await conn.fetch(
            """
            SELECT
                e.country AS entity_country,
                ac.country AS account_country,
                t.sender_country,
                t.receiver_country
            FROM alerts a
            LEFT JOIN entities e ON e.id = a.entity_id
            LEFT JOIN accounts ac ON ac.id = a.account_id
            LEFT JOIN transactions t ON t.id = a.transaction_id
            WHERE a.id = ANY($1::uuid[])
            """,
            alert_ids,
        )
        for row in rows:
            for key in ("entity_country", "account_country", "sender_country", "receiver_country"):
                value = row.get(key)
                if value:
                    candidates.append(str(value).upper())
    if transaction_ids:
        rows = await conn.fetch(
            """
            SELECT sender_country, receiver_country
            FROM transactions
            WHERE id = ANY($1::uuid[])
            """,
            transaction_ids,
        )
        for row in rows:
            for key in ("sender_country", "receiver_country"):
                value = row.get(key)
                if value:
                    candidates.append(str(value).upper())
    return [item for item in candidates if item]


async def _current_workload_map(conn: Any) -> dict[str, int]:
    rows = await conn.fetch(
        """
        SELECT assigned_to, COUNT(*)::int AS case_count
        FROM cases
        WHERE status <> 'closed'
          AND assigned_to IS NOT NULL
        GROUP BY assigned_to
        """
    )
    return {str(row["assigned_to"]): int(row["case_count"]) for row in rows if row["assigned_to"]}


async def resolve_case_routing(
    conn: Any,
    *,
    workflow_type: str,
    primary_entity_id: UUID | None = None,
    primary_account_id: UUID | None = None,
    alert_ids: list[UUID] | None = None,
    transaction_ids: list[UUID] | None = None,
    preferred_assignee: str | None = None,
    existing_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = _normalize_json_dict(existing_metadata)
    existing_routing = _normalize_json_dict(metadata.get("routing"))
    explicit_country = str(existing_routing.get("country") or "").upper().strip() or None
    explicit_region = str(existing_routing.get("region_key") or "").strip() or None

    countries = [explicit_country] if explicit_country else []
    countries.extend(
        await _country_candidates_from_links(
            conn,
            primary_entity_id=primary_entity_id,
            primary_account_id=primary_account_id,
            alert_ids=alert_ids or [],
            transaction_ids=transaction_ids or [],
        )
    )
    countries = [country for country in countries if country]
    selected_country = None
    if countries:
        counts = Counter(countries)
        selected_country = counts.most_common(1)[0][0]

    selected_region = explicit_region or region_for_country(selected_country)
    directory = analyst_directory()
    workflow_key = workflow_type.strip() or "general"

    eligible = [
        item for item in directory
        if (not item["workflows"] or workflow_key in item["workflows"] or "general" in item["workflows"])
        and (
            not item["regions"]
            or selected_region in item["regions"]
            or "global" in item["regions"]
            or (selected_country and selected_country in item["countries"])
        )
    ]
    if not eligible:
        eligible = [
            item for item in directory
            if not item["workflows"] or workflow_key in item["workflows"] or "general" in item["workflows"]
        ] or directory

    workload_map = await _current_workload_map(conn)
    eligible = sorted(
        eligible,
        key=lambda item: (
            0 if item["name"] == preferred_assignee else 1,
            workload_map.get(item["name"], 0),
            item["name"].lower(),
        ),
    )
    selected = eligible[0] if eligible else None
    preferred_allowed = bool(preferred_assignee and any(item["name"] == preferred_assignee for item in eligible))
    assignee = preferred_assignee if preferred_allowed else (selected["name"] if selected else None)
    team_key = selected["team_key"] if selected else settings.OPS_ALERT_DEFAULT_TEAM
    team_label = selected["team_label"] if selected else "Global AML Operations"

    reason_parts = []
    if selected_country:
        reason_parts.append(f"Primary country {selected_country}")
    if selected_region:
        reason_parts.append(f"mapped to {region_label(selected_region)}")
    if workflow_key:
        reason_parts.append(f"workflow {workflow_key.replace('_', ' ')}")
    reason_parts.append(f"assigned to {assignee or 'unassigned'}")

    return {
        "country": selected_country,
        "region_key": selected_region,
        "region_label": region_label(selected_region),
        "team_key": team_key,
        "team_label": team_label,
        "assigned_to": assignee,
        "eligible_analysts": [item["name"] for item in eligible],
        "reason": ", ".join(reason_parts),
    }


def routing_metadata_payload(
    routing: dict[str, Any] | None,
    *,
    workflow_type: str,
    source: str,
) -> dict[str, Any]:
    current = dict(routing or {})
    current["workflow_type"] = workflow_type
    current["source"] = source
    return current
