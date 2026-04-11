"""
Local auth, RBAC helpers, and future external-provider settings storage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from core.config import settings
from core.database import get_pool
from core.security import (
    ROLE_DEFINITIONS,
    create_access_token,
    has_permission,
    hash_password,
    verify_password,
)
from models.auth import (
    AuthProviderSettingsItem,
    AuthRoleItem,
    AuthUserItem,
    CurrentSessionResponse,
    UserProfilePreferences,
    UserProfileResponse,
)

bearer_scheme = HTTPBearer(auto_error=False)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            return []
    return []


def _normalize_json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


@dataclass
class AuthenticatedUser:
    id: UUID
    username: str
    full_name: str
    email: str | None
    role_key: str
    role_display_name: str
    permissions: list[str]
    desk_access: list[str]
    team_key: str
    team_label: str
    regions: list[str]
    countries: list[str]
    is_active: bool
    must_change_password: bool
    auth_provider: str
    last_login_at: datetime | None
    metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    @property
    def is_admin(self) -> bool:
        return self.role_key == "admin" or "*" in self.permissions

    def has_permission(self, permission: str) -> bool:
        return has_permission(self.permissions, permission)

    def can_access_desk(self, desk_key: str) -> bool:
        if self.is_admin:
            return True
        return desk_key in self.desk_access


def _user_from_row(row: Any) -> AuthenticatedUser:
    permissions = sorted(
        {
            str(item).strip()
            for item in _normalize_json_list(row.get("permissions"))
            if str(item).strip()
        }
    )
    desk_access = [
        str(item).strip()
        for item in _normalize_json_list(row.get("desk_access"))
        if str(item).strip()
    ]
    return AuthenticatedUser(
        id=row["id"],
        username=str(row["username"]),
        full_name=str(row["full_name"]),
        email=row.get("email"),
        role_key=str(row["role_key"]),
        role_display_name=str(row.get("role_display_name") or ROLE_DEFINITIONS.get(str(row["role_key"]), {}).get("display_name") or str(row["role_key"]).title()),
        permissions=permissions,
        desk_access=desk_access,
        team_key=str(row.get("team_key") or "global"),
        team_label=str(row.get("team_label") or "Global Operations"),
        regions=[str(item) for item in _normalize_json_list(row.get("regions")) if str(item).strip()],
        countries=[str(item).upper() for item in _normalize_json_list(row.get("countries")) if str(item).strip()],
        is_active=bool(row.get("is_active", True)),
        must_change_password=bool(row.get("must_change_password", False)),
        auth_provider=str(row.get("auth_provider") or "local"),
        last_login_at=row.get("last_login_at"),
        metadata=_normalize_json_dict(row.get("metadata")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _user_item(user: AuthenticatedUser) -> AuthUserItem:
    return AuthUserItem(
        id=user.id,
        username=user.username,
        full_name=user.full_name,
        email=user.email,
        role_key=user.role_key,
        role_display_name=user.role_display_name,
        permissions=user.permissions,
        desk_access=user.desk_access,
        team_key=user.team_key,
        team_label=user.team_label,
        regions=user.regions,
        countries=user.countries,
        is_active=user.is_active,
        must_change_password=user.must_change_password,
        auth_provider=user.auth_provider,
        last_login_at=user.last_login_at,
        metadata=user.metadata,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _provider_item(row: Any) -> AuthProviderSettingsItem:
    return AuthProviderSettingsItem(
        provider_key=str(row["provider_key"]),
        display_name=str(row["display_name"]),
        enabled=bool(row["enabled"]),
        mode=str(row.get("mode") or "password"),
        config=_normalize_json_dict(row.get("config")),
        updated_by=row.get("updated_by"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _profile_preferences_for_user(user: AuthenticatedUser) -> UserProfilePreferences:
    profile = _normalize_json_dict(user.metadata.get("profile"))
    preferred_home = _clean_optional_text(profile.get("preferred_home"))
    if preferred_home and preferred_home not in user.desk_access and not user.is_admin:
        preferred_home = None
    if not preferred_home:
        preferred_home = user.desk_access[0] if user.desk_access else "dashboard"
    return UserProfilePreferences(
        title=_clean_optional_text(profile.get("title")),
        phone=_clean_optional_text(profile.get("phone")),
        locale=_clean_optional_text(profile.get("locale")),
        timezone=_clean_optional_text(profile.get("timezone")),
        preferred_home=preferred_home,
        signature=_clean_optional_text(profile.get("signature")),
    )


def _role_item(row: Any) -> AuthRoleItem:
    return AuthRoleItem(
        role_key=str(row["role_key"]),
        display_name=str(row["display_name"]),
        description=row.get("description"),
        permissions=[str(item) for item in _normalize_json_list(row.get("permissions")) if str(item).strip()],
        desk_access=[str(item) for item in _normalize_json_list(row.get("desk_access")) if str(item).strip()],
        metadata=_normalize_json_dict(row.get("metadata")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def record_auth_audit_event(
    *,
    actor: str | None,
    event_type: str,
    status_value: str = "success",
    target_type: str | None = None,
    target_id: str | None = None,
    ip_address: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO auth_audit_events (
                actor, event_type, status, target_type, target_id, ip_address, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            """,
            actor,
            event_type,
            status_value,
            target_type,
            target_id,
            ip_address,
            json.dumps(metadata or {}),
        )


