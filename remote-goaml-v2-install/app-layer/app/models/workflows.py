"""
Workflow and automation request models.
"""

from pydantic import BaseModel, Field


class SlaNotificationRequest(BaseModel):
    triggered_by: str | None = None
    channels: list[str] = Field(default_factory=lambda: ["slack", "email"])
    breached_only: bool = True
    include_due_soon: bool | None = None
