"""
goAML-V2 models for graph exploration and document intelligence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class GraphExploreRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=255)
    hops: int = Field(2, ge=1, le=4)
    limit: int = Field(30, ge=1, le=100)


class GraphSyncRequest(BaseModel):
    clear_existing: bool = True


class GraphNode(BaseModel):
    id: str
    label: str
    node_type: str
    risk_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphExploreResponse(BaseModel):
    query: str
    node_count: int
    edge_count: int
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class GraphSyncResponse(BaseModel):
    status: str
    clear_existing: bool
    node_count: int
    edge_count: int
    table_counts: dict[str, int] = Field(default_factory=dict)
    synced_at: datetime


class GraphDrilldownRequest(BaseModel):
    node_id: str = Field(..., min_length=3, max_length=255)
    hops: int = Field(1, ge=1, le=3)
    limit: int = Field(25, ge=1, le=100)


class GraphRelationshipEvidenceItem(BaseModel):
    source_id: str
    source_label: str
    source_type: str
    target_id: str
    target_label: str
    target_type: str
    label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphDrilldownResponse(BaseModel):
    focus_node: GraphNode | None = None
    node_count: int
    edge_count: int
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    relationship_evidence: list[GraphRelationshipEvidenceItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class GraphPathItem(BaseModel):
    hops: int
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)


class GraphPathfindRequest(BaseModel):
    source_node_id: str = Field(..., min_length=3, max_length=255)
    target_node_id: str | None = None
    target_query: str | None = Field(None, min_length=2, max_length=255)
    max_hops: int = Field(4, ge=1, le=5)
    limit: int = Field(5, ge=1, le=20)


class GraphPathfindResponse(BaseModel):
    source_node_id: str
    target_query: str | None = None
    target_node_id: str | None = None
    path_count: int
    paths: list[GraphPathItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class EntityListItem(BaseModel):
    id: UUID
    name: str
    entity_type: str
    country: str | None = None
    nationality: str | None = None
    is_pep: bool = False
    is_sanctioned: bool = False
    risk_score: float | None = None
    risk_level: str | None = None
    resolution_status: str | None = None
    created_at: datetime | None = None


class EntityRelatedAccountItem(BaseModel):
    account_id: UUID
    account_number: str | None = None
    account_name: str | None = None
    role: str | None = None
    risk_score: float | None = None
    risk_level: str | None = None
    country: str | None = None


class EntityRelatedCaseItem(BaseModel):
    case_id: UUID
    case_ref: str
    title: str
    status: str
    priority: str
    assigned_to: str | None = None
    created_at: datetime | None = None


class EntityDocumentItem(BaseModel):
    document_id: UUID
    filename: str
    file_type: str | None = None
    uploaded_by: str | None = None
    pii_detected: bool = False
    parse_applied: bool = False
    embedded: bool = False
    created_at: datetime | None = None


class EntityScreeningHitItem(BaseModel):
    screening_id: UUID
    entity_name: str
    matched_name: str | None = None
    dataset: str | None = None
    match_type: str | None = None
    match_score: float | None = None
    matched_country: str | None = None
    created_at: datetime | None = None


class EntityResolutionCandidateItem(BaseModel):
    entity_id: UUID
    name: str
    entity_type: str
    country: str | None = None
    risk_level: str | None = None
    risk_score: float | None = None
    similarity: float | None = None
    linked_account_count: int = 0
    linked_case_count: int = 0
    linked_document_count: int = 0
    screening_hit_count: int = 0
    alert_count: int = 0


class EntityResolutionHistoryItem(BaseModel):
    action: str
    actor: str | None = None
    note: str | None = None
    candidate_entity_id: UUID | None = None
    candidate_name: str | None = None
    created_at: datetime
    resolution_status: str | None = None


class EntityWatchlistState(BaseModel):
    status: str | None = None
    source: str | None = None
    reason: str | None = None
    added_by: str | None = None
    added_at: datetime | None = None
    removed_by: str | None = None
    removed_at: datetime | None = None
    case_id: UUID | None = None
    case_ref: str | None = None


class EntityMergeState(BaseModel):
    merged_into_entity_id: UUID | None = None
    merged_into_name: str | None = None
    merged_by: str | None = None
    merged_at: datetime | None = None


class EntityProfileResponse(BaseModel):
    id: UUID
    name: str
    entity_type: str
    date_of_birth: str | None = None
    nationality: str | None = None
    country: str | None = None
    id_number: str | None = None
    id_type: str | None = None
    is_pep: bool = False
    is_sanctioned: bool = False
    sanctions_list: list[str] = Field(default_factory=list)
    risk_score: float | None = None
    risk_level: str | None = None
    embedding_id: str | None = None
    resolution_status: str | None = None
    aliases: list[str] = Field(default_factory=list)
    watchlist_state: EntityWatchlistState | None = None
    merge_state: EntityMergeState | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    related_accounts: list[EntityRelatedAccountItem] = Field(default_factory=list)
    related_cases: list[EntityRelatedCaseItem] = Field(default_factory=list)
    screening_hits: list[EntityScreeningHitItem] = Field(default_factory=list)
    documents: list[EntityDocumentItem] = Field(default_factory=list)
    resolution_candidates: list[EntityResolutionCandidateItem] = Field(default_factory=list)
    resolution_history: list[EntityResolutionHistoryItem] = Field(default_factory=list)
    graph: GraphDrilldownResponse | None = None


class EntityResolutionRequest(BaseModel):
    action: str = Field(..., min_length=3, max_length=64)
    actor: str | None = None
    note: str | None = None
    candidate_entity_id: UUID | None = None


class WatchlistDashboardCounts(BaseModel):
    active: int = 0
    removed: int = 0
    with_open_case: int = 0
    critical: int = 0
    total: int = 0


class WatchlistDashboardItem(BaseModel):
    id: UUID
    name: str
    entity_type: str
    country: str | None = None
    risk_score: float | None = None
    risk_level: str | None = None
    is_pep: bool = False
    is_sanctioned: bool = False
    resolution_status: str | None = None
    watchlist_status: str | None = None
    watchlist_source: str | None = None
    watchlist_reason: str | None = None
    watchlist_added_by: str | None = None
    watchlist_added_at: datetime | None = None
    case_id: UUID | None = None
    case_ref: str | None = None
    linked_case_count: int = 0
    linked_account_count: int = 0
    linked_document_count: int = 0
    screening_hit_count: int = 0
    alert_count: int = 0


class WatchlistDashboardResponse(BaseModel):
    status: str
    counts: WatchlistDashboardCounts
    items: list[WatchlistDashboardItem] = Field(default_factory=list)


class DocumentAnalyzeRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=512)
    file_type: str | None = None
    text: str | None = None
    file_base64: str | None = None
    image_base64: str | None = None
    mime_type: str | None = "image/png"
    uploaded_by: str | None = None
    case_id: UUID | None = None
    entity_id: UUID | None = None
    transaction_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentListItem(BaseModel):
    id: UUID
    filename: str
    file_type: str | None = None
    case_id: UUID | None = None
    entity_id: UUID | None = None
    transaction_id: UUID | None = None
    ocr_applied: bool
    parse_applied: bool
    pii_detected: bool
    embedded: bool
    uploaded_by: str | None = None
    created_at: datetime


class DocumentDetail(DocumentListItem):
    file_size: int | None = None
    storage_path: str | None = None
    extracted_text: str | None = None
    ocr_model: str | None = None
    structured_data: dict[str, Any] = Field(default_factory=dict)
    pii_entities: dict[str, Any] = Field(default_factory=dict)
    embedding_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentAnalyzeResponse(BaseModel):
    document: DocumentDetail
    summary: str
    vector_status: str
    graph_candidates: list[str] = Field(default_factory=list)


class DocumentAttachRequest(BaseModel):
    attached_by: str | None = None


class CaseContextAlertItem(BaseModel):
    id: UUID
    alert_ref: str
    title: str
    severity: str | None = None
    status: str | None = None
    description: str | None = None
    created_at: datetime | None = None


class CaseContextTransactionItem(BaseModel):
    id: UUID
    transaction_ref: str
    amount_usd: float | None = None
    risk_score: float | None = None
    status: str | None = None
    sender_name: str | None = None
    receiver_name: str | None = None
    transacted_at: datetime | None = None


class CaseContextScreeningHitItem(BaseModel):
    id: UUID
    entity_name: str
    matched_name: str | None = None
    match_score: float | None = None
    dataset: str | None = None
    match_type: str | None = None
    matched_country: str | None = None
    linked_txn_id: UUID | None = None
    matched_detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class CaseContextDocumentItem(BaseModel):
    document_id: UUID | None = None
    filename: str
    source: str
    snippet: str | None = None
    created_at: datetime | None = None
    case_id: UUID | None = None
    entity_id: UUID | None = None
    transaction_id: UUID | None = None
    ocr_applied: bool | None = None
    parse_applied: bool | None = None
    pii_detected: bool | None = None
    embedded: bool | None = None
    retrieval_score: float | None = None
    rerank_score: float | None = None
    embedding_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CaseContextResponse(BaseModel):
    case_id: UUID
    query: str
    focus_queries: list[str] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)
    alerts: list[CaseContextAlertItem] = Field(default_factory=list)
    transactions: list[CaseContextTransactionItem] = Field(default_factory=list)
    screening_hits: list[CaseContextScreeningHitItem] = Field(default_factory=list)
    direct_documents: list[CaseContextDocumentItem] = Field(default_factory=list)
    related_documents: list[CaseContextDocumentItem] = Field(default_factory=list)
    graph: GraphExploreResponse | None = None


class CaseSummaryRequest(BaseModel):
    generated_by: str | None = None
    persist: bool = True
    document_limit: int = Field(4, ge=1, le=12)
    related_limit: int = Field(6, ge=1, le=15)


class CaseSummaryResponse(BaseModel):
    case_id: UUID
    summary: str
    risk_factors: list[str] = Field(default_factory=list)
    model: str | None = None
    ai_generated: bool = False
    persisted: bool = True
    focus_queries: list[str] = Field(default_factory=list)
    context_summary: list[str] = Field(default_factory=list)
