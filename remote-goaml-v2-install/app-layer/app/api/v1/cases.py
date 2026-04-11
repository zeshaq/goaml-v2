"""
goAML-V2 case API endpoints.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from models.analyst_ops import (
    BulkActionPreviewResponse,
    BulkSarActionRequest,
    BulkSarActionResponse,
    DecisionFeedbackCreateRequest,
    DecisionFeedbackItem,
    DecisionFeedbackResponse,
)
from models.casework import (
    CaseCreate,
    CaseDetail,
    CaseEvidenceDeleteResponse,
    CaseEvidenceItem,
    CaseEvidencePinRequest,
    CaseEvidenceUpdateRequest,
    CaseEventItem,
    CaseFilingPackRequest,
    CaseFilingPackResponse,
    CaseListItem,
    CaseNoteCreate,
    CaseNoteItem,
    CaseTaskCreate,
    CaseTaskItem,
    CaseTaskUpdate,
    CaseUpdate,
    CaseWorkflowStateResponse,
    CaseWorkspaceResponse,
    FilingReadinessResponse,
    SarDraftRequest,
    SarFileRequest,
    SarUpdateRequest,
    SarRebalanceRequest,
    SarRebalanceResponse,
    SarReportDetail,
    SarQueueResponse,
    SarWorkflowRequest,
)
from models.intelligence import CaseContextResponse, CaseSummaryRequest, CaseSummaryResponse
from services.case_context import get_case_context
from services.case_filing_pack import export_case_filing_pack, generate_case_filing_pack
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
    run_bulk_sar_queue_actions,
    list_sar_queue,
    list_case_events,
    list_case_notes,
    list_case_tasks,
    list_cases,
    update_sar,
    update_case,
    update_case_task,
)
from services.case_workspace import (
    delete_case_evidence,
    get_case_filing_readiness,
    get_case_workflow_state,
    get_case_workspace,
    list_case_evidence,
    pin_case_evidence,
    update_case_evidence,
)
from services.decision_quality import list_decision_feedback, record_decision_feedback
from services.maturity_features import get_sar_bulk_preview
from services.auth import (
    AuthenticatedUser,
    ensure_assignment_allowed,
    require_any_permissions,
    require_permissions,
    resolve_request_actor,
)

router = APIRouter()


async def _guard_sar_approval_separation(case_id: UUID, current_user: AuthenticatedUser) -> None:
    sar = await get_case_sar(case_id)
    if not sar or sar == {}:
        raise HTTPException(status_code=404, detail="Case or SAR not found")
    drafter = str(sar.get("drafted_by") or "").strip()
    reviewer = str(sar.get("reviewed_by") or "").strip()
    if drafter and drafter == current_user.username:
        raise HTTPException(status_code=403, detail="SAR drafter cannot approve the same SAR")
    if reviewer and reviewer == current_user.username:
        raise HTTPException(status_code=403, detail="SAR reviewer cannot approve the same SAR")


async def _guard_sar_filing_separation(case_id: UUID, current_user: AuthenticatedUser) -> None:
    sar = await get_case_sar(case_id)
    if not sar or sar == {}:
        raise HTTPException(status_code=404, detail="Case or SAR not found")
    drafter = str(sar.get("drafted_by") or "").strip()
    if drafter and drafter == current_user.username:
        raise HTTPException(status_code=403, detail="SAR drafter cannot file the same SAR")


@router.get("/sars/queue", response_model=SarQueueResponse, summary="Get first-class SAR review and approval queues")
async def get_sar_queue(
    queue: str = Query("review", pattern="^(draft|review|approval|filed|all)$"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: AuthenticatedUser = Depends(require_permissions("view_cases")),
):
    try:
        row = await list_sar_queue(queue=queue, limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SarQueueResponse(**row)


@router.post("/sars/queue/rebalance", response_model=SarRebalanceResponse, summary="Automatically rebalance SAR queue workload across analysts")
async def post_sar_queue_rebalance(
    payload: SarRebalanceRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_queues")),
):
    try:
        row = await rebalance_sar_queue(
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
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


@router.post("/sars/queue/bulk-actions", response_model=BulkSarActionResponse, summary="Apply bulk reviewer or approver actions to SAR queue items")
async def post_sar_queue_bulk_actions(
    payload: BulkSarActionRequest,
    current_user: AuthenticatedUser = Depends(require_any_permissions("manage_queues", "review_sar", "approve_sar")),
):
    try:
        row = await run_bulk_sar_queue_actions(
            payload.model_copy(
                update={
                    "actor": resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
                    "assigned_to": ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user),
                }
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BulkSarActionResponse(**row)


@router.post("/sars/queue/bulk-preview", response_model=BulkActionPreviewResponse, summary="Preview a bulk SAR queue action before applying it")
async def post_sar_queue_bulk_preview(
    payload: BulkSarActionRequest,
    current_user: AuthenticatedUser = Depends(require_any_permissions("manage_queues", "review_sar", "approve_sar")),
):
    return BulkActionPreviewResponse(**(await get_sar_bulk_preview(payload.case_ids, payload.action)))


@router.post("/cases", response_model=CaseDetail, status_code=status.HTTP_201_CREATED, summary="Create case")
async def post_case(
    payload: CaseCreate,
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    row = await create_case(
        payload.model_copy(
            update={
                "assigned_to": ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user),
                "created_by": resolve_request_actor(requested_actor=payload.created_by, current_user=current_user),
            }
        )
    )
    return CaseDetail(**row)


@router.get("/cases", response_model=list[CaseListItem], summary="List cases")
async def get_cases(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_permissions("view_cases")),
):
    rows = await list_cases(limit=limit, offset=offset, status=status)
    return [CaseListItem(**row) for row in rows]


@router.get("/cases/{case_id}", response_model=CaseDetail, summary="Get case detail")
async def get_case(case_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_cases"))):
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
    current_user: AuthenticatedUser = Depends(require_permissions("view_cases")),
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
    current_user: AuthenticatedUser = Depends(require_permissions("view_cases")),
):
    row = await get_case_context(case_id=case_id, document_limit=document_limit, related_limit=related_limit)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseContextResponse(**row)


@router.get("/cases/{case_id}/workspace", response_model=CaseWorkspaceResponse, summary="Get aggregated case command center workspace")
async def get_case_command_workspace(
    case_id: UUID,
    document_limit: int = Query(4, ge=1, le=12),
    related_limit: int = Query(6, ge=1, le=15),
    current_user: AuthenticatedUser = Depends(require_permissions("view_cases")),
):
    row = await get_case_workspace(case_id=case_id, document_limit=document_limit, related_limit=related_limit)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseWorkspaceResponse(**row)


@router.get("/cases/{case_id}/workflow", response_model=CaseWorkflowStateResponse, summary="Get case-specific workflow state")
async def get_case_workflow(case_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_cases"))):
    row = await get_case_workflow_state(case_id)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseWorkflowStateResponse(**row)


@router.get("/cases/{case_id}/filing-readiness", response_model=FilingReadinessResponse, summary="Get filing readiness for case")
async def get_case_readiness(case_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_cases"))):
    row = await get_case_filing_readiness(case_id)
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return FilingReadinessResponse(**row)


@router.get("/cases/{case_id}/evidence", response_model=list[CaseEvidenceItem], summary="List pinned evidence for a case")
async def get_case_pinned_evidence(case_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_cases"))):
    rows = await list_case_evidence(case_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return [CaseEvidenceItem(**row) for row in rows]


@router.get("/cases/{case_id}/feedback", response_model=list[DecisionFeedbackItem], summary="List closed-loop feedback for a case")
async def get_case_feedback(case_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_cases"))):
    rows = await list_decision_feedback("case", case_id, limit=30)
    return [DecisionFeedbackItem(**row) for row in rows]


@router.post("/cases/{case_id}/feedback", response_model=DecisionFeedbackResponse, summary="Record closed-loop feedback for a case")
async def post_case_feedback(
    case_id: UUID,
    payload: DecisionFeedbackCreateRequest,
    current_user: AuthenticatedUser = Depends(require_any_permissions("edit_cases", "review_sar", "approve_sar", "manage_queues")),
):
    try:
        row = await record_decision_feedback(
            subject_type="case",
            subject_id=case_id,
            actor=resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            actor_role=current_user.role_key,
            feedback_key=payload.feedback_key,
            note=payload.note,
            metadata=payload.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DecisionFeedbackResponse(item=DecisionFeedbackItem(**row), summary=[f"Recorded {row['label'].lower()} feedback for the selected case."])


@router.post("/cases/{case_id}/evidence/pin", response_model=CaseEvidenceItem, status_code=status.HTTP_201_CREATED, summary="Pin evidence to a case")
async def post_case_pinned_evidence(
    case_id: UUID,
    payload: CaseEvidencePinRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    row = await pin_case_evidence(
        case_id,
        payload.model_dump()
        | {
            "pinned_by": resolve_request_actor(requested_actor=payload.pinned_by, current_user=current_user),
        },
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseEvidenceItem(**row)


@router.patch("/cases/{case_id}/evidence/{evidence_id}", response_model=CaseEvidenceItem, summary="Update pinned evidence for a case")
async def patch_case_pinned_evidence(
    case_id: UUID,
    evidence_id: UUID,
    payload: CaseEvidenceUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    row = await update_case_evidence(
        case_id,
        evidence_id,
        payload.model_dump(exclude_none=True)
        | {"updated_by": resolve_request_actor(requested_actor=payload.updated_by, current_user=current_user)},
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case or evidence not found")
    return CaseEvidenceItem(**row)


@router.delete("/cases/{case_id}/evidence/{evidence_id}", response_model=CaseEvidenceDeleteResponse, summary="Remove pinned evidence from a case")
async def delete_case_pinned_evidence(
    case_id: UUID,
    evidence_id: UUID,
    removed_by: str | None = Query(None),
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    deleted = await delete_case_evidence(
        case_id,
        evidence_id,
        removed_by=resolve_request_actor(requested_actor=removed_by, current_user=current_user),
    )
    if deleted is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if deleted is False:
        raise HTTPException(status_code=404, detail="Evidence not found")
    return CaseEvidenceDeleteResponse(status="deleted", case_id=case_id, evidence_id=evidence_id)


@router.post("/cases/{case_id}/summary", response_model=CaseSummaryResponse, summary="Generate AI case summary")
async def post_case_summary(
    case_id: UUID,
    payload: CaseSummaryRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("draft_sar")),
):
    row = await generate_case_summary(
        case_id=case_id,
        generated_by=resolve_request_actor(requested_actor=payload.generated_by, current_user=current_user),
        persist=payload.persist,
        document_limit=payload.document_limit,
        related_limit=payload.related_limit,
        prioritize_pinned_evidence=payload.prioritize_pinned_evidence,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseSummaryResponse(**row)


@router.get("/cases/{case_id}/sar", response_model=SarReportDetail | None, summary="Get case SAR detail")
async def get_case_sar_detail(case_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_cases"))):
    row = await get_case_sar(case_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if row == {}:
        return None
    return SarReportDetail(**row)


@router.post("/cases/{case_id}/filing-pack", response_model=CaseFilingPackResponse, summary="Generate a grounded filing evidence pack")
async def post_case_filing_pack(
    case_id: UUID,
    payload: CaseFilingPackRequest | None = None,
    current_user: AuthenticatedUser = Depends(require_permissions("export_filing_pack")),
):
    payload = payload or CaseFilingPackRequest()
    row = await generate_case_filing_pack(
        case_id=case_id,
        generated_by=resolve_request_actor(requested_actor=payload.generated_by, current_user=current_user),
        include_notes=payload.include_notes,
        include_tasks=payload.include_tasks,
        include_ai_summary=payload.include_ai_summary,
        evidence_limit=payload.evidence_limit,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseFilingPackResponse(**row)


@router.get("/cases/{case_id}/filing-pack/export", summary="Download a filing pack artifact")
async def get_case_filing_pack_export(
    case_id: UUID,
    format: str = Query("json", pattern="^(json|pdf|docx)$"),
    generated_by: str | None = Query(None),
    include_notes: bool = Query(True),
    include_tasks: bool = Query(True),
    include_ai_summary: bool = Query(True),
    evidence_limit: int = Query(12, ge=3, le=30),
    current_user: AuthenticatedUser = Depends(require_permissions("export_filing_pack")),
):
    row = await generate_case_filing_pack(
        case_id=case_id,
        generated_by=resolve_request_actor(requested_actor=generated_by, current_user=current_user),
        include_notes=include_notes,
        include_tasks=include_tasks,
        include_ai_summary=include_ai_summary,
        evidence_limit=evidence_limit,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    try:
        filename, payload, media_type = export_case_filing_pack(row, format)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return Response(
        content=payload,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.patch("/cases/{case_id}/sar", response_model=SarReportDetail, summary="Update SAR draft details")
async def patch_case_sar_detail(
    case_id: UUID,
    payload: SarUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("draft_sar")),
):
    try:
        row = await update_sar(
            case_id,
            payload.model_copy(update={"editor": resolve_request_actor(requested_actor=payload.editor, current_user=current_user)}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if row == {}:
        raise HTTPException(status_code=404, detail="SAR not found")
    return SarReportDetail(**row)


@router.patch("/cases/{case_id}", response_model=CaseDetail, summary="Update case")
async def patch_case(
    case_id: UUID,
    payload: CaseUpdate,
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    row = await update_case(
        case_id,
        payload.model_copy(
            update={
                "assigned_to": ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user),
                "closed_by": resolve_request_actor(requested_actor=payload.closed_by, current_user=current_user, allow_delegate=current_user.has_permission("manage_queues")),
                "event_actor": resolve_request_actor(requested_actor=payload.event_actor, current_user=current_user),
            }
        ),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseDetail(**row)


@router.get("/cases/{case_id}/tasks", response_model=list[CaseTaskItem], summary="List collaboration tasks for a case")
async def get_case_tasks(case_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_cases"))):
    rows = await list_case_tasks(case_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return [CaseTaskItem(**row) for row in rows]


@router.post("/cases/{case_id}/tasks", response_model=CaseTaskItem, status_code=status.HTTP_201_CREATED, summary="Create a collaboration task for a case")
async def post_case_task(
    case_id: UUID,
    payload: CaseTaskCreate,
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    row = await add_case_task(
        case_id,
        payload.model_copy(
            update={
                "assigned_to": ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user),
                "created_by": resolve_request_actor(requested_actor=payload.created_by, current_user=current_user),
            }
        ),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseTaskItem(**row)


@router.patch("/cases/{case_id}/tasks/{task_id}", response_model=CaseTaskItem, summary="Update a collaboration task for a case")
async def patch_case_task(
    case_id: UUID,
    task_id: UUID,
    payload: CaseTaskUpdate,
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    row = await update_case_task(
        case_id,
        task_id,
        payload.model_copy(
            update={
                "assigned_to": ensure_assignment_allowed(assigned_to=payload.assigned_to, current_user=current_user),
                "actor": resolve_request_actor(requested_actor=payload.actor, current_user=current_user),
            }
        ),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    if row == {}:
        raise HTTPException(status_code=404, detail="Task not found")
    return CaseTaskItem(**row)


@router.get("/cases/{case_id}/notes", response_model=list[CaseNoteItem], summary="List analyst notes for a case")
async def get_case_notes(case_id: UUID, current_user: AuthenticatedUser = Depends(require_permissions("view_cases"))):
    rows = await list_case_notes(case_id)
    if rows is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return [CaseNoteItem(**row) for row in rows]


@router.post("/cases/{case_id}/notes", response_model=CaseNoteItem, status_code=status.HTTP_201_CREATED, summary="Add an analyst note to a case")
async def post_case_note(
    case_id: UUID,
    payload: CaseNoteCreate,
    current_user: AuthenticatedUser = Depends(require_permissions("edit_cases")),
):
    row = await add_case_note(
        case_id,
        payload.model_copy(update={"author": resolve_request_actor(requested_actor=payload.author, current_user=current_user)}),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return CaseNoteItem(**row)


@router.post("/cases/{case_id}/sar", response_model=SarReportDetail, summary="Draft SAR report for case")
async def post_case_sar(
    case_id: UUID,
    payload: SarDraftRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("draft_sar")),
):
    row = await draft_sar(
        case_id,
        payload.model_copy(update={"drafted_by": resolve_request_actor(requested_actor=payload.drafted_by, current_user=current_user)}),
    )
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    return SarReportDetail(**row)


@router.post("/cases/{case_id}/sar/review", response_model=SarReportDetail, summary="Advance SAR review or approval workflow")
async def post_case_sar_review(
    case_id: UUID,
    payload: SarWorkflowRequest,
    current_user: AuthenticatedUser = Depends(require_any_permissions("review_sar", "approve_sar")),
):
    normalized = payload.model_copy(update={"actor": resolve_request_actor(requested_actor=payload.actor, current_user=current_user)})
    if normalized.action.value == "approve":
        if not current_user.has_permission("approve_sar"):
            raise HTTPException(status_code=403, detail="Approval permission is required")
        await _guard_sar_approval_separation(case_id, current_user)
    elif normalized.action.value in {"submit_review", "reject"} and not current_user.has_permission("review_sar"):
        raise HTTPException(status_code=403, detail="Review permission is required")
    try:
        row = await advance_sar_workflow(case_id, normalized)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Case or SAR not found")
    return SarReportDetail(**row)


@router.post("/cases/{case_id}/sar/file", response_model=SarReportDetail, summary="File SAR report for case")
async def post_case_sar_file(
    case_id: UUID,
    payload: SarFileRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("file_sar")),
):
    await _guard_sar_filing_separation(case_id, current_user)
    try:
        row = await file_sar(
            case_id,
            payload.model_copy(
                update={
                    "filed_by": current_user.username,
                    "approved_by": None,
                    "reviewed_by": None,
                }
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="Case or SAR not found")
    return SarReportDetail(**row)
