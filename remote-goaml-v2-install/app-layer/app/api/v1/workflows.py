"""
Workflow, orchestration, and automation dashboard endpoints.
"""

from fastapi import APIRouter

from models.workflows import SlaNotificationRequest
from services.workflow_engine import (
    dispatch_sla_notifications,
    get_camunda_dashboard,
    get_n8n_dashboard,
    get_workflow_overview,
)

router = APIRouter()


@router.get("/workflow/overview", summary="Get workflow operations overview")
async def get_workflow_dashboard():
    return await get_workflow_overview()


@router.get("/workflow/n8n", summary="Get n8n automation dashboard data")
async def get_n8n_workflow_dashboard():
    return await get_n8n_dashboard()


@router.get("/workflow/camunda", summary="Get Camunda orchestration dashboard data")
async def get_camunda_workflow_dashboard():
    return await get_camunda_dashboard()


@router.post("/workflow/sla/notify", summary="Dispatch SAR SLA breach notifications")
async def post_sla_notifications(payload: SlaNotificationRequest):
    return await dispatch_sla_notifications(
        triggered_by=payload.triggered_by,
        channels=payload.channels,
        breached_only=payload.breached_only,
        include_due_soon=payload.include_due_soon,
    )
