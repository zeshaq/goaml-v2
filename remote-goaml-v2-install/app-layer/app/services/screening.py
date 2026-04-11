"""
goAML-V2 sanctions screening service via yente.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
import json
from typing import Any
import xml.etree.ElementTree as ET

import httpx

from core.config import settings
from core.database import get_pool
from models.casework import ScreenEntityRequest
from services.graph_sync import safe_resync_graph


class ScreeningUnavailableError(Exception):
    pass


_OFAC_CACHE: dict[str, Any] = {"loaded_at": None, "entries": []}
_OFAC_NAMESPACE = {"ofac": "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/XML"}
SCREENING_PANEL_DEFS: list[dict[str, Any]] = [
    {
        "key": "un",
        "label": "UN sanctions",
        "dataset_keys": {"un_sc_sanctions"},
    },
    {
        "key": "eu",
        "label": "EU consolidated list",
        "dataset_keys": {"eu_fsf", "eu_travel_bans"},
    },
    {
        "key": "uk",
        "label": "UK sanctions",
        "dataset_keys": {"gb_hmt_sanctions", "gb_fcdo_sanctions", "gb_proscribed_orgs"},
    },
    {
        "key": "bis",
        "label": "BIS denied / entity lists",
        "dataset_keys": {"us_bis_dpl", "us_bis_entity_list", "us_bis_unverified", "us_trade_csl"},
    },
    {
        "key": "ofac",
        "label": "OFAC / U.S. sanctions",
        "dataset_keys": {"us_ofac_sdn", "us_ofac_cons"},
    },
]
SCREENING_SAMPLE_QUERIES: dict[str, str] = {
    "un": "AL-QAIDA IN THE ISLAMIC MAGHREB",
    "eu": "ALROSA",
    "uk": "ALROSA",
    "bis": "HUAWEI TECHNOLOGIES CO., LTD.",
    "ofac": "AEROCARIBBEAN AIRLINES",
}


async def screen_entity(payload: ScreenEntityRequest, *, resync_graph: bool = True) -> list[dict[str, Any]]:
    try:
        hits = await _query_yente(payload.entity_name, payload.limit)
    except Exception:
        hits = await _query_ofac_fallback(payload.entity_name, payload.limit)
    pool = get_pool()
    results: list[dict[str, Any]] = []

    async with pool.acquire() as conn:
        for hit in hits:
            matched_name = (
                hit.get("caption")
                or hit.get("name")
                or _first_value(hit.get("properties", {}).get("name"))
            )
            score = hit.get("score")
            dataset = _resolve_primary_dataset_label(hit)
            dataset_id = hit.get("id")
            schema = hit.get("schema")
            country = _first_value(hit.get("properties", {}).get("country"))
            entity_type = _to_entity_type(schema)

            row = await conn.fetchrow(
                """
                INSERT INTO screening_results (
                    entity_name, matched_name, match_score, dataset, dataset_id,
                    match_type, matched_country, matched_type, matched_detail,
                    screened_by, trigger, linked_txn_id
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8::entity_type, $9,
                    $10, $11, $12
                )
                RETURNING *
                """,
                payload.entity_name,
                matched_name,
                score,
                dataset,
                dataset_id,
                schema,
                country,
                entity_type,
                json.dumps(hit),
                payload.screened_by,
                payload.trigger,
                payload.linked_txn_id,
            )
            results.append(_normalize_screening_row(dict(row)))
    if results and resync_graph:
        await safe_resync_graph(clear_existing=True)
    return results


async def _query_yente(query: str, limit: int) -> list[dict[str, Any]]:
    candidates = [
        ("GET", f"{settings.YENTE_URL}/search/default", {"q": query, "limit": limit}),
        ("GET", f"{settings.YENTE_URL}/match/default", {"q": query, "limit": limit}),
        ("GET", f"{settings.YENTE_URL}/search", {"q": query, "limit": limit}),
        ("GET", f"{settings.YENTE_URL}/match", {"q": query, "limit": limit}),
    ]

    async with httpx.AsyncClient(timeout=10.0) as client:
        last_error: Exception | None = None
        for method, url, params in candidates:
            try:
                resp = await client.request(method, url, params=params)
                if resp.status_code == 500:
                    detail = ""
                    try:
                        data = resp.json()
                        detail = str(data.get("detail", ""))
                    except Exception:
                        detail = resp.text
                    if "initial ingestion of data is still ongoing" in detail or "Index yente-entities does not exist" in detail:
                        raise ScreeningUnavailableError(
                            "Sanctions screening is still indexing public data. Please retry in a few minutes."
                        )
                resp.raise_for_status()
                data = resp.json()
                return _extract_hits(data)[:limit]
            except ScreeningUnavailableError:
                raise
            except Exception as exc:
                last_error = exc
                continue

    if isinstance(last_error, ScreeningUnavailableError):
        raise last_error
    if last_error:
        raise last_error
    return []


async def _query_ofac_fallback(query: str, limit: int) -> list[dict[str, Any]]:
    entries = await _load_ofac_entries()
    norm_query = _normalize_name(query)
    scored: list[tuple[float, dict[str, Any]]] = []

    for entry in entries:
        names = [entry["name"], *entry["aka_names"]]
        best_name = entry["name"]
        best_score = 0.0
        for candidate in names:
            score = SequenceMatcher(None, norm_query, _normalize_name(candidate)).ratio()
            if norm_query in _normalize_name(candidate):
                score = max(score, 0.92)
            if score > best_score:
                best_score = score
                best_name = candidate

        if best_score >= 0.68:
            scored.append(
                (
                    best_score,
                    {
                        "id": entry["uid"],
                        "caption": best_name,
                        "dataset": "OFAC SDN",
                        "schema": entry["sdn_type"].lower(),
                        "properties": {
                            "name": [best_name],
                            "country": [entry["country"]] if entry["country"] else [],
                            "program": entry["programs"],
                        },
                        "score": round(best_score, 4),
                        "source": "ofac_public_xml_fallback",
                        "aka_names": entry["aka_names"],
                    },
                )
            )

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:limit]]


async def _load_ofac_entries() -> list[dict[str, Any]]:
    loaded_at = _OFAC_CACHE.get("loaded_at")
    if loaded_at and isinstance(loaded_at, datetime):
        if datetime.now(timezone.utc) - loaded_at < timedelta(hours=6):
            return _OFAC_CACHE["entries"]

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(settings.OFAC_SDN_XML_URL)
        resp.raise_for_status()
        xml_text = resp.text

    root = ET.fromstring(xml_text)
    entries: list[dict[str, Any]] = []

    for node in root.findall("ofac:sdnEntry", _OFAC_NAMESPACE):
        uid = _xml_text(node, "ofac:uid")
        last_name = _xml_text(node, "ofac:lastName")
        first_name = _xml_text(node, "ofac:firstName")
        full_name = " ".join(part for part in [first_name, last_name] if part).strip() or last_name or first_name or "Unknown"
        sdn_type = _xml_text(node, "ofac:sdnType") or "Unknown"
        programs = [p.text.strip() for p in node.findall("ofac:programList/ofac:program", _OFAC_NAMESPACE) if p.text]
        aka_names = []
        for aka in node.findall("ofac:akaList/ofac:aka", _OFAC_NAMESPACE):
            aka_last = _xml_text(aka, "ofac:lastName")
            aka_first = _xml_text(aka, "ofac:firstName")
            aka_name = " ".join(part for part in [aka_first, aka_last] if part).strip() or aka_last or aka_first
            if aka_name:
                aka_names.append(aka_name)
        country = _xml_text(node, "ofac:addressList/ofac:address/ofac:country")
        entries.append(
            {
                "uid": uid,
                "name": full_name,
                "sdn_type": sdn_type,
                "programs": programs,
                "aka_names": aka_names,
                "country": country,
            }
        )

    _OFAC_CACHE["loaded_at"] = datetime.now(timezone.utc)
    _OFAC_CACHE["entries"] = entries
    return entries


def _xml_text(node: ET.Element, path: str) -> str | None:
    child = node.find(path, _OFAC_NAMESPACE)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _normalize_name(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch.lower() if ch.isalnum() else " " for ch in value).strip()


def _to_entity_type(value: str | None) -> str:
    mapping = {
        "individual": "individual",
        "person": "individual",
        "entity": "company",
        "company": "company",
        "vessel": "company",
        "aircraft": "company",
        "organization": "company",
    }
    key = str(value or "").strip().lower()
    return mapping.get(key, "unknown")


def _extract_hits(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    for key in ("results", "matches", "entities"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _first_value(value: Any) -> str | None:
    if isinstance(value, list) and value:
        item = value[0]
        return str(item) if item is not None else None
    if value is None:
        return None
    return str(value)


def _normalize_screening_row(row: dict[str, Any]) -> dict[str, Any]:
    row["matched_detail"] = _normalize_json_dict(row.get("matched_detail"))
    if not row.get("dataset"):
        row["dataset"] = _resolve_primary_dataset_label(row["matched_detail"])
    return row


def _normalize_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def build_screening_panels(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    panels: list[dict[str, Any]] = []
    for panel in SCREENING_PANEL_DEFS:
        panel_rows = [row for row in rows if _row_matches_panel(row, panel["dataset_keys"], panel["key"])]
        panels.append(
            {
                "key": panel["key"],
                "label": panel["label"],
                "result_count": len(panel_rows),
                "results": panel_rows,
            }
        )
    return panels


def get_screening_sample_queries() -> dict[str, str]:
    return dict(SCREENING_SAMPLE_QUERIES)


def _row_matches_panel(row: dict[str, Any], dataset_keys: set[str], panel_key: str) -> bool:
    detail = row.get("matched_detail") or {}
    hit_datasets = _extract_dataset_keys(detail)
    if panel_key == "ofac" and detail.get("source") == "ofac_public_xml_fallback":
        return True
    return bool(hit_datasets & dataset_keys)


def _resolve_primary_dataset_label(hit: dict[str, Any]) -> str | None:
    dataset_keys = _extract_dataset_keys(hit)
    for panel in SCREENING_PANEL_DEFS:
        if dataset_keys & panel["dataset_keys"]:
            return panel["label"]
    if "dataset" in hit and hit.get("dataset"):
        return _dataset_code_to_label(str(hit["dataset"]))
    if dataset_keys:
        return _dataset_code_to_label(sorted(dataset_keys)[0])
    if hit.get("source") == "ofac_public_xml_fallback":
        return "OFAC / U.S. sanctions"
    return None


def _extract_dataset_keys(hit: dict[str, Any]) -> set[str]:
    datasets = hit.get("datasets")
    if isinstance(datasets, list):
        return {str(item).strip().lower() for item in datasets if item}
    dataset = hit.get("dataset")
    if dataset:
        return {str(dataset).strip().lower()}
    return set()


def _dataset_code_to_label(code: str) -> str:
    labels = {
        "un_sc_sanctions": "UN sanctions",
        "eu_fsf": "EU consolidated list",
        "eu_travel_bans": "EU travel bans",
        "gb_hmt_sanctions": "UK sanctions",
        "gb_fcdo_sanctions": "UK sanctions",
        "gb_proscribed_orgs": "UK proscribed organisations",
        "us_bis_dpl": "BIS denied persons",
        "us_bis_entity_list": "BIS entity list",
        "us_bis_unverified": "BIS unverified list",
        "us_trade_csl": "BIS / trade consolidated screening",
        "us_ofac_sdn": "OFAC SDN",
        "us_ofac_cons": "OFAC non-SDN",
    }
    return labels.get(code, code.replace("_", " ").title())
