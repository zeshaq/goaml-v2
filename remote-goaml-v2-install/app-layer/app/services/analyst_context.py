"""
Analyst profile, team presets, and role-based desk defaults.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.auth import get_auth_user
from services.routing import analyst_directory


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _derive_role_key(actor: str, workflows: list[str]) -> str:
    actor_key = str(actor or "").lower()
    workflow_set = {str(item or "").strip().lower() for item in workflows}
    if actor_key.startswith("approver"):
        return "approver"
    if actor_key.startswith("manager") or actor_key.endswith("ops"):
        return "operations_manager"
    if "sar_review" in workflow_set and "watchlist" in workflow_set:
        return "aml_analyst"
    if "sar_review" in workflow_set:
        return "sar_reviewer"
    if "watchlist" in workflow_set:
        return "watchlist_analyst"
    return "operations_analyst"


def _fallback_profile(actor: str) -> dict[str, Any]:
    return {
        "actor": actor,
        "role_key": _derive_role_key(actor, ["general"]),
        "team_key": "global",
        "team_label": "Global Operations",
        "regions": ["global"],
        "countries": [],
        "workflows": ["general"],
        "team_members": [actor],
    }


def _profile_for_actor(actor: str) -> dict[str, Any]:
    actor_key = str(actor or "").strip() or "analyst1"
    directory = analyst_directory()
    match = next((item for item in directory if str(item.get("name")) == actor_key), None)
    if not match:
        return _fallback_profile(actor_key)
    team_key = str(match.get("team_key") or "global")
    team_members = sorted(
        {
            str(item.get("name"))
            for item in directory
            if str(item.get("team_key") or "global") == team_key and str(item.get("name") or "").strip()
        }
    )
    workflows = [str(item) for item in match.get("workflows", []) if str(item).strip()]
    return {
        "actor": actor_key,
        "role_key": _derive_role_key(actor_key, workflows),
        "team_key": team_key,
        "team_label": str(match.get("team_label") or team_key.replace("_", " ").title()),
        "regions": [str(item) for item in match.get("regions", []) if str(item).strip()],
        "countries": [str(item) for item in match.get("countries", []) if str(item).strip()],
        "workflows": workflows,
        "team_members": team_members or [actor_key],
    }


def _make_preset(
    *,
    scope: str,
    key: str,
    name: str,
    description: str,
    filters: dict[str, Any],
    profile: dict[str, Any],
    is_default: bool = False,
) -> dict[str, Any]:
    return {
        "id": f"preset:{scope}:{key}",
        "scope": scope,
        "name": name,
        "description": description,
        "kind": "system_preset",
        "is_default": is_default,
        "filters": filters,
        "metadata": {
            "source": "analyst_context",
            "role_key": profile["role_key"],
            "team_key": profile["team_key"],
        },
    }


def _desk_presets(profile: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    actor = profile["actor"]
    team_key = profile["team_key"]
    team_label = profile["team_label"]
    team_members = profile.get("team_members", []) or [actor]

    alerts_presets = [
        _make_preset(
            scope="alerts",
            key="my-open",
            name="My Open Alerts",
            description="Open alerts currently assigned to you.",
            filters={"status": "open", "assigned_to": actor, "assigned_to_any": [actor]},
            profile=profile,
            is_default=True,
        ),
        _make_preset(
            scope="alerts",
            key="team-hot",
            name=f"{team_label} Hot Alerts",
            description="Open high and critical alerts assigned to your pod.",
            filters={
                "status": "open",
                "severity_levels": ["high", "critical"],
                "assigned_to_any": team_members,
                "team_key": team_key,
            },
            profile=profile,
        ),
        _make_preset(
            scope="alerts",
            key="unassigned-escalations",
            name="Unassigned Escalations",
            description="High-severity open alerts still waiting for an analyst owner.",
            filters={"status": "open", "severity_levels": ["high", "critical"], "ownership": "unassigned"},
            profile=profile,
        ),
    ]

    sar_default_key = "my-review"
    if profile["role_key"] == "approver":
        sar_default_key = "team-ready-file"
    elif profile["role_key"] == "operations_manager":
        sar_default_key = "team-breaches"

    sar_presets = [
        _make_preset(
            scope="sar_queue",
            key="my-review",
            name="My Review Queue",
            description="SAR items currently routed to you for review.",
            filters={"queue": "review", "owner": actor, "owners": [actor]},
            profile=profile,
            is_default=sar_default_key == "my-review",
        ),
        _make_preset(
            scope="sar_queue",
            key="team-breaches",
            name=f"{team_label} SLA Breaches",
            description="Breached SAR items owned by your pod.",
            filters={"queue": "review", "sla": "breached", "owner_team_key": team_key, "owners": team_members},
            profile=profile,
            is_default=sar_default_key == "team-breaches",
        ),
        _make_preset(
            scope="sar_queue",
            key="team-ready-file",
            name=f"{team_label} Ready to File",
            description="Approved SARs owned by your pod and ready for filing.",
            filters={"queue": "approval", "owner_team_key": team_key, "owners": team_members},
            profile=profile,
            is_default=sar_default_key == "team-ready-file",
        ),
    ]

    inbox_default_key = "my-active"
    if profile["role_key"] == "operations_manager":
        inbox_default_key = "team-ops"

    inbox_presets = [
        _make_preset(
            scope="inbox",
            key="my-active",
            name="My Active Inbox",
            description="All active tasks and notifications currently in your inbox.",
            filters={"state": "active"},
            profile=profile,
            is_default=inbox_default_key == "my-active",
        ),
        _make_preset(
            scope="inbox",
            key="my-tasks",
            name="My Tasks",
            description="Focus only on analyst tasks that need action.",
            filters={"state": "active", "item_types": ["task"]},
            profile=profile,
        ),
        _make_preset(
            scope="inbox",
            key="team-ops",
            name=f"{team_label} Notifications",
            description="Team-facing workflow and operational notifications for your pod.",
            filters={"state": "active", "team_key": team_key, "item_types": ["notification"]},
            profile=profile,
            is_default=inbox_default_key == "team-ops",
        ),
    ]

    return {
        "alerts": alerts_presets,
        "sar_queue": sar_presets,
        "inbox": inbox_presets,
    }


async def get_analyst_context(actor: str) -> dict[str, Any]:
    auth_user = await get_auth_user(actor)
    if auth_user:
        directory = analyst_directory()
        team_members = sorted(
            {
                str(item.get("name"))
                for item in directory
                if str(item.get("team_key") or "global") == auth_user.team_key and str(item.get("name") or "").strip()
            }
        ) or [auth_user.username]
        profile = {
            "actor": auth_user.username,
            "role_key": auth_user.role_key,
            "team_key": auth_user.team_key,
            "team_label": auth_user.team_label,
            "regions": auth_user.regions,
            "countries": auth_user.countries,
            "workflows": list(auth_user.metadata.get("workflows") or []),
            "team_members": team_members,
        }
    else:
        profile = _profile_for_actor(actor)
    presets = _desk_presets(profile)
    desk_defaults = {
        scope: next((item["id"] for item in items if item.get("is_default")), items[0]["id"] if items else "")
        for scope, items in presets.items()
    }
    summary = [
        f"{profile['actor']} belongs to {profile['team_label']}.",
        f"Role defaults are available for {', '.join(sorted(presets.keys()))} desks.",
        f"Team presets cover {len(profile.get('team_members', []))} analyst accounts in the pod.",
    ]
    return {
        "generated_at": _utcnow(),
        "profile": profile,
        "desk_defaults": desk_defaults,
        "desk_presets": presets,
        "summary": summary,
    }
