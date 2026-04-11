"""
Pydantic models for local auth, RBAC, and provider settings.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AuthRoleItem(BaseModel):
    role_key: str
    display_name: str
    description: str | None = None
    permissions: list[str] = Field(default_factory=list)
    desk_access: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AuthUserItem(BaseModel):
    id: UUID
    username: str
    full_name: str
    email: str | None = None
    role_key: str
    role_display_name: str | None = None
    permissions: list[str] = Field(default_factory=list)
    desk_access: list[str] = Field(default_factory=list)
    team_key: str
    team_label: str
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    is_active: bool = True
    must_change_password: bool = False
    auth_provider: str = "local"
    last_login_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class AuthProviderSettingsItem(BaseModel):
    provider_key: str
    display_name: str
    enabled: bool = False
    mode: str = "password"
    config: dict[str, Any] = Field(default_factory=dict)
    updated_by: str | None = None
    created_at: datetime
    updated_at: datetime


class AuthAuditEventItem(BaseModel):
    id: UUID
    actor: str | None = None
    event_type: str
    status: str
    target_type: str | None = None
    target_id: str | None = None
    ip_address: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=8, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    auth_mode: str = "local"
    user: AuthUserItem
    provider_settings: list[AuthProviderSettingsItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class CurrentSessionResponse(BaseModel):
    auth_mode: str = "local"
    user: AuthUserItem
    provider_settings: list[AuthProviderSettingsItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class UserProfilePreferences(BaseModel):
    title: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=64)
    locale: str | None = Field(None, max_length=64)
    timezone: str | None = Field(None, max_length=128)
    preferred_home: str | None = Field(None, max_length=64)
    signature: str | None = Field(None, max_length=2000)


class UserProfileResponse(BaseModel):
    auth_mode: str = "local"
    user: AuthUserItem
    provider_settings: list[AuthProviderSettingsItem] = Field(default_factory=list)
    profile: UserProfilePreferences = Field(default_factory=UserProfilePreferences)
    summary: list[str] = Field(default_factory=list)


class UserProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    email: str | None = Field(None, max_length=255)
    title: str | None = Field(None, max_length=255)
    phone: str | None = Field(None, max_length=64)
    locale: str | None = Field(None, max_length=64)
    timezone: str | None = Field(None, max_length=128)
    preferred_home: str | None = Field(None, max_length=64)
    signature: str | None = Field(None, max_length=2000)


class AuthProviderSettingsUpdateRequest(BaseModel):
    display_name: str | None = Field(None, max_length=255)
    enabled: bool | None = None
    mode: str | None = Field(None, max_length=64)
    config: dict[str, Any] = Field(default_factory=dict)
    updated_by: str | None = Field(None, max_length=255)


class AuthSettingsResponse(BaseModel):
    auth_mode: str
    providers: list[AuthProviderSettingsItem] = Field(default_factory=list)
    roles: list[AuthRoleItem] = Field(default_factory=list)
    summary: list[str] = Field(default_factory=list)


class LocalUserCreateRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=255)
    full_name: str = Field(..., min_length=2, max_length=255)
    email: str | None = Field(None, max_length=255)
    password: str = Field(..., min_length=8, max_length=255)
    role_key: str = Field(..., min_length=2, max_length=64)
    team_key: str = Field("global", min_length=2, max_length=64)
    team_label: str = Field("Global Operations", min_length=2, max_length=255)
    regions: list[str] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    is_active: bool = True
    must_change_password: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class LocalUserUpdateRequest(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    email: str | None = Field(None, max_length=255)
    role_key: str | None = Field(None, min_length=2, max_length=64)
    team_key: str | None = Field(None, min_length=2, max_length=64)
    team_label: str | None = Field(None, min_length=2, max_length=255)
    regions: list[str] | None = None
    countries: list[str] | None = None
    is_active: bool | None = None
    must_change_password: bool | None = None
    metadata: dict[str, Any] | None = None


class PasswordChangeRequest(BaseModel):
    current_password: str = Field(..., min_length=8, max_length=255)
    new_password: str = Field(..., min_length=8, max_length=255)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=255)
    must_change_password: bool = True


class PasswordActionResponse(BaseModel):
    status: str
    username: str
    changed_at: datetime
    summary: list[str] = Field(default_factory=list)
