"""
Document intelligence workflows for analysts.
"""

from __future__ import annotations

import asyncio
import base64
from datetime import datetime
import hashlib
import json
import re
from typing import Any
from uuid import uuid4

import httpx

from core.config import settings
from core.database import get_pool
from models.intelligence import DocumentAnalyzeRequest
from services.graph_sync import safe_resync_graph


PII_LABELS = [
    "person", "organization", "location", "email", "phone", "address",
    "date", "bank_account", "passport", "national_id", "financial_info",
]


async def list_documents(limit: int = 20) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, filename, file_type, case_id, entity_id, transaction_id,
                   ocr_applied, parse_applied, pii_detected, embedded,
                   uploaded_by, created_at
            FROM documents
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [_normalize_document_row(dict(row)) for row in rows]


async def get_document(document_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM documents WHERE id = $1", document_id)
    if row is None:
        return None
    return _normalize_document_row(dict(row))


async def attach_document_to_case(document_id: str, case_id: str, attached_by: str | None = None) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            case_exists = await conn.fetchval("SELECT 1 FROM cases WHERE id = $1", case_id)
            if not case_exists:
                return None

            current = await conn.fetchrow("SELECT * FROM documents WHERE id = $1", document_id)
            if not current:
                return None

            metadata = _normalize_document_row(dict(current)).get("metadata", {})
            previous_case_id = current["case_id"]
            metadata["attached_case_id"] = str(case_id)
            metadata["attached_at"] = datetime.utcnow().isoformat() + "Z"
            if attached_by:
                metadata["attached_by"] = attached_by

            row = await conn.fetchrow(
                """
                UPDATE documents
                SET case_id = $2, metadata = $3::jsonb
                WHERE id = $1
                RETURNING *
                """,
                document_id,
                case_id,
                json.dumps(metadata),
            )

            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, 'document_attached', $2, $3, $4)
                """,
                case_id,
                attached_by,
                f"Document attached: {current['filename']}",
                json.dumps(
                    {
                        "document_id": document_id,
                        "filename": current["filename"],
                        "previous_case_id": str(previous_case_id) if previous_case_id else None,
                    }
                ),
            )

    if row:
        await safe_resync_graph(clear_existing=True)
    return _normalize_document_row(dict(row)) if row else None


async def analyze_document(payload: DocumentAnalyzeRequest) -> tuple[dict[str, Any], str, str, list[str]]:
    extracted_text = (payload.text or "").strip()
    ocr_applied = False
    ocr_model = None
    ocr_summary = ""
    file_bytes = _decode_base64_bytes(payload.file_base64) or _decode_base64_bytes(payload.image_base64)
    mime_type = payload.mime_type or payload.file_type or "application/octet-stream"

    if not extracted_text and (payload.image_base64 or (file_bytes and mime_type.startswith("image/"))):
        try:
            ocr_payload = payload.image_base64 or payload.file_base64
            ocr = await _run_ocr(ocr_payload, mime_type)
            extracted_text = ocr.get("text", "").strip()
            ocr_applied = bool(extracted_text)
            ocr_model = ocr.get("mode") == "cuda" and "nemotron-ocr-v2-cuda" or "nemotron-ocr-v2"
            ocr_summary = "OCR completed"
        except Exception as exc:
            ocr_summary = f"OCR unavailable: {exc}"

    if not extracted_text and file_bytes:
        extracted_text = await _extract_text_from_file_bytes(file_bytes, mime_type, payload.filename, payload.file_type)

    if not extracted_text:
        raise ValueError("Provide document text, an image for OCR, or an uploadable file.")

    structured_data = await _extract_structure(extracted_text, payload.filename, payload.file_type)
    pii_entities = await _extract_pii(extracted_text)
    pii_detected = bool(pii_entities.get("entities"))
    embedding_ids, vector_status = await _store_embedding(payload, extracted_text)
    graph_candidates = _graph_candidates(structured_data, pii_entities, extracted_text)
    metadata = dict(payload.metadata)
    metadata["analysis_timestamp"] = datetime.utcnow().isoformat() + "Z"
    if ocr_summary:
        metadata["ocr_status"] = ocr_summary
    storage_path, file_size, checksum, storage_status = await _store_raw_document(payload, file_bytes, extracted_text)
    metadata["storage_status"] = storage_status
    summary = _build_summary(structured_data, pii_entities, vector_status)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO documents (
                filename, file_type, file_size, storage_path, checksum,
                extracted_text, ocr_applied, ocr_model, parse_applied,
                structured_data, pii_detected, pii_entities, embedded,
                embedding_ids, case_id, entity_id, transaction_id,
                uploaded_by, metadata
            ) VALUES (
                $1, $2, $3, $4, $5,
                $6, $7, $8, $9,
                $10::jsonb, $11, $12::jsonb, $13,
                $14::text[], $15, $16, $17,
                $18, $19::jsonb
            )
            RETURNING *
            """,
            payload.filename,
            payload.file_type,
            file_size,
            storage_path,
            checksum,
            extracted_text,
            ocr_applied,
            ocr_model,
            bool(structured_data),
            json.dumps(structured_data),
            pii_detected,
            json.dumps(pii_entities),
            bool(embedding_ids),
            embedding_ids or None,
            payload.case_id,
            payload.entity_id,
            payload.transaction_id,
            payload.uploaded_by,
            json.dumps(metadata),
        )
        if payload.case_id:
            await conn.execute(
                """
                INSERT INTO case_events (case_id, event_type, actor, detail, metadata)
                VALUES ($1, 'document_uploaded', $2, $3, $4)
                """,
                payload.case_id,
                payload.uploaded_by,
                f"Document uploaded: {payload.filename}",
                json.dumps({"document_id": str(row["id"]), "filename": payload.filename}),
            )
    await safe_resync_graph(clear_existing=True)
    return _normalize_document_row(dict(row)), summary, vector_status, graph_candidates


