"""Workspaces and the memberships that gate access to them."""

from __future__ import annotations

import re
import uuid
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Workspace, WorkspaceMembership
from app.services.auth.roles import OWNER, VALID_ROLES, allows

_SLUG_SAFE = re.compile(r"[^a-z0-9]+")


class DuplicateWorkspaceError(ValueError):
    """Raised when a workspace name or slug is already taken."""


class NotAMemberError(PermissionError):
    """Raised when a user has no membership in the workspace they addressed.

    Deliberately indistinguishable, at the API layer, from "no such workspace":
    telling a stranger that a workspace exists is itself a leak.
    """


class InsufficientRoleError(PermissionError):
    """Raised when a member's role does not reach what the action requires."""


def slugify(value: str) -> str:
    slug = _SLUG_SAFE.sub("-", value.strip().lower()).strip("-")
    if not slug:
        raise ValueError(f"{value!r} does not reduce to a usable slug")
    return slug


class WorkspaceService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(self, *, name: str, owner: User, settings_json: Optional[dict] = None) -> Workspace:
        """Create a workspace and make its creator the owner.

        The owner membership is written in the same flush as the workspace. A
        workspace with no owner is unadministrable -- nobody can add the first
        member -- so the two rows are one operation, not two.
        """
        slug = slugify(name)
        clash = self.session.scalar(
            select(Workspace).where((Workspace.slug == slug) | (Workspace.name == name))
        )
        if clash is not None:
            raise DuplicateWorkspaceError(f"A workspace named {name!r} already exists")

        workspace = Workspace(name=name, slug=slug, settings_json=settings_json or {})
        self.session.add(workspace)
        self.session.flush()

        self.session.add(
            WorkspaceMembership(workspace_id=workspace.id, user_id=owner.id, role=OWNER)
        )
        self.session.flush()
        return workspace

    def by_slug(self, slug: str) -> Optional[Workspace]:
        return self.session.scalar(select(Workspace).where(Workspace.slug == slug))

    def for_user(self, user: User) -> Sequence[Workspace]:
        """Only the workspaces this user belongs to -- never the whole table."""
        return self.session.scalars(
            select(Workspace)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(WorkspaceMembership.user_id == user.id)
            .order_by(Workspace.name)
        ).all()

    def membership(self, workspace_id: uuid.UUID, user_id: uuid.UUID) -> Optional[WorkspaceMembership]:
        return self.session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user_id,
            )
        )

    def members(self, workspace_id: uuid.UUID) -> Sequence[WorkspaceMembership]:
        return self.session.scalars(
            select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
        ).all()

    def add_member(
        self, *, workspace: Workspace, user: User, role: str, actor: User
    ) -> WorkspaceMembership:
        if role not in VALID_ROLES:
            raise ValueError(f"role must be one of {sorted(VALID_ROLES)}, got {role!r}")
        self.require_role(workspace=workspace, user=actor, required_role=OWNER)

        existing = self.membership(workspace.id, user.id)
        if existing is not None:
            existing.role = role
            self.session.flush()
            return existing

        membership = WorkspaceMembership(
            workspace_id=workspace.id, user_id=user.id, role=role
        )
        self.session.add(membership)
        self.session.flush()
        return membership

    # -- authorisation -------------------------------------------------------
    def require_member(self, *, workspace: Workspace, user: User) -> WorkspaceMembership:
        """The membership, or raise. A superuser is a member of everything.

        The superuser bypass exists so the first account can administer a
        workspace it was not added to -- otherwise a mis-set role locks
        everyone out with no recovery path.
        """
        membership = self.membership(workspace.id, user.id)
        if membership is None:
            if user.is_superuser:
                return WorkspaceMembership(
                    workspace_id=workspace.id, user_id=user.id, role=OWNER
                )
            raise NotAMemberError(f"{user.email} is not a member of {workspace.slug}")
        return membership

    def require_role(self, *, workspace: Workspace, user: User, required_role: str) -> WorkspaceMembership:
        membership = self.require_member(workspace=workspace, user=user)
        if not allows(membership.role, required_role):
            raise InsufficientRoleError(
                f"{user.email} is {membership.role} in {workspace.slug}; "
                f"this action needs {required_role}"
            )
        return membership
