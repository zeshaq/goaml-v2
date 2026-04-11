"""
Document intelligence API endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from models.intelligence import (
    DocumentAttachRequest,
    DocumentAnalyzeRequest,
    DocumentAnalyzeResponse,
    DocumentDetail,
    DocumentIntelligenceResponse,
    DocumentListItem,
)
from services.auth import AuthenticatedUser, require_permissions, resolve_request_actor
from services.documents import analyze_document, attach_document_to_case, get_document, list_documents
from services.maturity_features import get_document_intelligence

router = APIRouter()


@router.get("/documents", response_model=list[DocumentListItem], summary="List analyzed documents")
async def get_documents(
    limit: int = 20,
    current_user: AuthenticatedUser = Depends(require_permissions("view_documents")),
):
    return [DocumentListItem(**row) for row in await list_documents(limit)]


@router.get("/documents/{document_id}", response_model=DocumentDetail, summary="Get document detail")
async def get_document_detail(
    document_id: str,
    current_user: AuthenticatedUser = Depends(require_permissions("view_documents")),
):
    row = await get_document(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetail(**row)


@router.get("/documents/{document_id}/intelligence", response_model=DocumentIntelligenceResponse, summary="Get duplicate detection, provenance, and filing-pack intelligence for a document")
async def get_document_intelligence_detail(
    document_id: UUID,
    current_user: AuthenticatedUser = Depends(require_permissions("view_documents")),
):
    row = await get_document_intelligence(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentIntelligenceResponse(**row)


@router.post("/documents/analyze", response_model=DocumentAnalyzeResponse, summary="Analyze AML document")
async def post_document_analyze(
    payload: DocumentAnalyzeRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("analyze_documents")),
):
    try:
        row, summary, vector_status, graph_candidates = await analyze_document(
            payload.model_copy(update={"uploaded_by": resolve_request_actor(requested_actor=payload.uploaded_by, current_user=current_user)})
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentAnalyzeResponse(
        document=DocumentDetail(**row),
        summary=summary,
        vector_status=vector_status,
        graph_candidates=graph_candidates,
    )


@router.post("/cases/{case_id}/documents/analyze", response_model=DocumentAnalyzeResponse, summary="Analyze and attach document to case")
async def post_case_document_analyze(
    case_id: str,
    payload: DocumentAnalyzeRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("analyze_documents")),
):
    try:
        case_payload = payload.model_copy(
            update={
                "case_id": case_id,
                "uploaded_by": resolve_request_actor(requested_actor=payload.uploaded_by, current_user=current_user),
            }
        )
        row, summary, vector_status, graph_candidates = await analyze_document(case_payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentAnalyzeResponse(
        document=DocumentDetail(**row),
        summary=summary,
        vector_status=vector_status,
        graph_candidates=graph_candidates,
    )


@router.post("/cases/{case_id}/documents/{document_id}/attach", response_model=DocumentDetail, summary="Attach existing document to case")
async def post_attach_document_to_case(
    case_id: str,
    document_id: str,
    payload: DocumentAttachRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    row = await attach_document_to_case(
        document_id=document_id,
        case_id=case_id,
        attached_by=resolve_request_actor(requested_actor=payload.attached_by, current_user=current_user),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case or document not found")
    return DocumentDetail(**row)
