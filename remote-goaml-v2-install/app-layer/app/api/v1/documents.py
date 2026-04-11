"""
Document intelligence API endpoints.
"""

from fastapi import APIRouter, HTTPException

from models.intelligence import (
    DocumentAttachRequest,
    DocumentAnalyzeRequest,
    DocumentAnalyzeResponse,
    DocumentDetail,
    DocumentListItem,
)
from services.documents import analyze_document, attach_document_to_case, get_document, list_documents

router = APIRouter()


@router.get("/documents", response_model=list[DocumentListItem], summary="List analyzed documents")
async def get_documents(limit: int = 20):
    return [DocumentListItem(**row) for row in await list_documents(limit)]


@router.get("/documents/{document_id}", response_model=DocumentDetail, summary="Get document detail")
async def get_document_detail(document_id: str):
    row = await get_document(document_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetail(**row)


@router.post("/documents/analyze", response_model=DocumentAnalyzeResponse, summary="Analyze AML document")
async def post_document_analyze(payload: DocumentAnalyzeRequest):
    try:
        row, summary, vector_status, graph_candidates = await analyze_document(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DocumentAnalyzeResponse(
        document=DocumentDetail(**row),
        summary=summary,
        vector_status=vector_status,
        graph_candidates=graph_candidates,
    )


@router.post("/cases/{case_id}/documents/analyze", response_model=DocumentAnalyzeResponse, summary="Analyze and attach document to case")
async def post_case_document_analyze(case_id: str, payload: DocumentAnalyzeRequest):
    try:
        case_payload = payload.model_copy(update={"case_id": case_id})
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
async def post_attach_document_to_case(case_id: str, document_id: str, payload: DocumentAttachRequest):
    row = await attach_document_to_case(document_id=document_id, case_id=case_id, attached_by=payload.attached_by)
    if row is None:
        raise HTTPException(status_code=404, detail="Case or document not found")
    return DocumentDetail(**row)
