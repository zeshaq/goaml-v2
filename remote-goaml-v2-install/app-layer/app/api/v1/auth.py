"""
Local auth, RBAC, and provider settings endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, status

from core.config import settings
from models.auth import (
    AuthAuditEventItem,
    AuthProviderSettingsItem,
    AuthRoleItem,
    AuthSettingsResponse,
    AuthUserItem,
    AuthProviderSettingsUpdateRequest,
    CurrentSessionResponse,
    LocalUserCreateRequest,
    LocalUserUpdateRequest,
    LoginRequest,
    PasswordActionResponse,
    PasswordChangeRequest,
    PasswordResetRequest,
    TokenResponse,
    UserProfileResponse,
    UserProfileUpdateRequest,
)
from services.auth import (
    AuthenticatedUser,
    authenticate_local_user,
    change_current_user_password,
    create_local_user,
    get_auth_settings_response,
    get_current_user_profile,
    get_current_session,
    get_current_user,
    list_auth_audit_events,
    list_auth_roles,
    list_auth_users,
    record_auth_audit_event,
    require_permissions,
    reset_user_password,
    update_local_user,
    update_current_user_profile,
    update_provider_settings,
)

router = APIRouter()


@router.post("/auth/login", response_model=TokenResponse, summary="Authenticate with local username and password")
async def post_auth_login(payload: LoginRequest, request: Request):
    token, session = await authenticate_local_user(payload.username, payload.password, request=request)
    return TokenResponse(
        access_token=token,
        expires_in=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        auth_mode=session.auth_mode,
        user=session.user,
        provider_settings=session.provider_settings,
        summary=session.summary,
    )


@router.post("/auth/logout", summary="Record a logout event for the current token holder")
async def post_auth_logout(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    await record_auth_audit_event(
        actor=current_user.username,
        event_type="logout",
        target_type="user",
        target_id=current_user.username,
        ip_address=request.client.host if request.client else None,
    )
    return {"status": "logged_out"}


@router.get("/auth/me", response_model=CurrentSessionResponse, summary="Get current authenticated user and provider context")
async def get_auth_me(current_user: AuthenticatedUser = Depends(get_current_user)):
    return await get_current_session(current_user)


@router.post("/auth/change-password", response_model=PasswordActionResponse, summary="Change the current user's password")
async def post_change_password(
    payload: PasswordChangeRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return PasswordActionResponse(**(await change_current_user_password(current_user, payload.current_password, payload.new_password)))


@router.get("/auth/profile", response_model=UserProfileResponse, summary="Get the current user's editable profile and preferences")
async def get_auth_profile(current_user: AuthenticatedUser = Depends(get_current_user)):
    return await get_current_user_profile(current_user)


@router.patch("/auth/profile", response_model=UserProfileResponse, summary="Update the current user's profile and desk preferences")
async def patch_auth_profile(
    payload: UserProfileUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    return await update_current_user_profile(current_user, payload.model_dump(exclude_unset=True), current_user.username)


@router.get("/auth/settings", response_model=AuthSettingsResponse, summary="Get auth mode, provider settings, and RBAC roles")
async def get_auth_settings(
    current_user: AuthenticatedUser = Depends(require_permissions("manage_auth_settings")),
):
    return AuthSettingsResponse(**(await get_auth_settings_response()))


@router.put("/auth/settings/{provider_key}", response_model=AuthProviderSettingsItem, summary="Update local or future external auth provider settings")
async def put_auth_provider_settings(
    provider_key: str,
    payload: AuthProviderSettingsUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_auth_settings")),
):
    return await update_provider_settings(
        provider_key=provider_key,
        display_name=payload.display_name,
        enabled=payload.enabled,
        mode=payload.mode,
        config=payload.config,
        updated_by=current_user.username,
    )


@router.get("/auth/roles", response_model=list[AuthRoleItem], summary="List RBAC role definitions")
async def get_auth_roles(current_user: AuthenticatedUser = Depends(require_permissions("manage_users"))):
    return await list_auth_roles()


@router.get("/auth/users", response_model=list[AuthUserItem], summary="List local users and their effective role access")
async def get_auth_users(current_user: AuthenticatedUser = Depends(require_permissions("manage_users"))):
    return await list_auth_users()


@router.post("/auth/users", response_model=AuthUserItem, status_code=status.HTTP_201_CREATED, summary="Create a local user")
async def post_auth_user(
    payload: LocalUserCreateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_users")),
):
    return await create_local_user(payload.model_dump(), current_user.username)


@router.patch("/auth/users/{username}", response_model=AuthUserItem, summary="Update a local user")
async def patch_auth_user(
    username: str,
    payload: LocalUserUpdateRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_users")),
):
    return await update_local_user(username, payload.model_dump(exclude_none=True), current_user.username)


@router.post("/auth/users/{username}/reset-password", response_model=PasswordActionResponse, summary="Reset a local user's password")
async def post_auth_user_password_reset(
    username: str,
    payload: PasswordResetRequest,
    current_user: AuthenticatedUser = Depends(require_permissions("manage_users")),
):
    return PasswordActionResponse(
        **(
            await reset_user_password(
                username,
                new_password=payload.new_password,
                must_change_password=payload.must_change_password,
                actor=current_user.username,
            )
        )
    )


@router.get("/auth/audit", response_model=list[AuthAuditEventItem], summary="Get recent auth and RBAC audit events")
async def get_auth_audit(
    limit: int = Query(50, ge=10, le=200),
    current_user: AuthenticatedUser = Depends(require_permissions("manage_auth_settings")),
):
    rows = await list_auth_audit_events(limit=limit)
    return [AuthAuditEventItem(**row) for row in rows]
