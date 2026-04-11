#!/usr/bin/env python3
"""
Seed a dense, synthetic AML investigation dataset for goAML-V2.

This script only replaces data previously created by the same seed batch.
It preserves unrelated records already present in the platform.
"""

from __future__ import annotations

import asyncio
import json
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

import httpx

from core.clickhouse import get_ch_client, init_clickhouse
from core.config import settings
from core.database import close_postgres, get_pool, init_postgres
from services.documents import _graph_candidates, _heuristic_structure, _regex_pii, _store_in_milvus, _store_in_minio_sync
from services.graph_sync import close_graph_driver, sync_graph_from_postgres


SEED_TAG = "synthetic_aml_dense_v1"
SEED_PREFIX = "seed_dense"
UTC = timezone.utc

ACCOUNT_COUNT = 60
ENTITY_COUNT = 48
ROUTINE_TX_COUNT = 560
SUSPICIOUS_TX_PER_THEME = 28
CASE_COUNT = 42
DOCUMENT_COUNT = 108
SCREENING_COUNT = 120
SAR_COUNT = 16
EMBEDDED_DOCUMENT_COUNT = 24

ANALYSTS = ["analyst1", "analyst2", "analyst3", "analyst4", "aml_ops"]
COUNTRIES = ["US", "AE", "BD", "NG", "PK", "SG", "HK", "GB", "TR", "CY", "VG", "KY"]
COMPANY_COUNTRIES = ["US", "AE", "SG", "HK", "TR", "CY", "VG", "KY", "NG", "GB"]
DATASETS = ["OFAC SDN", "EU Sanctions", "UK Sanctions", "UN Sanctions", "BIS Entity List"]
THEMES = [
    {
        "code": "structuring",
        "alert_type": "structuring",
        "description": "Repeated sub-threshold cash deposits and same-day outbound wires.",
        "transaction_type": "cash_deposit",
        "risk_factors": ["STRUCT", "CASH"],
    },
    {
        "code": "layering",
        "alert_type": "layering",
        "description": "Funds rapidly moved across shell entities and pass-through accounts.",
        "transaction_type": "wire_transfer",
        "risk_factors": ["LAYERING", "VELOCITY"],
    },
    {
        "code": "sanctions",
        "alert_type": "sanctions_match",
        "description": "Transactions routed toward a sanctioned beneficiary and related aliases.",
        "transaction_type": "international_wire",
        "risk_factors": ["SANCTIONS", "GEO"],
    },
    {
        "code": "geo",
        "alert_type": "unusual_geography",
        "description": "High-value corridor activity through multiple jurisdictions inside short windows.",
        "transaction_type": "wire_transfer",
        "risk_factors": ["GEO", "VELOCITY"],
    },
    {
        "code": "cash",
        "alert_type": "large_cash",
        "description": "Cash-intensive business account with abrupt deposit spikes and cross-border transfers.",
        "transaction_type": "cash_deposit",
        "risk_factors": ["CASH", "UNUSUAL_PATTERN"],
    },
    {
        "code": "crypto",
        "alert_type": "crypto_mixing",
        "description": "Customer used exchange-linked accounts and rapid wallet settlement behavior.",
        "transaction_type": "crypto",
        "risk_factors": ["CRYPTO", "VELOCITY"],
    },
    {
        "code": "pep",
        "alert_type": "pep_exposure",
        "description": "PEP-linked business moved funds through layered corporate structures.",
        "transaction_type": "wire_transfer",
        "risk_factors": ["PEP", "LAYERING"],
    },
]


@dataclass
class EntitySeed:
    id: str
    name: str
    entity_type: str
    country: str
    nationality: str | None
    date_of_birth: date | None
    id_number: str | None
    id_type: str | None
    is_pep: bool
    is_sanctioned: bool
    sanctions_list: list[str]
    risk_score: float
    risk_level: str
    metadata: dict[str, Any]


@dataclass
class AccountSeed:
    id: str
    account_number: str
    account_name: str
    account_type: str
    institution: str
    country: str
    opened_at: datetime
    risk_score: float
    risk_level: str
    metadata: dict[str, Any]
    owner_entity_id: str


def risk_level_for(score: float) -> str:
    if score >= 0.85:
        return "critical"
    if score >= 0.65:
        return "high"
    if score >= 0.4:
        return "medium"
    return "low"


def utc_now() -> datetime:
    return datetime.now(UTC)


def jsonb(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:48]


def random_dt(rng: random.Random, start_days_back: int = 75, end_days_back: int = 0) -> datetime:
    days_back = rng.randint(end_days_back, start_days_back)
    hours = rng.randint(0, 23)
    minutes = rng.randint(0, 59)
    seconds = rng.randint(0, 59)
    return utc_now() - timedelta(days=days_back, hours=hours, minutes=minutes, seconds=seconds)


def amount_decimal(value: float) -> Decimal:
    return Decimal(f"{value:.4f}")


async def clear_existing_seed(pool) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            case_ids = await conn.fetch(
                "SELECT id FROM cases WHERE metadata->>'seed_batch' = $1",
                SEED_TAG,
            )
            alert_ids = await conn.fetch(
                "SELECT id FROM alerts WHERE metadata->>'seed_batch' = $1",
                SEED_TAG,
            )
            txn_ids = await conn.fetch(
                "SELECT id FROM transactions WHERE metadata->>'seed_batch' = $1",
                SEED_TAG,
            )
            doc_ids = await conn.fetch(
                "SELECT id FROM documents WHERE metadata->>'seed_batch' = $1",
                SEED_TAG,
            )
            sar_ids = await conn.fetch(
                "SELECT id FROM sar_reports WHERE metadata->>'seed_batch' = $1",
                SEED_TAG,
            )
            entity_ids = await conn.fetch(
                "SELECT id FROM entities WHERE metadata->>'seed_batch' = $1",
                SEED_TAG,
            )
            account_ids = await conn.fetch(
                "SELECT id FROM accounts WHERE metadata->>'seed_batch' = $1",
                SEED_TAG,
            )

            case_values = [row["id"] for row in case_ids]
            alert_values = [row["id"] for row in alert_ids]
            txn_values = [row["id"] for row in txn_ids]
            entity_values = [row["id"] for row in entity_ids]
            account_values = [row["id"] for row in account_ids]

            if case_values:
                await conn.execute("DELETE FROM case_events WHERE case_id = ANY($1::uuid[])", case_values)
                await conn.execute("DELETE FROM case_transactions WHERE case_id = ANY($1::uuid[])", case_values)
                await conn.execute("DELETE FROM case_alerts WHERE case_id = ANY($1::uuid[])", case_values)

            if doc_ids:
                await conn.execute("DELETE FROM documents WHERE metadata->>'seed_batch' = $1", SEED_TAG)

            await conn.execute("DELETE FROM screening_results WHERE screened_by = $1", SEED_TAG)

            if case_values:
                await conn.execute("UPDATE cases SET sar_id = NULL WHERE id = ANY($1::uuid[])", case_values)
            if alert_values:
                await conn.execute("UPDATE alerts SET case_id = NULL WHERE id = ANY($1::uuid[])", alert_values)

            if sar_ids:
                await conn.execute("DELETE FROM sar_reports WHERE metadata->>'seed_batch' = $1", SEED_TAG)
            if alert_ids:
                await conn.execute("DELETE FROM alerts WHERE metadata->>'seed_batch' = $1", SEED_TAG)
            if case_ids:
                await conn.execute("DELETE FROM cases WHERE metadata->>'seed_batch' = $1", SEED_TAG)
            if txn_ids:
                await conn.execute("DELETE FROM transactions WHERE metadata->>'seed_batch' = $1", SEED_TAG)
            if account_values:
                await conn.execute("DELETE FROM account_entities WHERE account_id = ANY($1::uuid[])", account_values)
            if entity_values:
                await conn.execute("DELETE FROM account_entities WHERE entity_id = ANY($1::uuid[])", entity_values)
            if entity_ids:
                await conn.execute("DELETE FROM entities WHERE metadata->>'seed_batch' = $1", SEED_TAG)
            if account_ids:
                await conn.execute("DELETE FROM accounts WHERE metadata->>'seed_batch' = $1", SEED_TAG)