async def get_auth_user(username: str) -> AuthenticatedUser | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                u.*,
                r.display_name AS role_display_name,
                r.permissions,
                r.desk_access
            FROM app_users u
            JOIN auth_roles r ON r.role_key = u.role_key
            WHERE LOWER(u.username) = LOWER($1)
            """,
            username,
        )
    if not row:
        return None
    return _user_from_row(dict(row))


async def list_auth_roles() -> list[AuthRoleItem]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM auth_roles ORDER BY display_name ASC")
    return [_role_item(dict(row)) for row in rows]


async def list_auth_users() -> list[AuthUserItem]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                u.*,
                r.display_name AS role_display_name,
                r.permissions,
                r.desk_access
            FROM app_users u
            JOIN auth_roles r ON r.role_key = u.role_key
            ORDER BY u.role_key ASC, u.username ASC
            """
        )
    return [_user_item(_user_from_row(dict(row))) for row in rows]


async def list_provider_settings() -> list[AuthProviderSettingsItem]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM auth_provider_settings ORDER BY provider_key ASC")
    return [_provider_item(dict(row)) for row in rows]


async def get_auth_settings_response() -> dict[str, Any]:
    providers = await list_provider_settings()
    roles = await list_auth_roles()
    summary = [
        f"Auth mode is currently {settings.AUTH_MODE}.",
        f"{len(providers)} auth providers are configured, including a future-ready WSO2 placeholder.",
        f"{len(roles)} roles are available for local RBAC.",
    ]
    return {
        "auth_mode": settings.AUTH_MODE,
        "providers": providers,
        "roles": roles,
        "summary": summary,
    }


async def list_auth_audit_events(limit: int = 50) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT *
            FROM auth_audit_events
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [dict(row) for row in rows]