def _decode_base64_bytes(value: str | None) -> bytes | None:
    if not value:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except Exception:
        try:
            return base64.b64decode(value)
        except Exception:
            return None


async def _extract_text_from_file_bytes(file_bytes: bytes, mime_type: str, filename: str, file_type: str | None) -> str:
    if _looks_textual(mime_type, filename, file_type):
        for encoding in ("utf-8", "utf-8-sig", "latin-1"):
            try:
                return file_bytes.decode(encoding).strip()
            except Exception:
                continue
    return await _extract_text_with_tika(file_bytes, mime_type)


def _looks_textual(mime_type: str, filename: str, file_type: str | None) -> bool:
    lowered = (mime_type or "").lower()
    suffix = str(filename or "").lower()
    file_type_value = str(file_type or "").lower()
    if lowered.startswith("text/"):
        return True
    if lowered in {"application/json", "application/xml", "text/csv"}:
        return True
    return suffix.endswith((".txt", ".csv", ".json", ".md", ".log", ".xml")) or file_type_value in {"txt", "csv", "json", "md", "xml"}


async def _extract_text_with_tika(file_bytes: bytes, mime_type: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.put(
                f"{settings.TIKA_URL.rstrip('/')}/tika",
                content=file_bytes,
                headers={"Accept": "text/plain", "Content-Type": mime_type or "application/octet-stream"},
            )
            resp.raise_for_status()
            return resp.text.strip()
    except Exception:
        return ""


async def _store_raw_document(payload: DocumentAnalyzeRequest, file_bytes: bytes | None, extracted_text: str) -> tuple[str | None, int, str, str]:
    raw_bytes = file_bytes or extracted_text.encode("utf-8")
    checksum = hashlib.sha256(raw_bytes).hexdigest()
    file_size = len(raw_bytes)

    try:
        storage_path = await asyncio.to_thread(_store_in_minio_sync, payload.filename, payload.mime_type, raw_bytes)
        return storage_path, file_size, checksum, "stored_in_minio"
    except Exception:
        return None, file_size, checksum, "storage_unavailable"


def _store_in_minio_sync(filename: str, mime_type: str | None, raw_bytes: bytes) -> str:
    import boto3
    from botocore.config import Config

    bucket = settings.MINIO_BUCKET
    key = _build_storage_key(filename)
    client = boto3.client(
        "s3",
        endpoint_url=settings.MINIO_ENDPOINT,
        aws_access_key_id=settings.MINIO_ACCESS_KEY,
        aws_secret_access_key=settings.MINIO_SECRET_KEY,
        region_name="us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        verify=False,
    )

    existing = {item["Name"] for item in client.list_buckets().get("Buckets", [])}
    if bucket not in existing:
        client.create_bucket(Bucket=bucket)

    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=raw_bytes,
        ContentType=mime_type or "application/octet-stream",
    )
    return f"s3://{bucket}/{key}"