def clear_clickhouse_seed() -> None:
    client = get_ch_client()
    commands = [
        f"ALTER TABLE transaction_events DELETE WHERE external_id LIKE '{SEED_PREFIX}_%'",
        f"ALTER TABLE alert_events DELETE WHERE rule_id = '{SEED_TAG}'",
        f"ALTER TABLE risk_score_history DELETE WHERE trigger_type = '{SEED_TAG}'",
        f"ALTER TABLE screening_events DELETE WHERE trigger = '{SEED_TAG}'",
    ]
    for command in commands:
        try:
            client.command(command)
        except Exception:
            pass


def delete_seed_vectors(vector_ids: list[str]) -> None:
    if not vector_ids:
        return
    try:
        from pymilvus import Collection, connections, utility

        connections.connect(alias="default", host=settings.MILVUS_HOST, port=str(settings.MILVUS_PORT))
        if not utility.has_collection("document_chunks"):
            return
        collection = Collection("document_chunks")
        for start in range(0, len(vector_ids), 50):
            batch = vector_ids[start : start + 50]
            quoted = ", ".join(json.dumps(item) for item in batch)
            collection.delete(expr=f"id in [{quoted}]")
        collection.flush()
    except Exception:
        pass


def build_entities(rng: random.Random) -> tuple[list[EntitySeed], dict[str, list[str]]]:
    first_names = [
        "Amina", "Rahim", "Karim", "Fatima", "Nadia", "Sajid", "Mariam", "Yusuf", "Layla", "Omar",
        "Samira", "Rafiq", "Farah", "Tariq", "Salma", "Imran", "Noor", "Kamal", "Nasrin", "Javed",
        "Hina", "Iqbal", "Shirin", "Mahmud", "Tania", "Arif", "Sadia", "Noman",
    ]
    last_names = [
        "Khan", "Rahman", "Ahmed", "Chowdhury", "Karim", "Siddiqui", "Hossain", "Malik", "Qureshi", "Hasan",
        "Rashid", "Farooq", "Sultan", "Mahmood", "Aziz", "Latif", "Habib", "Jalal", "Sharif", "Kabir",
    ]
    company_heads = [
        "Meridian", "Blue Creek", "East Pier", "Crescent", "Nova", "Golden Dunes", "Harborline", "Silk Route",
        "Atlas", "North Gate", "Silver Oak", "Sandstone", "Delta Bridge", "Apex", "Gulf Bridge", "Orchid",
    ]
    company_tails = [
        "Trading", "Logistics", "Consulting", "Ventures", "Remit", "Holdings", "Exchange", "Industries",
        "Payments", "Exports", "Partners", "Services", "Capital", "Resources", "Finance", "Shipping",
    ]
    suffixes = ["LLC", "Ltd", "FZE", "Inc", "Pte Ltd", "PLC"]

    entities: list[EntitySeed] = []
    traits = {"sanctioned": [], "pep": [], "shell": []}

    for index in range(ENTITY_COUNT):
        entity_id = str(uuid4())
        if index < ENTITY_COUNT // 2:
            first = first_names[index % len(first_names)]
            last = last_names[(index * 3) % len(last_names)]
            name = f"{first} {last}"
            country = COUNTRIES[index % len(COUNTRIES)]
            is_pep = index in {3, 7, 11, 15, 19, 22}
            is_sanctioned = index in {5, 12, 21}
            sanctions_list = ["OFAC SDN", "UN Sanctions"] if is_sanctioned else []
            risk = 0.88 if is_sanctioned else 0.74 if is_pep else round(rng.uniform(0.18, 0.52), 4)
            entity = EntitySeed(
                id=entity_id,
                name=name,
                entity_type="individual",
                country=country,
                nationality=country,
                date_of_birth=date(1965 + (index % 25), (index % 11) + 1, (index % 26) + 1),
                id_number=f"P{index + 2000000}",
                id_type="passport",
                is_pep=is_pep,
                is_sanctioned=is_sanctioned,
                sanctions_list=sanctions_list,
                risk_score=risk,
                risk_level=risk_level_for(risk),
                metadata={"seed_batch": SEED_TAG, "seed_category": "individual", "seed_index": index},
            )
            if is_pep or is_sanctioned:
                entity.metadata["resolution_status"] = "watchlist_active"
                entity.metadata["watchlist_state"] = {
                    "status": "active",
                    "source": "external_screening" if is_sanctioned else "internal_pep_review",
                    "reason": (
                        "Seeded sanctions-linked individual placed on enhanced review watchlist."
                        if is_sanctioned
                        else "Seeded politically exposed person placed on enhanced due diligence watchlist."
                    ),
                    "added_by": "seed_engine",
                    "added_at": utc_now().isoformat(),
                }
            if is_pep:
                traits["pep"].append(entity_id)
            if is_sanctioned:
                traits["sanctioned"].append(entity_id)
        else:
            head = company_heads[(index * 2) % len(company_heads)]
            tail = company_tails[index % len(company_tails)]
            suffix = suffixes[index % len(suffixes)]
            name = f"{head} {tail} {suffix}"
            country = COMPANY_COUNTRIES[index % len(COMPANY_COUNTRIES)]
            is_shell = index in {26, 29, 33, 37, 40, 43}
            is_sanctioned = index in {28, 35, 41}
            sanctions_list = ["EU Sanctions", "BIS Entity List"] if is_sanctioned else []
            risk = 0.91 if is_sanctioned else 0.79 if is_shell else round(rng.uniform(0.24, 0.61), 4)
            entity = EntitySeed(
                id=entity_id,
                name=name,
                entity_type="company",
                country=country,
                nationality=None,
                date_of_birth=None,
                id_number=f"REG-{index + 4000}",
                id_type="registration",
                is_pep=False,
                is_sanctioned=is_sanctioned,
                sanctions_list=sanctions_list,
                risk_score=risk,
                risk_level=risk_level_for(risk),
                metadata={"seed_batch": SEED_TAG, "seed_category": "company", "seed_index": index},
            )
            if is_sanctioned:
                entity.metadata["resolution_status"] = "watchlist_active"
                entity.metadata["watchlist_state"] = {
                    "status": "active",
                    "source": "external_screening",
                    "reason": "Seeded sanctioned company placed on watchlist review.",
                    "added_by": "seed_engine",
                    "added_at": utc_now().isoformat(),
                }
            if is_shell:
                traits["shell"].append(entity_id)
            if is_sanctioned:
                traits["sanctioned"].append(entity_id)
        entities.append(entity)

    return entities, traits