async def authenticate_local_user(username: str, password: str, request: Request | None = None) -> tuple[str, CurrentSessionResponse]:
    pool = get_pool()
    normalized = str(username or "").strip().lower()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                u.*,
                r.display_name AS role_display_name,
                r.permissions,
                r.desk_access
            FROM app_users u
            JOIN auth_roles r ON r.role_key = u.role_key
            WHERE LOWER(u.username) = LOWER($1)
            """,
            normalized,
        )
    if not row:
        await record_auth_audit_event(
            actor=normalized,
            event_type="login",
            status_value="denied",
            target_type="user",
            target_id=normalized,
            ip_address=request.client.host if request and request.client else None,
            metadata={"reason": "user_not_found"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    user = _user_from_row(dict(row))
    if not user.is_active:
        await record_auth_audit_event(
            actor=user.username,
            event_type="login",
            status_value="denied",
            target_type="user",
            target_id=user.username,
            ip_address=request.client.host if request and request.client else None,
            metadata={"reason": "user_inactive"},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    if not verify_password(password, dict(row)["password_hash"]):
        await record_auth_audit_event(
            actor=user.username,
            event_type="login",
            status_value="denied",
            target_type="user",
            target_id=user.username,
            ip_address=request.client.host if request and request.client else None,
            metadata={"reason": "bad_password"},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    expires_at = _utcnow() + timedelta(minutes=settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES)
    token = create_access_token(subject=user.username, expires_at=expires_at)

    await record_auth_audit_event(
        actor=user.username,
        event_type="login",
        status_value="success",
        target_type="user",
        target_id=user.username,
        ip_address=request.client.host if request and request.client else None,
        metadata={"role_key": user.role_key},
    )

    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE app_users
            SET last_login_at = NOW(), updated_at = NOW()
            WHERE username = $1
            """,
            user.username,
        )

    refreshed = await get_auth_user(user.username)
    assert refreshed is not None
    providers = await list_provider_settings()
    session = CurrentSessionResponse(
        auth_mode=settings.AUTH_MODE,
        user=_user_item(refreshed),
        provider_settings=providers,
        summary=[
            f"Logged in as {refreshed.full_name}.",
            f"Role {refreshed.role_display_name} unlocks {len(refreshed.permissions)} permissions and {len(refreshed.desk_access)} desks.",
        ],
    )
    return token, session


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)) -> AuthenticatedUser:
    if credentials is None or str(credentials.credentials or "").strip() == "":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.AUTH_JWT_SECRET,
            algorithms=[settings.AUTH_JWT_ALGORITHM],
            audience=settings.AUTH_JWT_AUDIENCE,
            issuer=settings.AUTH_JWT_ISSUER,
        )
    except JWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token") from exc
    subject = str(payload.get("sub") or "").strip()
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject")
    user = await get_auth_user(subject)
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User session is no longer active")
    return user


def require_permissions(*permissions: str) -> Callable[..., Any]:
    required = [str(value).strip() for value in permissions if str(value).strip()]

    async def _dependency(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if current_user.is_admin:
            return current_user
        missing = [permission for permission in required if not current_user.has_permission(permission)]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission(s): {', '.join(missing)}",
            )
        return current_user

    return _dependency


def require_any_permissions(*permissions: str) -> Callable[..., Any]:
    allowed = [str(value).strip() for value in permissions if str(value).strip()]

    async def _dependency(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if current_user.is_admin:
            return current_user
        if any(current_user.has_permission(permission) for permission in allowed):
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing one of the required permissions: {', '.join(allowed)}",
        )

    return _dependency


