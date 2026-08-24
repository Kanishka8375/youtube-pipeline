"""Workspaces, membership, audit trail and config profiles."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, db_session, resolve_workspace
from app.db.models import ConfigProfile, User, Workspace
from app.services.audit.audit_service import ACTION_MEMBER_ADDED, AuditService
from app.services.auth.auth_service import AuthService
from app.services.auth.roles import OWNER, VALID_ROLES
from app.services.workspaces.workspace_service import (
    DuplicateWorkspaceError,
    InsufficientRoleError,
    WorkspaceService,
)

router = APIRouter()


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    settings_json: Dict[str, Any] = Field(default_factory=dict)


class MemberAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    role: str = Field(default="member")


class ConfigProfileUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_key: str = Field(min_length=1, max_length=128)
    profile_json: Dict[str, Any] = Field(default_factory=dict)


#: Field names that hold credentials. Matched as whole words against the
#: underscore-separated parts of a key, not as substrings: a substring test on
#: "key" also rejects `provider_key`, which is exactly the setting this feature
#: exists to store.
_SECRET_WORDS = frozenset(
    {"key", "keys", "secret", "secrets", "token", "tokens", "password", "passwd",
     "credential", "credentials", "apikey", "auth"}
)
#: Names containing a secret word that are not secrets. "token" is the
#: ambiguous one: in this domain it usually means an LLM billing unit, not a
#: credential, so every token-*count* name is listed here explicitly.
_SECRET_ALLOWLIST = frozenset(
    {
        "provider_key", "profile_key", "model_key", "template_key", "suite_key",
        "max_tokens", "min_tokens", "input_tokens", "output_tokens",
        "total_tokens", "budget_tokens", "thinking_tokens",
    }
)


def _secret_like_keys(profile_json: Dict[str, Any]) -> set:
    """Keys that look like they hold a credential."""
    found = set()
    for key in profile_json:
        lowered = key.lower()
        if lowered in _SECRET_ALLOWLIST:
            continue
        if _SECRET_WORDS & set(lowered.replace("-", "_").split("_")):
            found.add(key)
    return found


def _workspace_payload(workspace: Workspace) -> dict:
    return {
        "id": str(workspace.id),
        "name": workspace.name,
        "slug": workspace.slug,
        "settings_json": workspace.settings_json,
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_workspace(
    body: WorkspaceCreate,
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    """Create a workspace. The caller becomes its owner."""
    try:
        workspace = WorkspaceService(session).create(
            name=body.name, owner=user, settings_json=body.settings_json
        )
    except DuplicateWorkspaceError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    session.commit()
    return _workspace_payload(workspace)


@router.get("")
def list_workspaces(
    session: Session = Depends(db_session),
    user: User = Depends(current_user),
):
    """Only workspaces this user belongs to."""
    return [_workspace_payload(w) for w in WorkspaceService(session).for_user(user)]


@router.get("/{workspace_slug}")
def get_workspace(workspace: Workspace = Depends(resolve_workspace)):
    return _workspace_payload(workspace)


@router.get("/{workspace_slug}/members")
def list_members(
    workspace: Workspace = Depends(resolve_workspace),
    session: Session = Depends(db_session),
):
    rows = WorkspaceService(session).members(workspace.id)
    out = []
    for membership in rows:
        member = session.get(User, membership.user_id)
        out.append(
            {
                "user_id": str(membership.user_id),
                "email": member.email if member else None,
                "full_name": member.full_name if member else None,
                "role": membership.role,
            }
        )
    return out


@router.post("/{workspace_slug}/members", status_code=status.HTTP_201_CREATED)
def add_member(
    body: MemberAdd,
    workspace: Workspace = Depends(resolve_workspace),
    session: Session = Depends(db_session),
    actor: User = Depends(current_user),
):
    """Add or re-role a member. Owners only."""
    if body.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"role must be one of {sorted(VALID_ROLES)}",
        )

    target = AuthService(session).by_email(body.email)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"No user with email {body.email}"
        )

    service = WorkspaceService(session)
    try:
        membership = service.add_member(
            workspace=workspace, user=target, role=body.role, actor=actor
        )
    except InsufficientRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    AuditService(session).record(
        action=ACTION_MEMBER_ADDED,
        entity_type="workspace_membership",
        entity_id=str(membership.id),
        actor=actor,
        workspace=workspace,
        message=f"{target.email} is now {body.role} in {workspace.slug}",
        metadata={"target_user_id": str(target.id), "role": body.role},
    )
    session.commit()
    return {"user_id": str(target.id), "email": target.email, "role": membership.role}


@router.get("/{workspace_slug}/audit-log")
def workspace_audit_log(
    limit: int = 100,
    workspace: Workspace = Depends(resolve_workspace),
    session: Session = Depends(db_session),
):
    entries = AuditService(session).for_workspace(workspace.id, limit=min(limit, 500))
    return [
        {
            "action": e.action,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "actor_user_id": str(e.actor_user_id) if e.actor_user_id else None,
            "message": e.message,
            "correlation_id": e.correlation_id,
            "metadata": e.metadata_json,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]


@router.put("/{workspace_slug}/config-profiles")
def upsert_config_profile(
    body: ConfigProfileUpsert,
    workspace: Workspace = Depends(resolve_workspace),
    session: Session = Depends(db_session),
    actor: User = Depends(current_user),
):
    """Set a workspace config profile, e.g. which LLM answers for this team.

    Owners only, and secrets are refused: API keys belong in the environment,
    not in a row any workspace member can read back.
    """
    try:
        WorkspaceService(session).require_role(
            workspace=workspace, user=actor, required_role=OWNER
        )
    except InsufficientRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    secret_like = sorted(_secret_like_keys(body.profile_json))
    if secret_like:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Refusing to store {sorted(secret_like)} in a config profile. "
                "Credentials belong in the environment, not the database."
            ),
        )

    existing = session.scalar(
        select(ConfigProfile).where(
            ConfigProfile.workspace_id == workspace.id,
            ConfigProfile.profile_key == body.profile_key,
        )
    )
    if existing is None:
        existing = ConfigProfile(
            workspace_id=workspace.id,
            profile_key=body.profile_key,
            profile_json=body.profile_json,
        )
        session.add(existing)
    else:
        existing.profile_json = body.profile_json
    session.flush()
    session.commit()
    return {"profile_key": existing.profile_key, "profile_json": existing.profile_json}


@router.get("/{workspace_slug}/config-profiles")
def list_config_profiles(
    workspace: Workspace = Depends(resolve_workspace),
    session: Session = Depends(db_session),
):
    rows = session.scalars(
        select(ConfigProfile).where(ConfigProfile.workspace_id == workspace.id)
    ).all()
    return [{"profile_key": r.profile_key, "profile_json": r.profile_json} for r in rows]
