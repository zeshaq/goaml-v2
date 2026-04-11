"""
goAML-V2 case API endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from models.casework import (
    CaseCreate,
    CaseDetail,
    CaseEventItem,
    CaseListItem,
    CaseNoteCreate,
    CaseNoteItem,
    CaseTaskCreate,
    CaseTaskItem,
    CaseTaskUpdate,
    CaseUpdate,
    SarDraftRequest,
    SarFileRequest,
    SarRebalanceRequest,
    SarRebalanceResponse,
    SarReportDetail,
    SarQueueResponse,
    SarWorkflowRequest,
)
from models.intelligence import CaseContextResponse, CaseSummaryRequest, CaseSummaryResponse
from services.case_context import get_case_context
from services.case_summary import generate_case_summary
from services.cases import (
    add_case_note,
    add_case_task,
    advance_sar_workflow,
    create_case,
    draft_sar,
    file_sar,
    get_case_detail,
    get_case_sar,
    rebalance_sar_queue,
    list_sar_queue,
    list_case_events,
    list_case_notes,
    list_case_tasks,
    list_cases,
    update_case,
    update_case_task,
)

router = APIRouter()


@router.get("/sars/queue", response_model=SarQueueResponse, summary="Get first-class SAR review and approval queues")
async def get_sar_queue(
    queue: str = Query("review", pattern="^(draft|review|approval|filed|all)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    try:
        row = await list_sar_queue(queue=queue, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SarQueueResponse(**row)


@router.post("/sars/queue/rebalance", response_model=SarRebalanceResponse, summary="Automatically rebalance SAR queue workload across analysts")
async def post_sar_queue_rebalance(payload: SarRebalanceRequest):
    try:
        row = await rebalance_sar_queue(
            actor=payload.actor,
            queue=payload.queue,
            limit=payload.limit,
            analyst_pool=payload.analyst_pool,
            breached_only=payload.breached_only,
            include_due_soon=payload.include_due_soon,
            max_items_per_owner=payload.max_items_per_owner,
            min_workload_gap=payload.min_workload_gap,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SarRebalanceResponse(**row)


@router.post("/cases", response_model=CaseDetail, status_code=status.HTTP_201_CREATED, summary="Create case")
async def post_case(payload: CaseCreate):
    row = await create_case(payload)
    return CaseDetail(**row)


@router.get("/cases", response_model=list[CaseListItem], summary="List cases")
async def get_cases(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
):
    rows = await list_cases(limit=limit, offset=offset, status=status)
    return [CaseListItem(**row) for row in rows]


@router.get("/cases/{case_id}", response_model=CaseDetail, summary="Get case detail")
async def get_case(case_id: UUID):
    row = await get_case_detail(case_id)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseDetail(**row)


@router.get("/cases/{case_id}/events", response_model=list[CaseEventItem], summary="Get case investigation timeline")
async def get_case_events(
    case_id: UUID,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    order: str = Query("asc", pattern="^(asc|desc)$"),
):
    rows = await list_case_events(case_id=case_id, limit=limit, offset=offset, order=order)
    if rows is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return [CaseEventItem(**row) for row in rows]


@router.get("/cases/{case_id}/context", response_model=CaseContextResponse, summary="Get investigation context for case")
async def get_case_investigation_context(
    case_id: UUID,
    document_limit: int = Query(4, ge=1, le=12),
    related_limit: int = Query(6, ge=1, le=15),
):
    row = await get_case_context(case_id=case_id, document_limit=document_limit, related_limit=related_limit)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseContextResponse(**row)


@router.post("/cases/{case_id}/summary", response_model=CaseSummaryResponse, summary="Generate AI case summary")
async def post_case_summary(case_id: UUID, payload: CaseSummaryRequest):
    row = await generate_case_summary(
        case_id=case_id,
        generated_by=payload.generated_by,
        persist=payload.persist,
        document_limit=payload.document_limit,
        related_limit=payload.related_limit,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseSummaryResponse(**row)


@router.get("/cases/{case_id}/sar", response_model=SarReportDetail | None, summary="Get case SAR detail")
async def get_case_sar_detail(case_id: UUID):
    row = await get_case_sar(case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if row == {}:
        return None
    return SarReportDetail(**row)


@router.patch("/cases/{case_id}", response_model=CaseDetail, summary="Update case")
async def patch_case(case_id: UUID, payload: CaseUpdate):
    row = await update_case(case_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseDetail(**row)


@router.get("/cases/{case_id}/tasks", response_model=list[CaseTaskItem], summary="List collaboration tasks for a case")
async def get_case_tasks(case_id: UUID):
    rows = await list_case_tasks(case_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return [CaseTaskItem(**row) for row in rows]


@router.post("/cases/{case_id}/tasks", response_model=CaseTaskItem, status_code=status.HTTP_201_CREATED, summary="Create a collaboration task for a case")
async def post_case_task(case_id: UUID, payload: CaseTaskCreate):
    row = await add_case_task(case_id, payload)
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseTaskItem(**row)


@router.patch("/cases/{case_id}/tasks/{task_id}", response_model=CaseTaskItem, summary="Update a collaboration task for a case")
async def patch_case_task(case_id: UUID, task_id: UUID, payload: CaseTaskUpdate):
    row = await update_case_task(case_id, task_id, payload)
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if row == {}:
        raise HTTPException(status_code=404, detail="Task not found")
    return CaseTaskItem(**row)


@router.get("/cases/{case_id}/notes", response_model=list[CaseNoteItem], summary="List analyst notes for a case")
async def get_case_notes(case_id: UUID):
    rows = await list_case_notes(case_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return [CaseNoteItem(**row) for row in rows]


@router.post("/cases/{case_id}/notes", response_model=CaseNoteItem, status_code=status.HTTP_201_CREATED, summary="Add an analyst note to a case")
async def post_case_note(case_id: UUID, payload: CaseNoteCreate):
    row = await add_case_note(case_id, payload)
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseNoteItem(**row)


@router.post("/cases/{case_id}/sar", response_model=SarReportDetail, summary="Draft SAR report for case")
async def post_case_sar(case_id: UUID, payload: SarDraftRequest):
    row = await draft_sar(case_id, payload)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return SarReportDetail(**row)


@router.post("/cases/{case_id}/sar/review", response_model=SarReportDetail, summary="Advance SAR review or approval workflow")
async def post_case_sar_review(case_id: UUID, payload: SarWorkflowRequest):
    try:
        row = await advance_sar_workflow(case_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Case or SAR not found")
    return SarReportDetail(**row)


@router.post("/cases/{case_id}/sar/file", response_model=SarReportDetail, summary="File SAR report for case")
async def post_case_sar_file(case_id: UUID, payload: SarFileRequest):
    try:
        row = await file_sar(case_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Case or SAR not found")
    return SarReportDetail(**row)