def require_roles(*role_keys: str) -> Callable[..., Any]:
    allowed = {str(value).strip() for value in role_keys if str(value).strip()}

    async def _dependency(current_user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if current_user.is_admin or current_user.role_key in allowed:
            return current_user
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Role is not allowed to access this action")

    return _dependency


def resolve_request_actor(
    *,
    requested_actor: str | None,
    current_user: AuthenticatedUser,
    allow_delegate: bool = False,
) -> str:
    requested = str(requested_actor or "").strip()
    if not requested or requested == current_user.username:
        return current_user.username
    if allow_delegate or current_user.has_permission("manage_queues") or current_user.has_permission("manage_workflows") or current_user.has_permission("manage_models") or current_user.has_permission("manage_users"):
        return requested
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot act on behalf of another user")


def ensure_assignment_allowed(*, assigned_to: str | None, current_user: AuthenticatedUser) -> str | None:
    if assigned_to is None:
        return None
    target = str(assigned_to).strip()
    if not target:
        return None
    if target == current_user.username:
        return target
    if current_user.has_permission("manage_queues") or current_user.has_permission("manage_users") or current_user.is_admin:
        return target
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You cannot assign work to another user")


async def update_provider_settings(
    provider_key: str,
    *,
    display_name: str | None,
    enabled: bool | None,
    mode: str | None,
    config: dict[str, Any] | None,
    updated_by: str,
) -> AuthProviderSettingsItem:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM auth_provider_settings WHERE provider_key = $1", provider_key)
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auth provider not found")
        current = dict(row)
        merged_config = _normalize_json_dict(current.get("config"))
        merged_config.update(config or {})
        updated = await conn.fetchrow(
            """
            UPDATE auth_provider_settings
            SET
                display_name = COALESCE($2, display_name),
                enabled = COALESCE($3, enabled),
                mode = COALESCE($4, mode),
                config = $5::jsonb,
                updated_by = $6,
                updated_at = NOW()
            WHERE provider_key = $1
            RETURNING *
            """,
            provider_key,
            display_name,
            enabled,
            mode,
            json.dumps(merged_config),
            updated_by,
        )
    await record_auth_audit_event(
        actor=updated_by,
        event_type="provider_settings_updated",
        target_type="auth_provider",
        target_id=provider_key,
        metadata={"enabled": enabled, "mode": mode},
    )
    return _provider_item(dict(updated))


async def create_local_user(payload: dict[str, Any], actor: str) -> AuthUserItem:
    role_key = str(payload.get("role_key") or "").strip()
    if role_key not in ROLE_DEFINITIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role_key")
    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT 1 FROM app_users WHERE LOWER(username) = LOWER($1)", payload["username"])
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
        row = await conn.fetchrow(
            """
            INSERT INTO app_users (
                username, full_name, email, password_hash, role_key,
                team_key, team_label, regions, countries, is_active,
                must_change_password, auth_provider, metadata, password_updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, 'local', $12::jsonb, NOW())
            RETURNING *
            """,
            str(payload["username"]).strip().lower(),
            payload["full_name"],
            payload.get("email"),
            hash_password(payload["password"]),
            role_key,
            payload.get("team_key", "global"),
            payload.get("team_label", "Global Operations"),
            json.dumps(payload.get("regions", [])),
            json.dumps(payload.get("countries", [])),
            payload.get("is_active", True),
            payload.get("must_change_password", False),
            json.dumps(payload.get("metadata", {})),
        )
    await record_auth_audit_event(
        actor=actor,
        event_type="user_created",
        target_type="user",
        target_id=str(payload["username"]).strip().lower(),
        metadata={"role_key": role_key},
    )
    created = await get_auth_user(str(payload["username"]).strip().lower())
    assert created is not None
    return _user_item(created)


async def update_local_user(username: str, payload: dict[str, Any], actor: str) -> AuthUserItem:
    if "role_key" in payload and payload["role_key"] is not None and str(payload["role_key"]) not in ROLE_DEFINITIONS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown role_key")
    updates: list[str] = []
    values: list[Any] = []
    idx = 1
    mapping = {
        "full_name": "full_name",
        "email": "email",
        "role_key": "role_key",
        "team_key": "team_key",
        "team_label": "team_label",
        "is_active": "is_active",
        "must_change_password": "must_change_password",
    }
    for field, column in mapping.items():
        if field in payload and payload[field] is not None:
            updates.append(f"{column} = ${idx}")
            values.append(payload[field])
            idx += 1
    if "regions" in payload and payload["regions"] is not None:
        updates.append(f"regions = ${idx}::jsonb")
        values.append(json.dumps(payload["regions"]))
        idx += 1
    if "countries" in payload and payload["countries"] is not None:
        updates.append(f"countries = ${idx}::jsonb")
        values.append(json.dumps(payload["countries"]))
        idx += 1
    if "metadata" in payload and payload["metadata"] is not None:
        updates.append(f"metadata = ${idx}::jsonb")
        values.append(json.dumps(payload["metadata"]))
        idx += 1
    if not updates:
        existing = await get_auth_user(username)
        if not existing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return _user_item(existing)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE app_users
            SET {", ".join(updates)}, updated_at = NOW()
            WHERE LOWER(username) = LOWER(${idx})
            RETURNING *
            """,
            *values,
            username.lower(),
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await record_auth_audit_event(
        actor=actor,
        event_type="user_updated",
        target_type="user",
        target_id=username.lower(),
        metadata={"fields": sorted(payload.keys())},
    )
    updated = await get_auth_user(username.lower())
    assert updated is not None
    return _user_item(updated)


async def change_current_user_password(current_user: AuthenticatedUser, current_password: str, new_password: str) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT password_hash FROM app_users WHERE id = $1", current_user.id)
        if not row or not verify_password(current_password, str(row["password_hash"])):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
        await conn.execute(
            """
            UPDATE app_users
            SET password_hash = $2, must_change_password = FALSE, password_updated_at = NOW(), updated_at = NOW()
            WHERE id = $1
            """,
            current_user.id,
            hash_password(new_password),
        )
    await record_auth_audit_event(
        actor=current_user.username,
        event_type="password_changed",
        target_type="user",
        target_id=current_user.username,
    )
    return {
        "status": "password_changed",
        "username": current_user.username,
        "changed_at": _utcnow(),
        "summary": ["Password updated successfully."],
    }


async def get_current_user_profile(current_user: AuthenticatedUser) -> UserProfileResponse:
    providers = await list_provider_settings()
    profile = _profile_preferences_for_user(current_user)
    return UserProfileResponse(
        auth_mode=settings.AUTH_MODE,
        user=_user_item(current_user),
        provider_settings=providers,
        profile=profile,
        summary=[
            f"Signed in as {current_user.full_name}.",
            f"Preferred home desk is {profile.preferred_home or 'dashboard'}.",
            f"Role {current_user.role_display_name} currently exposes {len(current_user.desk_access)} desks.",
        ],
    )


async def update_current_user_profile(current_user: AuthenticatedUser, payload: dict[str, Any], actor: str) -> UserProfileResponse:
    if not payload:
        return await get_current_user_profile(current_user)

    updates: list[str] = []
    values: list[Any] = []
    idx = 1

    if "full_name" in payload:
        full_name = _clean_optional_text(payload.get("full_name"))
        if not full_name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Full name cannot be empty")
        updates.append(f"full_name = ${idx}")
        values.append(full_name)
        idx += 1

    if "email" in payload:
        updates.append(f"email = ${idx}")
        values.append(_clean_optional_text(payload.get("email")))
        idx += 1

    profile_updates: dict[str, Any] = {}
    for field in ("title", "phone", "locale", "timezone", "signature"):
        if field in payload:
            profile_updates[field] = _clean_optional_text(payload.get(field))

    if "preferred_home" in payload:
        preferred_home = _clean_optional_text(payload.get("preferred_home"))
        if preferred_home and preferred_home not in current_user.desk_access and not current_user.is_admin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Preferred home desk is not available for this user")
        profile_updates["preferred_home"] = preferred_home

    if profile_updates:
        current_metadata = dict(current_user.metadata or {})
        current_profile = _normalize_json_dict(current_metadata.get("profile"))
        for key, value in profile_updates.items():
            if value is None:
                current_profile.pop(key, None)
            else:
                current_profile[key] = value
        current_metadata["profile"] = current_profile
        updates.append(f"metadata = ${idx}::jsonb")
        values.append(json.dumps(current_metadata))
        idx += 1

    if not updates:
        return await get_current_user_profile(current_user)

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE app_users
            SET {", ".join(updates)}, updated_at = NOW()
            WHERE id = ${idx}
            RETURNING username
            """,
            *values,
            current_user.id,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await record_auth_audit_event(
        actor=actor,
        event_type="profile_updated",
        target_type="user",
        target_id=current_user.username,
        metadata={"fields": sorted(payload.keys())},
    )

    refreshed = await get_auth_user(current_user.username)
    assert refreshed is not None
    return await get_current_user_profile(refreshed)


async def reset_user_password(username: str, *, new_password: str, must_change_password: bool, actor: str) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE app_users
            SET password_hash = $2, must_change_password = $3, password_updated_at = NOW(), updated_at = NOW()
            WHERE LOWER(username) = LOWER($1)
            RETURNING username
            """,
            username.lower(),
            hash_password(new_password),
            must_change_password,
        )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await record_auth_audit_event(
        actor=actor,
        event_type="password_reset",
        target_type="user",
        target_id=username.lower(),
        metadata={"must_change_password": must_change_password},
    )
    return {
        "status": "password_reset",
        "username": username.lower(),
        "changed_at": _utcnow(),
        "summary": [f"Password reset for {username.lower()}."],
    }


async def get_current_session(current_user: AuthenticatedUser) -> CurrentSessionResponse:
    providers = await list_provider_settings()
    return CurrentSessionResponse(
        auth_mode=settings.AUTH_MODE,
        user=_user_item(current_user),
        provider_settings=providers,
        summary=[
            f"Authenticated as {current_user.full_name}.",
            f"Role {current_user.role_display_name} has {len(current_user.permissions)} permissions.",
        ],
    )