def _build_storage_key(filename: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "-", filename).strip("-") or "document.bin"
    timestamp = datetime.utcnow().strftime("%Y/%m/%d")
    return f"documents/{timestamp}/{uuid4().hex[:12]}-{sanitized}"


async def _run_ocr(image_base64: str, mime_type: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{settings.OCR_URL.rstrip('/')}/extract",
            json={"image_base64": image_base64, "mime_type": mime_type, "output_format": "text"},
        )
        resp.raise_for_status()
        return resp.json()


async def _extract_structure(text: str, filename: str, file_type: str | None) -> dict[str, Any]:
    prompt = (
        "Extract structured AML-relevant data from the following document and return compact JSON with keys: "
        "summary, parties, accounts, amounts, dates, locations, suspicious_indicators. "
        "Do not include markdown fences.\n\n"
        f"Filename: {filename}\n"
        f"Type: {file_type or 'unknown'}\n"
        f"Document:\n{text[:6000]}"
    )
    body = {
        "model": settings.LLM_FAST_URL and "qwen3-8b-instruct" or "qwen3-8b-instruct",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(f"{settings.LLM_FAST_URL.rstrip('/')}/chat/completions", json=body)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json_block(content) or _heuristic_structure(text)
    except Exception:
        return _heuristic_structure(text)


async def _extract_pii(text: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.post(
                f"{settings.PII_URL.rstrip('/')}/extract",
                json={"text": text[:4000], "entities": PII_LABELS, "threshold": 0.45},
            )
            resp.raise_for_status()
            data = resp.json()
            return {"entities": data.get("entities", [])}
    except Exception:
        return {"entities": _regex_pii(text)}


async def _store_embedding(payload: DocumentAnalyzeRequest, text: str) -> tuple[list[str], str]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{settings.EMBED_URL.rstrip('/')}/embeddings",
                json={"model": "llama-nemotron-embed-1b-v2", "input": text[:8000]},
            )
            resp.raise_for_status()
            data = resp.json()
        vector = data["data"][0]["embedding"]
        vector_id = str(uuid4())
        stored = await _store_in_milvus(vector_id, payload.filename, text[:4000], vector)
        if stored:
            return [vector_id], "embedded_in_milvus"
        return [vector_id], "embedded_no_vector_store"
    except Exception:
        return [], "embedding_unavailable"


async def _store_in_milvus(vector_id: str, filename: str, text: str, vector: list[float]) -> bool:
    try:
        from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, utility

        connections.connect(alias="default", host=settings.MILVUS_HOST, port=str(settings.MILVUS_PORT))
        collection_name = "document_chunks"
        if not utility.has_collection(collection_name):
            schema = CollectionSchema(
                fields=[
                    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, auto_id=False, max_length=64),
                    FieldSchema(name="document_label", dtype=DataType.VARCHAR, max_length=512),
                    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
                    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=len(vector)),
                ],
                description="goAML document chunk embeddings",
            )
            collection = Collection(name=collection_name, schema=schema)
            collection.create_index("embedding", {"index_type": "AUTOINDEX", "metric_type": "COSINE"})
        else:
            collection = Collection(collection_name)
        collection.insert([[vector_id], [filename], [text], [vector]])
        collection.flush()
        return True
    except Exception:
        return False