def build_accounts(rng: random.Random, entities: list[EntitySeed]) -> tuple[list[AccountSeed], list[tuple[str, str, str, datetime]]]:
    institutions = ["Meridian Bank", "Harbor Commercial", "Apex Correspondent", "Crescent Trust", "Orchid Bank"]
    accounts: list[AccountSeed] = []
    account_links: list[tuple[str, str, str, datetime]] = []

    for index in range(ACCOUNT_COUNT):
        entity = entities[index % len(entities)]
        account_id = str(uuid4())
        opened_at = utc_now() - timedelta(days=180 + index * 3)
        risk_score = round(min(0.98, max(0.08, entity.risk_score + rng.uniform(-0.08, 0.12))), 4)
        account = AccountSeed(
            id=account_id,
            account_number=f"ACC-SD-{index + 1:05d}",
            account_name=f"{entity.name} Operating",
            account_type="business" if entity.entity_type == "company" else "personal",
            institution=institutions[index % len(institutions)],
            country=entity.country,
            opened_at=opened_at,
            risk_score=risk_score,
            risk_level=risk_level_for(risk_score),
            metadata={"seed_batch": SEED_TAG, "seed_index": index},
            owner_entity_id=entity.id,
        )
        accounts.append(account)
        account_links.append((account.id, entity.id, "owner", opened_at))

    for extra_index in range(12):
        account = accounts[extra_index * 2]
        entity = entities[(extra_index * 3 + 7) % len(entities)]
        account_links.append((account.id, entity.id, "beneficiary", account.opened_at + timedelta(days=10)))

    return accounts, account_links


async def fetch_embedding(text: str) -> list[float] | None:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.EMBED_URL.rstrip('/')}/embeddings",
                json={"model": "llama-nemotron-embed-1b-v2", "input": text[:8000]},
            )
            resp.raise_for_status()
            data = resp.json()
        return data["data"][0]["embedding"]
    except Exception:
        return None


async def build_documents(
    cases: list[dict[str, Any]],
    case_txns: dict[str, list[dict[str, Any]]],
    case_alerts: dict[str, list[dict[str, Any]]],
    entity_lookup: dict[str, EntitySeed],
    account_lookup: dict[str, AccountSeed],
) -> tuple[list[tuple[Any, ...]], list[tuple[str, str, str]], list[str]]:
    docs: list[tuple[Any, ...]] = []
    vector_ids_to_clear: list[str] = []

    counter = 0
    for case in cases:
        case_id = case["id"]
        primary_account = account_lookup.get(case["primary_account_id"])
        primary_entity = entity_lookup.get(case["primary_entity_id"]) if case.get("primary_entity_id") else None
        related_alerts = case_alerts.get(case_id, [])[:3]
        related_txns = case_txns.get(case_id, [])[:4]
        for doc_kind in ("analyst_note", "supporting_packet"):
            if counter >= DOCUMENT_COUNT:
                break
            counter += 1
            filename = f"seed-case-{counter:04d}-{doc_kind}.txt"
            txn_lines = "\n".join(
                f"- {txn['transaction_ref']} | ${txn['amount_usd']:.2f} | {txn['sender_name']} -> {txn['receiver_name']}"
                for txn in related_txns
            )
            alert_lines = "\n".join(
                f"- {alert['alert_ref']} | {alert['alert_type']} | {alert['title']}"
                for alert in related_alerts
            )
            text = (
                f"Case reference: {case['case_ref']}\n"
                f"Case theme: {case['title']}\n"
                f"Analyst: {case['assigned_to']}\n"
                f"Primary account: {primary_account.account_number if primary_account else 'unknown'}\n"
                f"Primary entity: {primary_entity.name if primary_entity else 'unknown'}\n"
                f"Jurisdiction: {primary_account.country if primary_account else 'unknown'}\n"
                f"Alert highlights:\n{alert_lines or '- no alerts recorded'}\n"
                f"Transaction highlights:\n{txn_lines or '- no transactions recorded'}\n"
                f"Investigator note: The account exhibited repeated layering, cross-border wires, and adverse screening context. "
                f"Contact email {slugify(primary_entity.name if primary_entity else case['case_ref'])}@example.com and passport P{counter + 700000} appeared in the onboarding file.\n"
            )
            structured = _heuristic_structure(text)
            pii = {"entities": _regex_pii(text)}
            pii_detected = bool(pii["entities"])
            embedded = counter <= EMBEDDED_DOCUMENT_COUNT
            embedding_ids: list[str] = []
            if embedded:
                vector_id = f"{SEED_PREFIX}-doc-{counter:04d}"
                vector_ids_to_clear.append(vector_id)
                vector = await fetch_embedding(text)
                if vector is not None:
                    try:
                        await _store_in_milvus(vector_id, filename, text[:4000], vector)
                        embedding_ids = [vector_id]
                    except Exception:
                        embedding_ids = []
            raw_bytes = text.encode("utf-8")
            checksum = __import__("hashlib").sha256(raw_bytes).hexdigest()
            try:
                storage_path = _store_in_minio_sync(filename, "text/plain", raw_bytes)
            except Exception:
                storage_path = f"s3://{settings.MINIO_BUCKET}/seed/{filename}"
            file_size = len(raw_bytes)
            tx_id = related_txns[0]["id"] if related_txns else None
            entity_id = primary_entity.id if primary_entity else None
            docs.append(
                (
                    str(uuid4()),
                    filename,
                    "txt",
                    file_size,
                    storage_path,
                    checksum,
                    text,
                    False,
                    None,
                    True,
                    jsonb(structured),
                    pii_detected,
                    jsonb(pii),
                    bool(embedding_ids),
                    embedding_ids or None,
                    case_id,
                    entity_id,
                    tx_id,
                    case["assigned_to"],
                    jsonb(
                        {
                            "seed_batch": SEED_TAG,
                            "seed_case_ref": case["case_ref"],
                            "seed_doc_kind": doc_kind,
                            "graph_candidates": _graph_candidates(structured, pii, text),
                        }
                    ),
                )
            )

    if counter < DOCUMENT_COUNT:
        fallback_entities = list(entity_lookup.values())
        for extra_index in range(counter + 1, DOCUMENT_COUNT + 1):
            entity = fallback_entities[(extra_index - 1) % len(fallback_entities)]
            linked_account = next((account for account in account_lookup.values() if account.owner_entity_id == entity.id), None)
            filename = f"seed-entity-{extra_index:04d}-dossier.txt"
            text = (
                f"Entity dossier: {entity.name}\n"
                f"Entity type: {entity.entity_type}\n"
                f"Country: {entity.country}\n"
                f"Risk level: {entity.risk_level}\n"
                f"Known account: {linked_account.account_number if linked_account else 'unknown'}\n"
                f"Sanctions status: {'yes' if entity.is_sanctioned else 'no'}\n"
                f"PEP status: {'yes' if entity.is_pep else 'no'}\n"
                f"Notes: Seeded counterparty dossier used for graph drill-down, document retrieval, and case evidence density.\n"
                f"Contact email {slugify(entity.name)}@example.com and reference passport P{extra_index + 850000}.\n"
            )
            structured = _heuristic_structure(text)
            pii = {"entities": _regex_pii(text)}
            raw_bytes = text.encode("utf-8")
            checksum = __import__("hashlib").sha256(raw_bytes).hexdigest()
            try:
                storage_path = _store_in_minio_sync(filename, "text/plain", raw_bytes)
            except Exception:
                storage_path = f"s3://{settings.MINIO_BUCKET}/seed/{filename}"
            docs.append(
                (
                    str(uuid4()),
                    filename,
                    "txt",
                    len(raw_bytes),
                    storage_path,
                    checksum,
                    text,
                    False,
                    None,
                    True,
                    jsonb(structured),
                    bool(pii["entities"]),
                    jsonb(pii),
                    False,
                    None,
                    None,
                    entity.id,
                    None,
                    "seed_engine",
                    jsonb(
                        {
                            "seed_batch": SEED_TAG,
                            "seed_doc_kind": "entity_dossier",
                            "graph_candidates": _graph_candidates(structured, pii, text),
                        }
                    ),
                )
            )

    return docs, [], vector_ids_to_clear


