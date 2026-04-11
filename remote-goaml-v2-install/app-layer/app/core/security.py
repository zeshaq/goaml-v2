"""
Local authentication, RBAC defaults, and future IdP-ready provider settings.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from jose import jwt
from passlib.context import CryptContext

from core.config import settings

PASSWORD_CONTEXT = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


DEFAULT_PERMISSIONS: tuple[str, ...] = (
    "view_dashboard",
    "view_alerts",
    "triage_alerts",
    "view_transactions",
    "ingest_transactions",
    "view_cases",
    "edit_cases",
    "draft_sar",
    "review_sar",
    "approve_sar",
    "file_sar",
    "manage_queues",
    "view_entities",
    "resolve_entities",
    "view_documents",
    "analyze_documents",
    "view_graph",
    "sync_graph",
    "view_reports",
    "view_workflow_ops",
    "manage_workflows",
    "view_model_ops",
    "manage_models",
    "manage_playbooks",
    "export_filing_pack",
    "manage_saved_views",
    "view_inbox",
    "manage_auth_settings",
    "manage_users",
    "view_platform_ops",
)


ALL_DESKS: tuple[str, ...] = (
    "dashboard",
    "inbox",
    "control-tower",
    "reports",
    "manager-console",
    "alerts",
    "case-command",
    "intelligence-hub",
    "workflow-ops",
    "model-ops",
    "platform-ops",
    "transactions",
    "documents",
    "entities",
    "watchlist",
    "graph",
    "screening",
    "sar-queue",
    "n8n",
    "camunda",
    "settings",
)


ROLE_DEFINITIONS: dict[str, dict[str, Any]] = {
    "analyst": {
        "display_name": "AML Analyst",
        "description": "Investigates alerts, cases, and supporting evidence.",
        "permissions": [
            "view_dashboard",
            "view_inbox",
            "manage_saved_views",
            "view_alerts",
            "triage_alerts",
            "view_transactions",
            "view_cases",
            "edit_cases",
            "draft_sar",
            "view_documents",
            "analyze_documents",
            "view_entities",
            "resolve_entities",
            "view_graph",
            "view_reports",
            "export_filing_pack",
        ],
        "desk_access": [
            "dashboard",
            "inbox",
            "control-tower",
            "reports",
            "alerts",
            "case-command",
            "intelligence-hub",
            "transactions",
            "documents",
            "entities",
            "watchlist",
            "graph",
            "screening",
        ],
        "default_home": "dashboard",
    },
    "reviewer": {
        "display_name": "SAR Reviewer",
        "description": "Reviews drafted SARs before approval.",
        "permissions": [
            "view_dashboard",
            "view_inbox",
            "manage_saved_views",
            "view_alerts",
            "triage_alerts",
            "view_transactions",
            "view_cases",
            "edit_cases",
            "draft_sar",
            "review_sar",
            "view_documents",
            "analyze_documents",
            "view_entities",
            "resolve_entities",
            "view_graph",
            "view_reports",
            "export_filing_pack",
        ],
        "desk_access": [
            "dashboard",
            "inbox",
            "control-tower",
            "reports",
            "alerts",
            "case-command",
            "sar-queue",
            "intelligence-hub",
            "transactions",
            "documents",
            "entities",
            "watchlist",
            "graph",
            "screening",
        ],
        "default_home": "sar-queue",
    },
    "approver": {
        "display_name": "SAR Approver",
        "description": "Approves and files SARs after review.",
        "permissions": [
            "view_dashboard",
            "view_inbox",
            "manage_saved_views",
            "view_alerts",
            "triage_alerts",
            "view_transactions",
            "view_cases",
            "edit_cases",
            "draft_sar",
            "review_sar",
            "approve_sar",
            "file_sar",
            "view_documents",
            "analyze_documents",
            "view_entities",
            "resolve_entities",
            "view_graph",
            "view_reports",
            "export_filing_pack",
        ],
        "desk_access": [
            "dashboard",
            "inbox",
            "control-tower",
            "reports",
            "alerts",
            "case-command",
            "sar-queue",
            "intelligence-hub",
            "transactions",
            "documents",
            "entities",
            "watchlist",
            "graph",
            "screening",
        ],
        "default_home": "sar-queue",
    },
    "manager": {
        "display_name": "Operations Manager",
        "description": "Owns workload balancing, playbooks, and queue performance.",
        "permissions": [
            "view_dashboard",
            "view_inbox",
            "manage_saved_views",
            "view_alerts",
            "triage_alerts",
            "view_transactions",
            "view_cases",
            "edit_cases",
            "draft_sar",
            "review_sar",
            "approve_sar",
            "file_sar",
            "manage_queues",
            "view_entities",
            "resolve_entities",
            "view_documents",
            "analyze_documents",
            "view_graph",
            "view_reports",
            "view_workflow_ops",
            "manage_playbooks",
            "export_filing_pack",
        ],
        "desk_access": [
            "dashboard",
            "inbox",
            "control-tower",
            "reports",
            "manager-console",
            "alerts",
            "case-command",
            "sar-queue",
            "intelligence-hub",
            "workflow-ops",
            "transactions",
            "documents",
            "entities",
            "watchlist",
            "graph",
            "screening",
        ],
        "default_home": "manager-console",
    },
    "sanctions_analyst": {
        "display_name": "Sanctions Analyst",
        "description": "Runs screening, watchlist, and sanctions-driven investigations.",
        "permissions": [
            "view_dashboard",
            "view_inbox",
            "manage_saved_views",
            "view_alerts",
            "triage_alerts",
            "view_transactions",
            "view_cases",
            "edit_cases",
            "draft_sar",
            "review_sar",
            "view_entities",
            "resolve_entities",
            "view_documents",
            "analyze_documents",
            "view_graph",
            "view_reports",
            "export_filing_pack",
        ],
        "desk_access": [
            "dashboard",
            "inbox",
            "control-tower",
            "reports",
            "alerts",
            "case-command",
            "intelligence-hub",
            "documents",
            "entities",
            "watchlist",
            "graph",
            "screening",
        ],
        "default_home": "watchlist",
    },
    "model_ops": {
        "display_name": "Model Operations",
        "description": "Manages model lifecycle, drift monitoring, and deployment governance.",
        "permissions": [
            "view_dashboard",
            "view_inbox",
            "manage_saved_views",
            "view_reports",
            "view_model_ops",
            "manage_models",
            "view_workflow_ops",
        ],
        "desk_access": [
            "dashboard",
            "inbox",
            "reports",
            "model-ops",
            "workflow-ops",
        ],
        "default_home": "model-ops",
    },
    "workflow_ops": {
        "display_name": "Workflow Operations",
        "description": "Runs orchestration, workflow monitoring, and automation health.",
        "permissions": [
            "view_dashboard",
            "view_inbox",
            "manage_saved_views",
            "view_reports",
            "view_workflow_ops",
            "manage_workflows",
            "view_platform_ops",
        ],
        "desk_access": [
            "dashboard",
            "inbox",
            "reports",
            "workflow-ops",
            "platform-ops",
            "n8n",
            "camunda",
        ],
        "default_home": "workflow-ops",
    },
    "auditor": {
        "display_name": "Auditor",
        "description": "Read-only access for compliance oversight and evidence review.",
        "permissions": [
            "view_dashboard",
            "view_alerts",
            "view_transactions",
            "view_cases",
            "view_entities",
            "view_documents",
            "view_graph",
            "view_reports",
            "view_workflow_ops",
            "view_model_ops",
            "view_inbox",
            "manage_saved_views",
            "export_filing_pack",
        ],
        "desk_access": [
            "dashboard",
            "inbox",
            "reports",
            "control-tower",
            "case-command",
            "sar-queue",
            "intelligence-hub",
            "workflow-ops",
            "model-ops",
            "documents",
            "entities",
            "graph",
        ],
        "default_home": "reports",
    },
    "admin": {
        "display_name": "Platform Admin",
        "description": "Full platform administration and user management.",
        "permissions": ["*"],
        "desk_access": list(ALL_DESKS),
        "default_home": "dashboard",
    },
}


def verify_password(plain_password: str, password_hash: str) -> bool:
    return PASSWORD_CONTEXT.verify(plain_password, password_hash)


def hash_password(plain_password: str) -> str:
    return PASSWORD_CONTEXT.hash(plain_password)


def create_access_token(*, subject: str, expires_at: datetime) -> str:
    payload = {
        "sub": subject,
        "exp": expires_at,
        "iat": _utcnow(),
        "iss": settings.AUTH_JWT_ISSUER,
        "aud": settings.AUTH_JWT_AUDIENCE,
    }
    return jwt.encode(payload, settings.AUTH_JWT_SECRET, algorithm=settings.AUTH_JWT_ALGORITHM)


def _seed_directory_users() -> list[dict[str, Any]]:
    try:
        directory = json.loads(settings.AML_ANALYST_DIRECTORY_JSON)
    except json.JSONDecodeError:
        directory = []
    seeded: list[dict[str, Any]] = []
    for item in directory if isinstance(directory, list) else []:
        if not isinstance(item, dict):
            continue
        username = str(item.get("name") or "").strip()
        if not username:
            continue
        workflows = {str(value or "").strip().lower() for value in item.get("workflows", [])}
        role_key = "analyst"
        if "sar_review" in workflows and "watchlist" in workflows:
            role_key = "analyst"
        elif "sar_review" in workflows:
            role_key = "reviewer"
        elif "watchlist" in workflows:
            role_key = "sanctions_analyst"
        seeded.append(
            {
                "username": username,
                "full_name": username.replace("_", " ").title(),
                "email": f"{username}@goaml.local",
                "role_key": role_key,
                "team_key": str(item.get("team_key") or "global").strip() or "global",
                "team_label": str(item.get("team_label") or "Global Operations").strip() or "Global Operations",
                "regions": [str(value).strip() for value in item.get("regions", []) if str(value).strip()],
                "countries": [str(value).strip().upper() for value in item.get("countries", []) if str(value).strip()],
                "metadata": {"seed_source": "analyst_directory"},
            }
        )
    return seeded


def default_provider_rows() -> list[dict[str, Any]]:
    return [
        {
            "provider_key": "local",
            "display_name": "Local Auth",
            "enabled": True,
            "mode": "password",
            "config": {
                "allow_password_login": True,
                "session_minutes": settings.AUTH_ACCESS_TOKEN_EXPIRE_MINUTES,
                "demo_password_hint": settings.AUTH_DEFAULT_DEMO_PASSWORD,
            },
        },
        {
            "provider_key": "wso2",
            "display_name": "WSO2 Identity Server",
            "enabled": False,
            "mode": "oidc",
            "config": {
                "issuer": settings.AUTH_WSO2_ISSUER,
                "discovery_url": settings.AUTH_WSO2_DISCOVERY_URL,
                "authorize_url": settings.AUTH_WSO2_AUTHORIZE_URL,
                "token_url": settings.AUTH_WSO2_TOKEN_URL,
                "userinfo_url": settings.AUTH_WSO2_USERINFO_URL,
                "jwks_url": settings.AUTH_WSO2_JWKS_URL,
                "client_id": settings.AUTH_WSO2_CLIENT_ID,
                "client_secret": settings.AUTH_WSO2_CLIENT_SECRET,
                "scopes": settings.AUTH_WSO2_SCOPES,
                "redirect_uri": settings.AUTH_WSO2_REDIRECT_URI,
            },
        },
    ]


def default_role_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for role_key, definition in ROLE_DEFINITIONS.items():
        desk_access = [str(value).strip() for value in definition.get("desk_access", []) if str(value).strip()]
        if "settings" not in desk_access:
            desk_access.append("settings")
        rows.append(
            {
                "role_key": role_key,
                "display_name": definition["display_name"],
                "description": definition.get("description"),
                "permissions": definition.get("permissions", []),
                "desk_access": desk_access,
                "metadata": {"default_home": definition.get("default_home", "dashboard")},
            }
        )
    return rows


def default_user_rows() -> list[dict[str, Any]]:
    demo_password_hash = hash_password(settings.AUTH_DEFAULT_DEMO_PASSWORD)
    rows = _seed_directory_users()
    rows.extend(
        [
            {
                "username": "reviewer1",
                "full_name": "Reviewer One",
                "email": "reviewer1@goaml.local",
                "role_key": "reviewer",
                "team_key": "south_asia",
                "team_label": "South Asia AML Pod",
                "regions": ["south_asia"],
                "countries": ["BD", "IN", "PK", "LK", "NP"],
                "metadata": {"seed_source": "local_auth"},
            },
            {
                "username": "approver1",
                "full_name": "Approver One",
                "email": "approver1@goaml.local",
                "role_key": "approver",
                "team_key": "global_ops",
                "team_label": "Global Approval Desk",
                "regions": ["global"],
                "countries": [],
                "metadata": {"seed_source": "local_auth"},
            },
            {
                "username": "manager1",
                "full_name": "Operations Manager",
                "email": "manager1@goaml.local",
                "role_key": "manager",
                "team_key": "global_ops",
                "team_label": "Global Operations",
                "regions": ["global"],
                "countries": [],
                "metadata": {"seed_source": "local_auth"},
            },
            {
                "username": "sanctions1",
                "full_name": "Sanctions Specialist",
                "email": "sanctions1@goaml.local",
                "role_key": "sanctions_analyst",
                "team_key": "mena",
                "team_label": "MENA Sanctions Pod",
                "regions": ["mena"],
                "countries": ["AE", "SA", "IR", "IQ", "EG", "JO", "SY", "LB", "QA", "KW", "OM", "YE", "TR"],
                "metadata": {"seed_source": "local_auth"},
            },
            {
                "username": "modelops1",
                "full_name": "Model Ops",
                "email": "modelops1@goaml.local",
                "role_key": "model_ops",
                "team_key": "model_ops",
                "team_label": "Model Operations",
                "regions": ["global"],
                "countries": [],
                "metadata": {"seed_source": "local_auth"},
            },
            {
                "username": "workflowops1",
                "full_name": "Workflow Ops",
                "email": "workflowops1@goaml.local",
                "role_key": "workflow_ops",
                "team_key": "workflow_ops",
                "team_label": "Workflow Operations",
                "regions": ["global"],
                "countries": [],
                "metadata": {"seed_source": "local_auth"},
            },
            {
                "username": "auditor1",
                "full_name": "Compliance Auditor",
                "email": "auditor1@goaml.local",
                "role_key": "auditor",
                "team_key": "compliance",
                "team_label": "Compliance Audit",
                "regions": ["global"],
                "countries": [],
                "metadata": {"seed_source": "local_auth"},
            },
            {
                "username": "admin1",
                "full_name": "Platform Admin",
                "email": "admin1@goaml.local",
                "role_key": "admin",
                "team_key": "platform",
                "team_label": "Platform Administration",
                "regions": ["global"],
                "countries": [],
                "metadata": {"seed_source": "local_auth"},
            },
        ]
    )
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for row in rows:
        username = str(row.get("username") or "").strip().lower()
        if not username or username in seen:
            continue
        seen.add(username)
        normalized.append(
            {
                **row,
                "username": username,
                "password_hash": demo_password_hash,
                "auth_provider": "local",
                "is_active": True,
                "must_change_password": False,
            }
        )
    return normalized


def permissions_for_role(role_key: str, role_overrides: list[str] | None = None) -> list[str]:
    if role_overrides:
        return sorted({str(value).strip() for value in role_overrides if str(value).strip()})
    definition = ROLE_DEFINITIONS.get(role_key, ROLE_DEFINITIONS["analyst"])
    permissions = [str(value).strip() for value in definition.get("permissions", []) if str(value).strip()]
    return sorted(set(permissions))


def desk_access_for_role(role_key: str, role_overrides: list[str] | None = None) -> list[str]:
    if role_overrides:
        values = [str(value).strip() for value in role_overrides if str(value).strip()]
        if "settings" not in values:
            values.append("settings")
        return values
    definition = ROLE_DEFINITIONS.get(role_key, ROLE_DEFINITIONS["analyst"])
    values = [str(value).strip() for value in definition.get("desk_access", []) if str(value).strip()]
    if "settings" not in values:
        values.append("settings")
    return values


def has_permission(user_permissions: list[str], permission: str) -> bool:
    permission_key = str(permission or "").strip()
    perms = {str(value).strip() for value in user_permissions if str(value).strip()}
    return "*" in perms or permission_key in perms