def _heuristic_structure(text: str) -> dict[str, Any]:
    amounts = re.findall(r"(?:USD|\$)\s?[\d,]+(?:\.\d+)?", text, re.IGNORECASE)
    dates = re.findall(r"\b20\d{2}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/20\d{2}\b", text)
    accounts = re.findall(r"\bACC-[A-Z0-9-]+\b|\b[A-Z]{2,5}-\d{3,}\b", text)
    parties = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b", text)
    locations = re.findall(r"\b(?:Havana|Dubai|London|Dhaka|Dubai|Cuba|UAE|Bangladesh|Pakistan|Nigeria)\b", text, re.IGNORECASE)
    return {
        "summary": text[:280],
        "parties": list(dict.fromkeys(parties[:8])),
        "accounts": list(dict.fromkeys(accounts[:8])),
        "amounts": list(dict.fromkeys(amounts[:8])),
        "dates": list(dict.fromkeys(dates[:8])),
        "locations": list(dict.fromkeys(locations[:8])),
        "suspicious_indicators": _suspicious_indicators(text),
    }


def _suspicious_indicators(text: str) -> list[str]:
    indicators: list[str] = []
    lowered = text.lower()
    if "cash" in lowered:
        indicators.append("cash activity")
    if "wire" in lowered:
        indicators.append("wire transfer")
    if "dubai" in lowered or "havana" in lowered:
        indicators.append("cross-border geography")
    if "sanction" in lowered or "ofac" in lowered:
        indicators.append("sanctions relevance")
    if "structur" in lowered:
        indicators.append("possible structuring")
    return indicators


def _parse_json_block(content: str | None) -> dict[str, Any] | None:
    if not content:
        return None
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.replace("json", "", 1).strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None
    return None


def _regex_pii(text: str) -> list[dict[str, Any]]:
    patterns = [
        ("email", r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE),
        ("passport", r"\b[P]\d{6,9}\b", 0),
        ("bank_account", r"\bACC-[A-Z0-9-]+\b", re.IGNORECASE),
        ("date", r"\b20\d{2}-\d{2}-\d{2}\b", 0),
    ]
    entities: list[dict[str, Any]] = []
    for label, pattern, flags in patterns:
        for match in re.finditer(pattern, text, flags):
            entities.append(
                {
                    "text": match.group(0),
                    "label": label,
                    "start": match.start(),
                    "end": match.end(),
                    "score": 0.7,
                }
            )
    return entities


def _graph_candidates(structured_data: dict[str, Any], pii_entities: dict[str, Any], text: str) -> list[str]:
    values: list[str] = []
    for key in ("parties", "accounts", "locations"):
        for item in structured_data.get(key, [])[:5]:
            if item:
                values.append(str(item))
    for entity in pii_entities.get("entities", [])[:5]:
        label = entity.get("text")
        if label:
            values.append(str(label))
    if not values:
        values.extend(re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}\b", text)[:5])
    return list(dict.fromkeys(values))[:8]


def _build_summary(structured_data: dict[str, Any], pii_entities: dict[str, Any], vector_status: str) -> str:
    parts = []
    if structured_data.get("summary"):
        parts.append(str(structured_data["summary"]))
    if structured_data.get("suspicious_indicators"):
        parts.append(f"Indicators: {', '.join(structured_data['suspicious_indicators'][:4])}.")
    if pii_entities.get("entities"):
        parts.append(f"PII/entities detected: {len(pii_entities['entities'])}.")
    parts.append(f"Vector status: {vector_status}.")
    return " ".join(parts).strip()


def _normalize_document_row(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("structured_data", "pii_entities", "metadata"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                row[key] = json.loads(value)
            except Exception:
                row[key] = {}
        elif value is None:
            row[key] = {}
    if row.get("embedding_ids") is None:
        row["embedding_ids"] = []
    return row