def chunked(rows: list[Any], size: int) -> list[list[Any]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)]


async def main() -> None:
    rng = random.Random(20260411)
    await init_postgres()
    init_clickhouse()
    pool = get_pool()

    print(f"[seed] clearing prior seed batch: {SEED_TAG}")
    await clear_existing_seed(pool)
    clear_clickhouse_seed()

    entities, traits = build_entities(rng)
    entity_lookup = {entity.id: entity for entity in entities}
    accounts, account_links = build_accounts(rng, entities)
    account_lookup = {account.id: account for account in accounts}

    theme_account_pools: dict[str, list[AccountSeed]] = {}
    theme_entity_pools: dict[str, list[EntitySeed]] = {}
    for index, theme in enumerate(THEMES):
        base = index * 6
        theme_account_pools[theme["code"]] = accounts[base : base + 6]
        theme_entity_pools[theme["code"]] = [entity_lookup[item.owner_entity_id] for item in theme_account_pools[theme["code"]]]

    transactions: list[dict[str, Any]] = []
    for idx in range(ROUTINE_TX_COUNT):
        sender = accounts[idx % len(accounts)]
        receiver = accounts[(idx * 7 + 11) % len(accounts)]
        if receiver.id == sender.id:
            receiver = accounts[(idx * 7 + 12) % len(accounts)]
        amount = round(rng.uniform(180.0, 28000.0), 2)
        score = round(rng.uniform(0.05, 0.38), 4)
        if idx % 19 == 0:
            score = round(rng.uniform(0.41, 0.58), 4)
        sender_entity = entity_lookup[sender.owner_entity_id]
        receiver_entity = entity_lookup[receiver.owner_entity_id]
        transactions.append(
            {
                "id": str(uuid4()),
                "external_id": f"{SEED_PREFIX}_txn_{idx + 1:06d}",
                "transaction_ref": f"TXN-SD-{idx + 1:06d}",
                "transaction_type": rng.choice(["wire_transfer", "ach", "internal_transfer", "check"]),
                "status": "completed",
                "sender_account_id": sender.id,
                "sender_account_ref": sender.account_number,
                "sender_name": sender_entity.name,
                "sender_country": sender.country,
                "receiver_account_id": receiver.id,
                "receiver_account_ref": receiver.account_number,
                "receiver_name": receiver_entity.name,
                "receiver_country": receiver.country,
                "amount": amount_decimal(amount),
                "currency": "USD",
                "amount_usd": amount_decimal(amount),
                "risk_score": score,
                "risk_level": risk_level_for(score),
                "risk_factors": ["GEO"] if score >= 0.41 else [],
                "ml_score_raw": score,
                "description": "Routine customer activity seeded for analytics and dashboard density.",
                "reference": f"seed-routine-{idx + 1}",
                "channel": rng.choice(["online", "branch", "api"]),
                "ip_address": None,
                "device_id": f"seed-device-{idx % 45:03d}",
                "geo_lat": None,
                "geo_lon": None,
                "metadata": {"seed_batch": SEED_TAG, "scenario": "routine"},
                "transacted_at": random_dt(rng, start_days_back=60),
                "processed_at": utc_now(),
            }
        )

    suspicious_transactions_by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for theme in THEMES:
        pool_accounts = theme_account_pools[theme["code"]]
        pool_entities = theme_entity_pools[theme["code"]]
        for idx in range(SUSPICIOUS_TX_PER_THEME):
            sender = pool_accounts[idx % len(pool_accounts)]
            receiver = pool_accounts[(idx + 1) % len(pool_accounts)]
            sender_entity = entity_lookup[sender.owner_entity_id]
            receiver_entity = entity_lookup[receiver.owner_entity_id]
            if theme["code"] == "sanctions":
                sanctioned_entity_id = traits["sanctioned"][idx % len(traits["sanctioned"])]
                receiver_entity = entity_lookup[sanctioned_entity_id]
                receiver = next(account for account in accounts if account.owner_entity_id == sanctioned_entity_id)
            amount_range = {
                "structuring": (8700, 9950),
                "layering": (42000, 118000),
                "sanctions": (65000, 155000),
                "geo": (38000, 92000),
                "cash": (18000, 64000),
                "crypto": (12000, 76000),
                "pep": (52000, 168000),
            }[theme["code"]]
            amount = round(rng.uniform(*amount_range), 2)
            score = round(rng.uniform(0.72, 0.97), 4)
            transaction = {
                "id": str(uuid4()),
                "external_id": f"{SEED_PREFIX}_{theme['code']}_{idx + 1:04d}",
                "transaction_ref": f"TXN-{theme['code'].upper()}-{idx + 1:04d}",
                "transaction_type": theme["transaction_type"],
                "status": "completed",
                "sender_account_id": sender.id,
                "sender_account_ref": sender.account_number,
                "sender_name": sender_entity.name,
                "sender_country": sender.country,
                "receiver_account_id": receiver.id,
                "receiver_account_ref": receiver.account_number,
                "receiver_name": receiver_entity.name,
                "receiver_country": receiver.country,
                "amount": amount_decimal(amount),
                "currency": "USD",
                "amount_usd": amount_decimal(amount),
                "risk_score": score,
                "risk_level": risk_level_for(score),
                "risk_factors": theme["risk_factors"],
                "ml_score_raw": score,
                "description": theme["description"],
                "reference": f"seed-{theme['code']}-{idx + 1}",
                "channel": rng.choice(["online", "api", "branch"]),
                "ip_address": None,
                "device_id": f"seed-{theme['code']}-device-{idx % 12}",
                "geo_lat": None,
                "geo_lon": None,
                "metadata": {"seed_batch": SEED_TAG, "scenario": theme["code"]},
                "transacted_at": random_dt(rng, start_days_back=35),
                "processed_at": utc_now(),
                "theme_code": theme["code"],
            }
            suspicious_transactions_by_theme[theme["code"]].append(transaction)
            transactions.append(transaction)

    alert_specs: list[dict[str, Any]] = []
    for theme in THEMES:
        themed = suspicious_transactions_by_theme[theme["code"]]
        for idx, txn in enumerate(themed[:20]):
            alert_specs.append(
                {
                    "id": str(uuid4()),
                    "alert_ref": f"ALT-{theme['code'].upper()}-{idx + 1:04d}",
                    "alert_type": theme["alert_type"],
                    "status": rng.choice(["open", "reviewing", "escalated", "open"]),
                    "severity": "critical" if float(txn["risk_score"]) >= 0.9 else "high",
                    "transaction_id": txn["id"],
                    "account_id": txn["sender_account_id"],
                    "entity_id": account_lookup[txn["sender_account_id"]].owner_entity_id,
                    "case_id": None,
                    "title": f"{theme['code'].replace('_', ' ').title()} pattern detected",
                    "description": theme["description"],
                    "evidence": {
                        "transaction_ref": txn["transaction_ref"],
                        "risk_factors": txn["risk_factors"],
                        "amount_usd": float(txn["amount_usd"]),
                    },
                    "rule_id": SEED_TAG,
                    "ml_explanation": f"Seeded alert for {theme['code']} behavior.",
                    "assigned_to": rng.choice(ANALYSTS),
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "closed_at": None,
                    "resolution_note": None,
                    "metadata": {"seed_batch": SEED_TAG, "theme": theme["code"]},
                    "created_at": txn["transacted_at"] + timedelta(minutes=15),
                }
            )

    medium_candidates = [txn for txn in transactions if 0.42 <= float(txn["risk_score"]) <= 0.60][:20]
    for idx, txn in enumerate(medium_candidates):
        alert_specs.append(
            {
                "id": str(uuid4()),
                "alert_ref": f"ALT-MED-{idx + 1:04d}",
                "alert_type": rng.choice(["velocity", "unusual_pattern", "rapid_movement"]),
                "status": rng.choice(["open", "reviewing"]),
                "severity": "medium",
                "transaction_id": txn["id"],
                "account_id": txn["sender_account_id"],
                "entity_id": account_lookup[txn["sender_account_id"]].owner_entity_id,
                "case_id": None,
                "title": "Medium-risk anomaly cluster",
                "description": "Seeded medium-risk alert for dashboard density.",
                "evidence": {"transaction_ref": txn["transaction_ref"], "risk_score": float(txn["risk_score"])},
                "rule_id": SEED_TAG,
                "ml_explanation": "Routine anomaly promoted for analyst queue seeding.",
                "assigned_to": rng.choice(ANALYSTS),
                "reviewed_by": None,
                "reviewed_at": None,
                "closed_at": None,
                "resolution_note": None,
                "metadata": {"seed_batch": SEED_TAG, "theme": "medium"},
                "created_at": txn["transacted_at"] + timedelta(minutes=20),
            }
        )

    alert_lookup = {alert["id"]: alert for alert in alert_specs}
    txn_lookup = {txn["id"]: txn for txn in transactions}
    alerts_by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alert in alert_specs:
        alerts_by_theme[alert["metadata"]["theme"]].append(alert)

    cases: list[dict[str, Any]] = []
    case_alert_links: list[tuple[str, str, datetime]] = []
    case_txn_links: list[tuple[str, str, datetime, str]] = []
    case_events: list[tuple[Any, ...]] = []

    case_counter = 0
    for theme in THEMES:
        themed_alerts = alerts_by_theme[theme["code"]]
        chunks = [themed_alerts[i : i + 4] for i in range(0, len(themed_alerts), 4)]
        for chunk in chunks:
            if case_counter >= CASE_COUNT - 2:
                break
            case_counter += 1
            primary_account_id = chunk[0]["account_id"]
            primary_entity_id = chunk[0]["entity_id"]
            status = rng.choice(["open", "reviewing", "pending_sar", "referred"])
            priority = "critical" if any(alert["severity"] == "critical" for alert in chunk) else "high"
            case_id = str(uuid4())
            ai_summary = (
                f"Seeded investigation for {theme['code']} activity on {account_lookup[primary_account_id].account_number}. "
                f"{len(chunk)} alerts and {len(chunk) + 2} related transactions point to {theme['description'].lower()}"
            )
            risk_factors = list(dict.fromkeys(theme["risk_factors"] + [theme["alert_type"].upper()]))
            case = {
                "id": case_id,
                "case_ref": f"CASE-SD-{case_counter:04d}",
                "title": f"{theme['code'].replace('_', ' ').title()} review — {account_lookup[primary_account_id].account_name}",
                "description": theme["description"],
                "status": status,
                "priority": priority,
                "assigned_to": rng.choice(ANALYSTS),
                "created_by": "seed_engine",
                "closed_by": None,
                "closed_at": None,
                "primary_account_id": primary_account_id,
                "primary_entity_id": primary_entity_id,
                "sar_required": priority in {"high", "critical"},
                "sar_id": None,
                "ai_summary": ai_summary,
                "ai_risk_factors": risk_factors,
                "metadata": {"seed_batch": SEED_TAG, "theme": theme["code"]},
                "created_at": min(alert["created_at"] for alert in chunk) - timedelta(hours=3),
                "updated_at": utc_now(),
            }
            cases.append(case)
            linked_tx_ids = []
            for alert in chunk:
                alert["case_id"] = case_id
                case_alert_links.append((case_id, alert["id"], alert["created_at"]))
                linked_tx_ids.append(alert["transaction_id"])
            themed_txns = suspicious_transactions_by_theme[theme["code"]]
            extra_txns = [txn for txn in themed_txns if txn["id"] not in linked_tx_ids][:2]
            for txn_id in linked_tx_ids + [item["id"] for item in extra_txns]:
                txn = txn_lookup[txn_id]
                case_txn_links.append((case_id, txn_id, txn["transacted_at"], f"Seeded from {theme['code']} cluster"))

            case_events.append(
                (
                    str(uuid4()),
                    case_id,
                    "created",
                    case["created_by"],
                    "Seeded case created",
                    jsonb({"seed_batch": SEED_TAG, "theme": theme["code"]}),
                    case["created_at"],
                )
            )
            case_events.append(
                (
                    str(uuid4()),
                    case_id,
                    "ai_summary_generated",
                    "seed_engine",
                    "Seeded AI summary loaded",
                    jsonb({"risk_factors": risk_factors}),
                    case["created_at"] + timedelta(minutes=18),
                )
            )

    screening_focus_entities = traits["sanctioned"][:2]
    for entity_id in screening_focus_entities:
        if case_counter >= CASE_COUNT:
            break
        case_counter += 1
        entity = entity_lookup[entity_id]
        linked_account = next(account for account in accounts if account.owner_entity_id == entity_id)
        case_id = str(uuid4())
        created_at = utc_now() - timedelta(days=3 + case_counter)
        cases.append(
            {
                "id": case_id,
                "case_ref": f"CASE-SD-{case_counter:04d}",
                "title": f"Adverse media / sanctions review — {entity.name}",
                "description": "Screening-only seeded case for graph pathfinding and analyst drill-down.",
                "status": "reviewing",
                "priority": "critical",
                "assigned_to": rng.choice(ANALYSTS),
                "created_by": "seed_engine",
                "closed_by": None,
                "closed_at": None,
                "primary_account_id": linked_account.id,
                "primary_entity_id": entity_id,
                "sar_required": True,
                "sar_id": None,
                "ai_summary": f"Screening hit against {entity.name} requires enhanced due diligence and cross-border transaction review.",
                "ai_risk_factors": ["SANCTIONS", "SCREENING", "CROSS_BORDER"],
                "metadata": {
                    "seed_batch": SEED_TAG,
                    "theme": "screening",
                    "entity_workflow": "watchlist_review",
                    "watchlist_reason": f"Seeded watchlist review for {entity.name} based on sanctions screening.",
                },
                "created_at": created_at,
                "updated_at": utc_now(),
            }
        )
        case_events.append(
            (
                str(uuid4()),
                case_id,
                "created",
                "seed_engine",
                "Seeded screening case created",
                jsonb({"seed_batch": SEED_TAG, "entity_id": entity_id}),
                created_at,
            )
        )

    if case_counter < CASE_COUNT:
        medium_chunks = [alerts_by_theme["medium"][i : i + 4] for i in range(0, len(alerts_by_theme["medium"]), 4)]
        for chunk in medium_chunks:
            if case_counter >= CASE_COUNT:
                break
            if not chunk:
                continue
            case_counter += 1
            primary_account_id = chunk[0]["account_id"]
            primary_entity_id = chunk[0]["entity_id"]
            created_at = min(alert["created_at"] for alert in chunk) - timedelta(hours=2)
            case_id = str(uuid4())
            cases.append(
                {
                    "id": case_id,
                    "case_ref": f"CASE-SD-{case_counter:04d}",
                    "title": f"Medium-risk monitoring — {account_lookup[primary_account_id].account_name}",
                    "description": "Seeded medium-risk queue case for analyst workflow testing.",
                    "status": "open",
                    "priority": "medium",
                    "assigned_to": rng.choice(ANALYSTS),
                    "created_by": "seed_engine",
                    "closed_by": None,
                    "closed_at": None,
                    "primary_account_id": primary_account_id,
                    "primary_entity_id": primary_entity_id,
                    "sar_required": False,
                    "sar_id": None,
                    "ai_summary": "Medium-risk anomalies were grouped for analyst triage and follow-up monitoring.",
                    "ai_risk_factors": ["VELOCITY", "MONITORING"],
                    "metadata": {"seed_batch": SEED_TAG, "theme": "medium"},
                    "created_at": created_at,
                    "updated_at": utc_now(),
                }
            )
            for alert in chunk:
                alert["case_id"] = case_id
                case_alert_links.append((case_id, alert["id"], alert["created_at"]))
                txn = txn_lookup[alert["transaction_id"]]
                case_txn_links.append((case_id, txn["id"], txn["transacted_at"], "Seeded from medium-risk queue"))
            case_events.append(
                (
                    str(uuid4()),
                    case_id,
                    "created",
                    "seed_engine",
                    "Seeded medium-risk case created",
                    jsonb({"seed_batch": SEED_TAG, "theme": "medium"}),
                    created_at,
                )
            )

    case_lookup = {case["id"]: case for case in cases}
    case_txns_lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case_id, txn_id, _, _ in case_txn_links:
        case_txns_lookup[case_id].append(txn_lookup[txn_id])
    case_alerts_lookup: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case_id, alert_id, _ in case_alert_links:
        case_alerts_lookup[case_id].append(alert_lookup[alert_id])

    deterministic_vector_ids = [f"{SEED_PREFIX}-doc-{index:04d}" for index in range(1, EMBEDDED_DOCUMENT_COUNT + 1)]
    delete_seed_vectors(deterministic_vector_ids)
    documents, _, _ = await build_documents(
        cases,
        case_txns_lookup,
        case_alerts_lookup,
        entity_lookup,
        account_lookup,
    )

    screening_results: list[tuple[Any, ...]] = []
    screening_events: list[list[Any]] = []
    screening_counter = 0
    focus_entities = traits["sanctioned"] + traits["pep"][:6] + [entity.id for entity in entities]
    for entity_id in focus_entities:
        entity = entity_lookup[entity_id]
        linked_account = next((account for account in accounts if account.owner_entity_id == entity_id), None)
        linked_txns = [txn for txn in transactions if txn["sender_account_id"] == linked_account.id][:2] if linked_account else []
        hit_count = 3 if entity.is_sanctioned or entity.is_pep else 2
        for hit_index in range(hit_count):
            if screening_counter >= SCREENING_COUNT:
                break
            screening_counter += 1
            dataset = DATASETS[(screening_counter - 1) % len(DATASETS)]
            match_score = round(0.97 - hit_index * 0.05, 4) if entity.is_sanctioned else round(0.86 - hit_index * 0.07, 4) if entity.is_pep else round(0.61 - hit_index * 0.04, 4)
            matched_name = entity.name if hit_index == 0 else f"{entity.name} Holdings"
            hit_id = str(uuid4())
            screening_results.append(
                (
                    hit_id,
                    entity_id,
                    entity.name,
                    matched_name,
                    match_score,
                    dataset,
                    f"{slugify(dataset)}-{screening_counter:04d}",
                    "name",
                    entity.country,
                    entity.entity_type,
                    jsonb(
                        {
                            "seed_batch": SEED_TAG,
                            "caption": f"Seeded screening hit from {dataset}",
                            "properties": {
                                "alias": [matched_name, entity.name],
                                "country": [entity.country],
                                "programId": ["AML-DEMO"],
                            },
                        }
                    ),
                    SEED_TAG,
                    SEED_TAG,
                    linked_txns[hit_index % len(linked_txns)]["id"] if linked_txns else None,
                    utc_now() - timedelta(days=hit_index + (screening_counter % 11)),
                )
            )
            screening_events.append(
                [
                    hit_id,
                    entity.name,
                    float(match_score),
                    dataset,
                    1,
                    SEED_TAG,
                    utc_now() - timedelta(days=hit_index + (screening_counter % 11)),
                ]
            )
        if screening_counter >= SCREENING_COUNT:
            break

    sars: list[tuple[Any, ...]] = []
    high_priority_cases = [case for case in cases if case["priority"] in {"high", "critical"}][:SAR_COUNT]
    for index, case in enumerate(high_priority_cases):
        status = "filed" if index < 8 else "approved" if index < 12 else "pending_review"
        drafted_at = case["created_at"] + timedelta(hours=8)
        filed_at = drafted_at + timedelta(days=2) if status == "filed" else None
        sar_id = str(uuid4())
        narrative = (
            f"Seed narrative for {case['case_ref']}. The investigation identified layered activity, "
            f"elevated transaction risk, and adverse counterparties linked to {case['title'].lower()}. "
            f"Analysts reviewed related alerts, documents, and screening hits before escalating the matter."
        )
        sars.append(
            (
                sar_id,
                f"SAR-SD-{index + 1:04d}",
                case["id"],
                status,
                entity_lookup[case["primary_entity_id"]].name if case.get("primary_entity_id") else account_lookup[case["primary_account_id"]].account_name,
                entity_lookup[case["primary_entity_id"]].entity_type if case.get("primary_entity_id") else "company",
                account_lookup[case["primary_account_id"]].account_number if case.get("primary_account_id") else None,
                narrative,
                "suspicious transfer activity",
                amount_decimal(145000 + index * 6800),
                case["created_at"] - timedelta(days=2),
                case["created_at"] + timedelta(days=1),
                "FinCEN",
                case["assigned_to"],
                drafted_at,
                case["assigned_to"] if status in {"approved", "filed"} else None,
                drafted_at + timedelta(hours=6) if status in {"approved", "filed"} else None,
                case["assigned_to"] if status == "filed" else None,
                drafted_at + timedelta(hours=12) if status == "filed" else None,
                filed_at,
                f"FCN-SD-{index + 1:06d}" if filed_at else None,
                True,
                settings.LLM_PRIMARY_MODEL,
                jsonb({"seed_batch": SEED_TAG, "seed_case_ref": case["case_ref"]}),
                drafted_at,
                utc_now(),
            )
        )
        case["sar_id"] = sar_id
        case["sar_required"] = True
        case["status"] = "sar_filed" if status == "filed" else "pending_sar"
        case_events.append(
            (
                str(uuid4()),
                case["id"],
                "sar_drafted",
                case["assigned_to"],
                "Seed SAR draft created",
                jsonb({"sar_id": sar_id}),
                drafted_at,
            )
        )
        if filed_at:
            case_events.append(
                (
                    str(uuid4()),
                    case["id"],
                    "sar_filed",
                    case["assigned_to"],
                    "Seed SAR filed",
                    jsonb({"sar_id": sar_id}),
                    filed_at,
                )
            )

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO entities (
                    id, name, name_normalized, entity_type, date_of_birth, nationality, country,
                    id_number, id_type, is_pep, is_sanctioned, sanctions_list,
                    risk_score, risk_level, metadata, created_at, updated_at
                ) VALUES (
                    $1, $2::varchar, lower($2::text), $3::entity_type, $4, $5, $6,
                    $7, $8, $9, $10, $11::varchar[],
                    $12, $13::risk_level, $14::jsonb, NOW(), NOW()
                )
                """,
                [
                    (
                        entity.id,
                        entity.name,
                        entity.entity_type,
                        entity.date_of_birth,
                        entity.nationality,
                        entity.country,
                        entity.id_number,
                        entity.id_type,
                        entity.is_pep,
                        entity.is_sanctioned,
                        entity.sanctions_list or None,
                        entity.risk_score,
                        entity.risk_level,
                        jsonb(entity.metadata),
                    )
                    for entity in entities
                ],
            )

            await conn.executemany(
                """
                INSERT INTO accounts (
                    id, account_number, account_name, account_type, currency, institution, country,
                    opened_at, risk_score, risk_level, is_monitored, is_blocked, metadata, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, 'USD', $5, $6,
                    $7, $8, $9::risk_level, TRUE, FALSE, $10::jsonb, NOW(), NOW()
                )
                """,
                [
                    (
                        account.id,
                        account.account_number,
                        account.account_name,
                        account.account_type,
                        account.institution,
                        account.country,
                        account.opened_at,
                        account.risk_score,
                        account.risk_level,
                        jsonb(account.metadata),
                    )
                    for account in accounts
                ],
            )

            await conn.executemany(
                """
                INSERT INTO account_entities (account_id, entity_id, role, since)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
                """,
                account_links,
            )

            await conn.executemany(
                """
                INSERT INTO transactions (
                    id, external_id, transaction_ref, transaction_type, status,
                    sender_account_id, sender_account_ref, sender_name, sender_country,
                    receiver_account_id, receiver_account_ref, receiver_name, receiver_country,
                    amount, currency, amount_usd, risk_score, risk_level, risk_factors,
                    ml_score_raw, ml_features, description, reference, channel, ip_address, device_id,
                    geo_lat, geo_lon, metadata, transacted_at, processed_at, created_at
                ) VALUES (
                    $1, $2, $3, $4::transaction_type, $5::transaction_status,
                    $6, $7, $8, $9,
                    $10, $11, $12, $13,
                    $14, $15, $16, $17, $18::risk_level, $19::text[],
                    $20, '{}'::jsonb, $21, $22, $23, $24, $25,
                    $26, $27, $28::jsonb, $29, $30, NOW()
                )
                """,
                [
                    (
                        txn["id"],
                        txn["external_id"],
                        txn["transaction_ref"],
                        txn["transaction_type"],
                        txn["status"],
                        txn["sender_account_id"],
                        txn["sender_account_ref"],
                        txn["sender_name"],
                        txn["sender_country"],
                        txn["receiver_account_id"],
                        txn["receiver_account_ref"],
                        txn["receiver_name"],
                        txn["receiver_country"],
                        txn["amount"],
                        txn["currency"],
                        txn["amount_usd"],
                        txn["risk_score"],
                        txn["risk_level"],
                        txn["risk_factors"],
                        txn["ml_score_raw"],
                        txn["description"],
                        txn["reference"],
                        txn["channel"],
                        txn["ip_address"],
                        txn["device_id"],
                        txn["geo_lat"],
                        txn["geo_lon"],
                        jsonb(txn["metadata"]),
                        txn["transacted_at"],
                        txn["processed_at"],
                    )
                    for txn in transactions
                ],
            )

            await conn.executemany(
                """
                INSERT INTO cases (
                    id, case_ref, title, description, status, priority, assigned_to, created_by,
                    closed_by, closed_at, primary_account_id, primary_entity_id, sar_required, sar_id,
                    ai_summary, ai_risk_factors, metadata, created_at, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5::case_status, $6::case_priority, $7, $8,
                    $9, $10, $11, $12, $13, $14,
                    $15, $16::text[], $17::jsonb, $18, $19
                )
                """,
                [
                    (
                        case["id"],
                        case["case_ref"],
                        case["title"],
                        case["description"],
                        case["status"],
                        case["priority"],
                        case["assigned_to"],
                        case["created_by"],
                        case["closed_by"],
                        case["closed_at"],
                        case["primary_account_id"],
                        case["primary_entity_id"],
                        case["sar_required"],
                        None,
                        case["ai_summary"],
                        case["ai_risk_factors"],
                        jsonb(case["metadata"]),
                        case["created_at"],
                        case["updated_at"],
                    )
                    for case in cases
                ],
            )

            await conn.executemany(
                """
                INSERT INTO alerts (
                    id, alert_ref, alert_type, status, severity, transaction_id, account_id, entity_id, case_id,
                    title, description, evidence, rule_id, ml_explanation, assigned_to, reviewed_by,
                    reviewed_at, closed_at, resolution_note, metadata, created_at, updated_at
                ) VALUES (
                    $1, $2, $3::alert_type, $4::alert_status, $5::risk_level, $6, $7, $8, $9,
                    $10, $11, $12::jsonb, $13, $14, $15, $16,
                    $17, $18, $19, $20::jsonb, $21, NOW()
                )
                """,
                [
                    (
                        alert["id"],
                        alert["alert_ref"],
                        alert["alert_type"],
                        alert["status"],
                        alert["severity"],
                        alert["transaction_id"],
                        alert["account_id"],
                        alert["entity_id"],
                        alert["case_id"],
                        alert["title"],
                        alert["description"],
                        jsonb(alert["evidence"]),
                        alert["rule_id"],
                        alert["ml_explanation"],
                        alert["assigned_to"],
                        alert["reviewed_by"],
                        alert["reviewed_at"],
                        alert["closed_at"],
                        alert["resolution_note"],
                        jsonb(alert["metadata"]),
                        alert["created_at"],
                    )
                    for alert in alert_specs
                ],
            )

            await conn.executemany(
                """
                INSERT INTO case_alerts (case_id, alert_id, added_at)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                case_alert_links,
            )

            await conn.executemany(
                """
                INSERT INTO case_transactions (case_id, transaction_id, added_at, note)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
                """,
                case_txn_links,
            )

            await conn.executemany(
                """
                INSERT INTO screening_results (
                    id, entity_id, entity_name, matched_name, match_score, dataset, dataset_id,
                    match_type, matched_country, matched_type, matched_detail, screened_by,
                    trigger, linked_txn_id, created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10::entity_type, $11::jsonb, $12,
                    $13, $14, $15
                )
                """,
                screening_results,
            )

            await conn.executemany(
                """
                INSERT INTO documents (
                    id, filename, file_type, file_size, storage_path, checksum, extracted_text,
                    ocr_applied, ocr_model, parse_applied, structured_data, pii_detected, pii_entities,
                    embedded, embedding_ids, case_id, entity_id, transaction_id, uploaded_by, metadata, created_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7,
                    $8, $9, $10, $11::jsonb, $12, $13::jsonb,
                    $14, $15::text[], $16, $17, $18, $19, $20::jsonb, NOW()
                )
                """,
                documents,
            )

            if sars:
                await conn.executemany(
                    """
                    INSERT INTO sar_reports (
                        id, sar_ref, case_id, status, subject_name, subject_type, subject_account,
                        narrative, activity_type, activity_amount, activity_from, activity_to, filing_agency,
                        drafted_by, drafted_at, reviewed_by, reviewed_at, approved_by, approved_at,
                        filed_at, filing_ref, ai_drafted, ai_model, metadata, created_at, updated_at
                    ) VALUES (
                        $1, $2, $3, $4::sar_status, $5, $6::entity_type, $7,
                        $8, $9, $10, $11, $12, $13,
                        $14, $15, $16, $17, $18, $19,
                        $20, $21, $22, $23, $24::jsonb, $25, $26
                    )
                    """,
                    sars,
                )
                for case in high_priority_cases:
                    await conn.execute(
                        """
                        UPDATE cases
                        SET sar_id = $2, sar_required = TRUE, status = $3::case_status, updated_at = NOW()
                        WHERE id = $1
                        """,
                        case["id"],
                        case["sar_id"],
                        case["status"],
                    )

            await conn.executemany(
                """
                INSERT INTO case_events (id, case_id, event_type, actor, detail, metadata, created_at)
                VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7)
                """,
                case_events,
            )

    client = get_ch_client()
    for batch in chunked(transactions, 250):
        client.insert(
            "transaction_events",
            [
                [
                    txn["id"],
                    txn["transaction_ref"],
                    txn["external_id"],
                    txn["sender_account_ref"],
                    txn["sender_country"],
                    txn["receiver_account_ref"],
                    txn["receiver_country"],
                    float(txn["amount"]),
                    txn["currency"],
                    float(txn["amount_usd"]),
                    txn["transaction_type"],
                    txn["channel"],
                    float(txn["risk_score"]),
                    txn["risk_level"],
                    txn["risk_factors"],
                    float(txn["ml_score_raw"]),
                    1 if float(txn["risk_score"]) >= 0.45 else 0,
                    1 if txn["external_id"].startswith(f"{SEED_PREFIX}_") and float(txn["risk_score"]) >= 0.7 else 0,
                    txn["transacted_at"],
                    txn["processed_at"],
                ]
                for txn in batch
            ],
            column_names=[
                "transaction_id",
                "transaction_ref",
                "external_id",
                "sender_account",
                "sender_country",
                "receiver_account",
                "receiver_country",
                "amount",
                "currency",
                "amount_usd",
                "transaction_type",
                "channel",
                "risk_score",
                "risk_level",
                "risk_factors",
                "ml_score_raw",
                "is_flagged",
                "is_alerted",
                "transacted_at",
                "processed_at",
            ],
        )

    for batch in chunked(alert_specs, 200):
        client.insert(
            "alert_events",
            [
                [
                    alert["id"],
                    alert["alert_ref"],
                    alert["alert_type"],
                    alert["severity"],
                    alert["status"],
                    alert["account_id"] or "",
                    alert["transaction_id"],
                    SEED_TAG,
                    alert["created_at"],
                    alert["closed_at"],
                ]
                for alert in batch
            ],
            column_names=[
                "alert_id",
                "alert_ref",
                "alert_type",
                "severity",
                "status",
                "account_id",
                "transaction_id",
                "rule_id",
                "created_at",
                "closed_at",
            ],
        )

    client.insert(
        "risk_score_history",
        [
            [
                txn["sender_account_ref"],
                float(txn["risk_score"]),
                txn["risk_level"],
                SEED_TAG,
                txn["transaction_ref"],
                txn["processed_at"],
            ]
            for txn in transactions
        ],
        column_names=["account_id", "risk_score", "risk_level", "trigger_type", "trigger_id", "scored_at"],
    )

    if screening_events:
        client.insert(
            "screening_events",
            screening_events,
            column_names=["screening_id", "entity_name", "match_score", "dataset", "match_found", "trigger", "screened_at"],
        )

    sync_result = await sync_graph_from_postgres(clear_existing=True)

    print("[seed] done")
    print(
        json.dumps(
            {
                "seed_batch": SEED_TAG,
                "accounts": len(accounts),
                "entities": len(entities),
                "transactions": len(transactions),
                "alerts": len(alert_specs),
                "cases": len(cases),
                "documents": len(documents),
                "screening_results": len(screening_results),
                "sars": len(sars),
                "graph_node_count": sync_result["node_count"],
                "graph_edge_count": sync_result["edge_count"],
            },
            indent=2,
        )
    )

    await close_graph_driver()
    await close_postgres()


if __name__ == "__main__":
    asyncio.run(main())
